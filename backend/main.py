import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import config
from database import get_session, init_db, close_db
from models import Candle, Signal, Fill as FillModel, Strategy as StrategyModel, PriceTicker
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

from api.market import router as market_router
from api.trading import router as trading_router
from api.bot import router as bot_router
from api.strategies import router as strategies_router
from api.ws_routes import router as ws_router

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
    load_engine_from_db()

    # H5: deterministic replay of fills to verify cached snapshot
    session = get_session()
    try:
        fills_by_strategy: Dict[int, List[FillModel]] = {}
        for f in session.query(FillModel).order_by(FillModel.ts).all():
            fills_by_strategy.setdefault(f.strategy_id, []).append(f)
        marks = {sym: MARKET.last(sym) for sym in settings.symbols if MARKET.last(sym) is not None}
        rebuild = ENGINE.rebuild_from_fills(fills_by_strategy, marks)
        logger.info("H5 startup rebuild: %s strategies rebuilt from fills", len(rebuild))
    finally:
        session.close()

    scheduler = start_scheduler(ENGINE, MARKET, settings.symbols, feed_manager)

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

app.include_router(market_router)
app.include_router(trading_router)
app.include_router(bot_router)
app.include_router(strategies_router)
app.include_router(ws_router)
