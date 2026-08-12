"""Market data routers — assets, prices, health."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import config
from database import get_session
from models import Asset, PriceTicker, Candle
from pydantic import BaseModel, Field, field_validator
from feeds.symbols import SYMBOLS

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AssetResponse(BaseModel):
    id: int
    symbol: str
    name: str


class PriceTickerResponse(BaseModel):
    id: int
    symbol: str
    price: float
    timestamp: str


class CandleResponse(BaseModel):
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    source: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/assets", response_model=List[AssetResponse])
def list_assets(db: Session = Depends(get_session)):
    return [AssetResponse(id=a.id, symbol=a.symbol, name=a.name) for a in db.query(Asset)]


@router.get("/assets/{symbol}", response_model=AssetResponse)
def get_asset(symbol: str, db: Session = Depends(get_session)):
    asset = db.query(Asset).filter_by(symbol=symbol).first()
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse(id=asset.id, symbol=asset.symbol, name=asset.name)


@router.get("/prices", response_model=List[PriceTickerResponse])
def list_prices(
    start: Optional[datetime] = None,
    asset: Optional[str] = None,
    db: Session = Depends(get_session),
):
    query = db.query(PriceTicker).order_by(PriceTicker.timestamp.desc())
    if asset:
        query = query.filter(PriceTicker.symbol == asset)
    if start:
        query = query.filter(PriceTicker.timestamp >= start)
    data = list(query.limit(100).all())
    return [
        PriceTickerResponse(
            id=p.id,
            symbol=p.symbol,
            price=float(p.price),
            timestamp=p.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for p in data
    ]


@router.get("/candles", response_model=List[CandleResponse])
def list_candles(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    db: Session = Depends(get_session),
):
    rows = (
        db.query(Candle)
        .filter_by(symbol=symbol, interval=interval)
        .order_by(Candle.open_time.desc())
        .limit(min(limit, 1000))
        .all()
    )
    rows.reverse()
    return [
        CandleResponse(
            symbol=r.symbol,
            interval=r.interval,
            open_time=int(r.open_time.timestamp()),
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=float(r.volume),
            trades=r.trades or 0,
            source=r.source or "",
        )
        for r in rows
    ]
