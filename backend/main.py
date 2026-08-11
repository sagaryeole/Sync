import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

import config
from database import get_session, init_db, close_db
from models import Asset, PriceTicker, Portfolio, TradeLog, Candle, Signal, Strategy as StrategyModel
from settings import get_settings
from feeds.symbols import SYMBOLS
from feeds.backfill import backfill_candles
from feeds.manager import FeedManager
from engine.market_state import MARKET
from engine.core import PaperEngine, EngineConfig
from engine.paper_broker import PaperBroker
from engine.risk import RiskConfig, RiskManager
from scheduler import start_scheduler
from sqlalchemy.dialects.sqlite import insert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api.main")

# Global scheduler reference
scheduler = None
feed_manager = FeedManager()
background_tasks = set()

_settings = get_settings()
ENGINE = PaperEngine(
    market_state=MARKET,
    broker=PaperBroker(
        MARKET,
        taker_fee_bps=_settings.taker_fee_bps,
        maker_fee_bps=_settings.maker_fee_bps,
        slippage_bps=_settings.slippage_bps,
        impact_notional=_settings.impact_notional,
        min_notional=_settings.min_notional,
        tradable_symbols=set(_settings.symbols),
    ),
    risk_manager=RiskManager(RiskConfig(
        max_open_positions=_settings.max_open_positions,
        max_position_pct=_settings.max_position_pct,
        risk_per_trade_pct=_settings.risk_per_trade_pct,
        stop_loss_pct=_settings.stop_loss_pct,
        take_profit_pct=_settings.take_profit_pct,
        max_drawdown_pct=_settings.max_drawdown_pct,
        min_notional=_settings.min_notional,
    )),
    config=EngineConfig(
        starting_cash=_settings.starting_cash,
        max_open_positions=_settings.max_open_positions,
    ),
)


def load_engine_from_db() -> None:
    """Register every DB strategy row with ENGINE and warm-start its account
    from the persisted portfolios/positions cache.

    This is a best-effort warm start, not the deterministic fills-replay H5
    calls for — a crash between a fill and its DB commit can still diverge.
    That gap is tracked (TODO.md H5) and not closed by this function.
    """
    from models import PortfolioAccount as PortfolioAccountModel, Position as PositionModel

    session = get_session()
    try:
        for strat in session.query(StrategyModel).all():
            ENGINE.register_strategy(strat.id, strat.key, float(strat.starting_cash))
            account = ENGINE.get_account(strat.id)
            saved = session.query(PortfolioAccountModel).filter_by(strategy_id=strat.id).first()
            if saved is not None:
                account.cash = float(saved.cash)
                account.realized_pnl = float(saved.realized_pnl)
                account.fees_paid = float(saved.fees_paid)
                account.peak_equity = float(saved.peak_equity)
                account.is_halted = bool(saved.is_halted)
                account.halt_reason = saved.halt_reason
            for pos_row in session.query(PositionModel).filter_by(strategy_id=strat.id).all():
                if float(pos_row.quantity) <= 0:
                    continue
                from engine.portfolio import Position as EnginePosition
                account.positions[pos_row.symbol] = EnginePosition(
                    symbol=pos_row.symbol,
                    quantity=float(pos_row.quantity),
                    avg_entry_price=float(pos_row.avg_entry_price),
                    stop_loss_price=float(pos_row.stop_loss_price) if pos_row.stop_loss_price is not None else None,
                    take_profit_price=float(pos_row.take_profit_price) if pos_row.take_profit_price is not None else None,
                    opened_at=pos_row.opened_at,
                    updated_at=pos_row.updated_at,
                )
    finally:
        session.close()

async def candle_flusher_task():
    """Background task to flush rolled/closed candles to the SQLite database."""
    settings = get_settings()
    while True:
        try:
            await asyncio.sleep(settings.candle_flush_seconds)
            closed = MARKET.drain_closed_candles()
            if not closed:
                continue

            session = get_session()
            try:
                for candle in closed:
                    stmt = insert(Candle).values(
                        symbol=candle.symbol,
                        interval=candle.interval,
                        open_time=candle.open_time,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                        trades=candle.trades,
                        source=candle.source
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["symbol", "interval", "open_time"],
                        set_={
                            "open": stmt.excluded.open,
                            "high": stmt.excluded.high,
                            "low": stmt.excluded.low,
                            "close": stmt.excluded.close,
                            "volume": stmt.excluded.volume,
                            "trades": stmt.excluded.trades,
                            "source": stmt.excluded.source
                        }
                    )
                    session.execute(stmt)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error("Error in database candle flusher: %s", e)
            finally:
                session.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Unexpected error in candle flusher loop: %s", e)

async def legacy_price_syncer_task():
    """Syncs live tick prices from MARKET to the legacy PriceTicker table for compatibility."""
    settings = get_settings()
    while True:
        try:
            await asyncio.sleep(5.0)
            session = get_session()
            try:
                for sym in settings.symbols:
                    price = MARKET.last(sym)
                    if price is not None:
                        session.add(PriceTicker(
                            symbol=sym,
                            price=price,
                            timestamp=datetime.now(timezone.utc)
                        ))
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error("Error syncing legacy prices: %s", e)
            finally:
                session.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Unexpected error in legacy price syncer: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB on startup, shut down scheduler on exit."""
    global scheduler
    
    # 1. DB setup & seed
    init_db()
    
    # 2. REST Candle backfills
    settings = get_settings()
    await backfill_candles(settings.symbols)
    
    # 3. Warm MarketState
    MARKET.warm_from_db()

    # 4. Load strategies + warm-start portfolio accounts, then start the
    # engine scheduler (engine_tick, strategy_tick, equity_snapshot, prune).
    # Replaces the old bot.py:start_bot() single MA-crossover cycle.
    load_engine_from_db()
    scheduler = start_scheduler(ENGINE, MARKET, settings.symbols)
    
    # 5. Start live FeedManager streaming
    async def run_feed():
        await feed_manager.start(
            symbols=settings.symbols,
            on_tick=MARKET.on_tick,
            on_status=lambda s: None,
            on_provider_change=lambda p: MARKET.close_all_candles()
        )
    feed_task = asyncio.create_task(run_feed())
    background_tasks.add(feed_task)

    # 6. Start background synchronization tasks
    flusher_task = asyncio.create_task(candle_flusher_task())
    syncer_task = asyncio.create_task(legacy_price_syncer_task())
    background_tasks.add(flusher_task)
    background_tasks.add(syncer_task)
    
    yield
    
    # --- Shutdown reverse sequence ---
    logger.info("Initiating server shutdown sequence...")
    
    if scheduler:
        scheduler.shutdown(wait=True)
        
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    background_tasks.clear()
    
    # Final candle flush
    MARKET.close_all_candles()
    closed = MARKET.drain_closed_candles()
    if closed:
        session = get_session()
        try:
            for candle in closed:
                stmt = insert(Candle).values(
                    symbol=candle.symbol,
                    interval=candle.interval,
                    open_time=candle.open_time,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    trades=candle.trades,
                    source=candle.source
                )
                session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Final candle flush failed: %s", e)
        finally:
            session.close()

    await feed_manager.stop()
    close_db()
    logger.info("Shutdown sequence complete.")


app = FastAPI(
    title="Crypto Trade API",
    description="Mock crypto trading bot with simulated prices and portfolio.",
    version="0.1.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


MAX_LIST_LIMIT = 1000


# Pydantic models for API response (database models are SQLAlchemy)

class PriceTickerResponse(BaseModel):
    id: int
    symbol: str
    price: float
    timestamp: str


class AssetResponse(BaseModel):
    id: int
    symbol: str
    name: str


class PortfolioItem(BaseModel):
    symbol: str = Field(..., pattern="^[A-Z0-9]{2,10}$|USD")
    balance: float = Field(default=0)
    quantity: float = Field(default=0)
    cost_basis: float = Field(default=0)


class TradeLogResponse(BaseModel):
    id: int
    type: str
    symbol: str
    quantity: float
    price: float
    timestamp: datetime


class ExecuteTradeRequest(BaseModel):
    type: str = Field(..., pattern="^(BUY|SELL)$")
    symbol: str = Field(..., pattern="^[A-Z0-9]{2,10}$")
    quantity: float = Field(..., ge=0)


class ExecuteTradeResponse(BaseModel):
    status: str
    type: str
    symbol: str
    quantity: float
    price: float


# Dependency: provides a fresh DB session per request and closes it afterwards.
def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# Health check
@app.get("/health")
def health_check():
    status_info = feed_manager.get_status()
    return {
        "status": "ok",
        "provider": status_info["provider"],
        "mode": status_info["mode"]
    }


# Assets route
@app.get("/assets")
def list_assets(db: Session = Depends(get_db)) -> List[AssetResponse]:
    return [AssetResponse(id=a.id, symbol=a.symbol, name=a.name) for a in db.query(Asset)]


@app.get("/assets/{symbol}")
def get_asset(symbol: str, db: Session = Depends(get_db)) -> AssetResponse:
    asset = db.query(Asset).filter_by(symbol=symbol).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse(id=asset.id, symbol=asset.symbol, name=asset.name)


# Prices route
@app.get("/prices", response_model=List[PriceTickerResponse])
def list_prices(start: Optional[datetime] = None, asset: Optional[str] = None, db: Session = Depends(get_db)) -> List[PriceTickerResponse]:
    query = db.query(PriceTicker).order_by(PriceTicker.timestamp.desc())
    if asset:
        query = query.filter(PriceTicker.symbol == asset)
    if start:
        query = query.filter(PriceTicker.timestamp >= start)
    data = list(query.limit(100).all())
    return [PriceTickerResponse(
        id=p.id,
        symbol=p.symbol,
        price=float(p.price),
        timestamp=p.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    ) for p in data]


# Portfolio routes
@app.get("/portfolio", response_model=List[PortfolioItem])
def list_portfolio(db: Session = Depends(get_db)) -> List[PortfolioItem]:
    """List all portfolio positions."""
    positions = db.query(Portfolio).all()
    return [
        PortfolioItem(
            symbol=p.symbol,
            balance=float(p.balance),
            quantity=float(p.quantity),
            cost_basis=float(p.cost_basis)
        )
        for p in positions
    ]


@app.get("/portfolio/{symbol}", response_model=PortfolioItem)
def get_portfolio(symbol: str, db: Session = Depends(get_db)) -> PortfolioItem:
    """Get a single portfolio position by symbol."""
    p = db.query(Portfolio).filter_by(symbol=symbol).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio entry not found")
    return PortfolioItem(
        symbol=p.symbol,
        balance=float(p.balance),
        quantity=float(p.quantity),
        cost_basis=float(p.cost_basis)
    )


def _legacy_execute_trade(db: Session, trade_type: str, symbol: str, quantity: float, price: float) -> bool:
    """Legacy weighted-average cost-basis accounting against the old Portfolio/TradeLog tables.

    Ported verbatim from the now-deleted bot.py:execute_trade (step 26/37). Kept
    only for the POST /trade REST shim — the same logic was also ported into
    engine/portfolio.py:PortfolioAccount.apply_fill for the new engine's
    `manual` strategy. Delete this alongside the rest of the Phase-1 shims in
    Phase 3, step 46.
    """
    timestamp = datetime.now(timezone.utc)
    quantity = float(quantity)
    price = float(price)

    coin_portfolio = db.query(Portfolio).filter_by(symbol=symbol).first()
    if not coin_portfolio:
        coin_portfolio = Portfolio(symbol=symbol, balance=0, quantity=0, cost_basis=0)
        db.add(coin_portfolio)
        db.flush()

    usd_portfolio = db.query(Portfolio).filter_by(symbol="USD").first()

    if trade_type == "BUY":
        cost = quantity * price
        if not usd_portfolio or float(usd_portfolio.balance) < cost:
            return False

        usd_portfolio.balance = float(usd_portfolio.balance) - cost

        old_qty = float(coin_portfolio.quantity)
        old_cb = float(coin_portfolio.cost_basis)
        new_qty = old_qty + quantity
        if new_qty > 0:
            new_cb = (old_qty * old_cb + quantity * price) / new_qty
        else:
            new_cb = 0

        coin_portfolio.balance = float(coin_portfolio.balance) - cost
        coin_portfolio.quantity = new_qty
        coin_portfolio.cost_basis = new_cb

    else:  # SELL
        if float(coin_portfolio.quantity) <= 0:
            return False

        qty_to_sell = min(float(coin_portfolio.quantity), quantity)
        revenue = qty_to_sell * price

        if usd_portfolio:
            usd_portfolio.balance = float(usd_portfolio.balance) + revenue

        remaining_qty = float(coin_portfolio.quantity) - qty_to_sell
        if remaining_qty > 0:
            coin_portfolio.balance = float(coin_portfolio.balance) + revenue
            coin_portfolio.quantity = remaining_qty
        else:
            coin_portfolio.balance = float(coin_portfolio.balance) + revenue
            coin_portfolio.quantity = 0
            coin_portfolio.cost_basis = 0

    db.add(TradeLog(
        type=trade_type, symbol=symbol,
        quantity=quantity, price=price, timestamp=timestamp
    ))
    db.commit()
    return True


# Execute trade
@app.post("/trade", response_model=ExecuteTradeResponse, status_code=status.HTTP_201_CREATED)
def execute_trade_endpoint(request: ExecuteTradeRequest, db: Session = Depends(get_db)):
    if request.type not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Invalid trade type")
    if request.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity must be non-negative")
    asset = db.query(Asset).filter_by(symbol=request.symbol).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    latest_price = db.query(PriceTicker).filter_by(symbol=request.symbol).order_by(
        PriceTicker.timestamp.desc()
    ).first()
    if not latest_price:
        raise HTTPException(status_code=404, detail="No price data for asset")
    price = float(latest_price.price)

    # For SELL, use the user's requested quantity (or all holdings if 0)
    quantity = float(request.quantity)
    if request.type == "SELL" and quantity == 0:
        portfolio = db.query(Portfolio).filter_by(symbol=request.symbol).first()
        if not portfolio or float(portfolio.quantity) <= 0:
            raise HTTPException(status_code=400, detail="Not enough balance to sell")
        quantity = float(portfolio.quantity)

    # Execute the user's trade
    success = _legacy_execute_trade(db, request.type, request.symbol, quantity, price)
    if not success:
        if request.type == "BUY":
            raise HTTPException(status_code=400, detail="Insufficient USD balance")
        else:
            raise HTTPException(status_code=400, detail="Not enough holdings to sell")

    return {
        "status": "trade executed",
        "type": request.type,
        "symbol": request.symbol,
        "quantity": quantity,
        "price": price
    }


# Trade log route
@app.get("/trades", response_model=List[TradeLogResponse])
def list_trades(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)) -> List[TradeLogResponse]:
    data = db.query(TradeLog).order_by(TradeLog.timestamp.desc()).offset(offset).limit(min(limit, MAX_LIST_LIMIT)).all()
    return [TradeLogResponse(
        id=t.id,
        type=t.type,
        symbol=t.symbol,
        quantity=float(t.quantity),
        price=float(t.price),
        timestamp=t.timestamp.replace(tzinfo=timezone.utc)
    ) for t in data]


# Bot signal route
@app.get("/bot/signals")
def get_bot_signals(db: Session = Depends(get_db)) -> dict:
    """Return the most recent non-HOLD signal per asset, across all strategies.

    Repointed at the new `signals` table (populated by StrategyRunner every
    strategy_tick) now that the legacy MA-crossover bot.py is gone. `None`
    means no strategy has produced a BUY/SELL signal for that symbol yet
    (e.g. still warming up).
    """
    signals = {}
    for asset in config.ASSETS:
        latest = (
            db.query(Signal)
            .filter_by(symbol=asset["symbol"])
            .order_by(Signal.ts.desc())
            .first()
        )
        signals[asset["symbol"]] = latest.action if latest else None
    return signals
