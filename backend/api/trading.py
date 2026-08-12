"""Trading routers — portfolio, trade, trade log."""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_session
from models import Portfolio, TradeLog, Asset, PriceTicker
from pydantic import BaseModel, Field, field_validator
from feeds.symbols import SYMBOLS

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortfolioItem(BaseModel):
    symbol: str = Field(..., pattern=r"^([A-Z0-9]{2,10}|USD)$")
    balance: float = Field(default=0)
    quantity: float = Field(default=0)
    cost_basis: float = Field(default=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if v != "USD" and v not in SYMBOLS:
            raise ValueError(
                f"Invalid symbol {v!r}. Valid symbols: {', '.join(sorted(SYMBOLS.keys()))}"
            )
        return v


class ExecuteTradeRequest(BaseModel):
    type: str = Field(..., pattern="^(BUY|SELL)$")
    symbol: str = Field(..., pattern=r"^[A-Z0-9]{2,10}$")
    quantity: float = Field(..., ge=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if v not in SYMBOLS:
            raise ValueError(
                f"Invalid symbol {v!r}. Valid symbols: {', '.join(sorted(SYMBOLS.keys()))}"
            )
        return v


class ExecuteTradeResponse(BaseModel):
    status: str
    type: str
    symbol: str
    quantity: float
    price: float


class TradeLogResponse(BaseModel):
    id: int
    type: str
    symbol: str
    quantity: float
    price: float
    timestamp: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legacy_execute_trade(db: Session, trade_type: str, symbol: str, quantity: float, price: float) -> bool:
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

    else:
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/portfolio", response_model=List[PortfolioItem])
def list_portfolio(db: Session = Depends(get_session)):
    positions = db.query(Portfolio).all()
    return [
        PortfolioItem(
            symbol=p.symbol,
            balance=float(p.balance),
            quantity=float(p.quantity),
            cost_basis=float(p.cost_basis),
        )
        for p in positions
    ]


@router.get("/portfolio/{symbol}", response_model=PortfolioItem)
def get_portfolio(symbol: str, db: Session = Depends(get_session)):
    p = db.query(Portfolio).filter_by(symbol=symbol).first()
    if not p:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Portfolio entry not found")
    return PortfolioItem(
        symbol=p.symbol,
        balance=float(p.balance),
        quantity=float(p.quantity),
        cost_basis=float(p.cost_basis),
    )


@router.post("/trade", response_model=ExecuteTradeResponse, status_code=201)
def execute_trade_endpoint(request: ExecuteTradeRequest, db: Session = Depends(get_session)):
    if request.type not in ("BUY", "SELL"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid trade type")
    if request.quantity < 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Quantity must be non-negative")
    asset = db.query(Asset).filter_by(symbol=request.symbol).first()
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    latest_price = db.query(PriceTicker).filter_by(symbol=request.symbol).order_by(
        PriceTicker.timestamp.desc()
    ).first()
    if not latest_price:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No price data for asset")
    price = float(latest_price.price)

    quantity = float(request.quantity)
    if request.type == "SELL" and quantity == 0:
        portfolio = db.query(Portfolio).filter_by(symbol=request.symbol).first()
        if not portfolio or float(portfolio.quantity) <= 0:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Not enough balance to sell")
        quantity = float(portfolio.quantity)

    success = _legacy_execute_trade(db, request.type, request.symbol, quantity, price)
    if not success:
        from fastapi import HTTPException
        if request.type == "BUY":
            raise HTTPException(status_code=400, detail="Insufficient USD balance")
        else:
            raise HTTPException(status_code=400, detail="Not enough holdings to sell")

    return {
        "status": "trade executed",
        "type": request.type,
        "symbol": request.symbol,
        "quantity": quantity,
        "price": price,
    }


MAX_LIST_LIMIT = 1000

@router.get("/trades", response_model=List[TradeLogResponse])
def list_trades(limit: int = 50, offset: int = 0, db: Session = Depends(get_session)):
    data = db.query(TradeLog).order_by(TradeLog.timestamp.desc()).offset(offset).limit(min(limit, MAX_LIST_LIMIT)).all()
    return [
        TradeLogResponse(
            id=t.id,
            type=t.type,
            symbol=t.symbol,
            quantity=float(t.quantity),
            price=float(t.price),
            timestamp=t.timestamp.replace(tzinfo=timezone.utc),
        )
        for t in data
    ]
