from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import config
from database import get_session, init_db, close_db
from models import Asset, PriceTicker, Portfolio, TradeLog
from bot import run_bot_cycle, generate_mock_price, get_signal, start_bot

# Global scheduler reference
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB on startup, shut down scheduler on exit."""
    global scheduler
    init_db()
    scheduler = start_bot()
    yield
    if scheduler:
        scheduler.shutdown()
    close_db()


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
    symbol: str = Field(..., pattern="^[A-Z]{3}$|USD")
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
    symbol: str = Field(..., pattern="^[A-Z]{3}$")
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
    return {"status": "ok"}


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
    from bot import execute_trade
    success = execute_trade(db, request.type, request.symbol, quantity, price)
    if not success:
        if request.type == "BUY":
            raise HTTPException(status_code=400, detail="Insufficient USD balance")
        else:
            raise HTTPException(status_code=400, detail="Not enough holdings to sell")

    # Refresh prices and run bot logic
    run_bot_cycle(db)

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
    data = db.query(TradeLog).order_by(TradeLog.timestamp.desc()).offset(offset).limit(limit).all()
    return [TradeLogResponse(
        id=t.id,
        type=t.type,
        symbol=t.symbol,
        quantity=float(t.quantity),
        price=float(t.price),
        timestamp=t.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    ) for t in data]


# Bot signal route
@app.get("/bot/signals")
def get_bot_signals(db: Session = Depends(get_db)) -> dict:
    """Return current buy/sell signals for each asset."""
    signals = {}
    for asset in config.ASSETS:
        signal = get_signal(db, asset["symbol"])
        signals[asset["symbol"]] = signal
    return signals
