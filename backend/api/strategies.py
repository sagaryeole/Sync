"""REST v2 routers — engine tables hydration.

These endpoints expose the new engine tables for frontend hydration.
Deltas will eventually stream over WebSocket; these are the initial state.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_session
from models import (
    Strategy as StrategyModel,
    PortfolioAccount as PortfolioAccountModel,
    Position as PositionModel,
    Order as OrderModel,
    Fill as FillModel,
    EquitySnapshot as EquitySnapshotModel,
    Signal as SignalModel,
)
from pydantic import BaseModel
from engine.market_state import MARKET
from settings import get_settings as _get_settings

_settings = _get_settings()

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StrategyResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str
    enabled: bool
    starting_cash: float
    created_at: str


class PortfolioResponse(BaseModel):
    id: int
    strategy_id: int
    cash: float
    realized_pnl: float
    fees_paid: float
    peak_equity: float
    is_halted: bool
    halt_reason: str
    updated_at: str


class PositionResponse(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    opened_at: str
    updated_at: str


class OrderResponse(BaseModel):
    id: int
    client_order_id: str
    strategy_id: int
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    filled_quantity: float
    filled_price: float
    fee: float
    reject_reason: str
    created_at: str
    updated_at: str


class FillResponse(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    realized_pnl: float
    liquidity: str
    ts: str


class EquitySnapshotResponse(BaseModel):
    id: int
    strategy_id: int
    ts: str
    equity: float
    cash: float
    position_value: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown_pct: float


class SignalResponse(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    action: str
    strength: float
    price: float
    indicators_json: str
    ts: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float(val):
    if val is None:
        return 0.0
    return float(val)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/strategies", response_model=List[StrategyResponse])
def list_strategies(db: Session = Depends(get_session)):
    rows = db.query(StrategyModel).order_by(StrategyModel.id).all()
    return [
        StrategyResponse(
            id=r.id,
            key=r.key,
            name=r.name,
            description=r.description or "",
            enabled=r.enabled,
            starting_cash=float(r.starting_cash),
            created_at=_fmt_dt(r.created_at),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: int, db: Session = Depends(get_session)):
    r = db.query(StrategyModel).filter_by(id=strategy_id).first()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyResponse(
        id=r.id,
        key=r.key,
        name=r.name,
        description=r.description or "",
        enabled=r.enabled,
        starting_cash=float(r.starting_cash),
        created_at=_fmt_dt(r.created_at),
    )


@router.get("/strategies/{strategy_id}/portfolio", response_model=List[PortfolioResponse])
def list_portfolios(strategy_id: int, db: Session = Depends(get_session)):
    rows = db.query(PortfolioAccountModel).filter_by(strategy_id=strategy_id).all()
    return [
        PortfolioResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            cash=float(r.cash),
            realized_pnl=float(r.realized_pnl),
            fees_paid=float(r.fees_paid),
            peak_equity=float(r.peak_equity),
            is_halted=r.is_halted,
            halt_reason=r.halt_reason or "",
            updated_at=_fmt_dt(r.updated_at),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}/positions", response_model=List[PositionResponse])
def list_positions(strategy_id: int, db: Session = Depends(get_session)):
    rows = db.query(PositionModel).filter_by(strategy_id=strategy_id).all()
    return [
        PositionResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            quantity=float(r.quantity),
            avg_entry_price=float(r.avg_entry_price),
            realized_pnl=float(r.realized_pnl),
            stop_loss_price=_float(r.stop_loss_price),
            take_profit_price=_float(r.take_profit_price),
            opened_at=_fmt_dt(r.opened_at),
            updated_at=_fmt_dt(r.updated_at),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}/orders", response_model=List[OrderResponse])
def list_orders(
    strategy_id: int,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_session),
):
    query = db.query(OrderModel).filter_by(strategy_id=strategy_id)
    if symbol:
        query = query.filter(OrderModel.symbol == symbol)
    if status:
        query = query.filter(OrderModel.status == status)
    rows = query.order_by(desc(OrderModel.created_at)).limit(limit).all()
    return [
        OrderResponse(
            id=r.id,
            client_order_id=r.client_order_id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            side=r.side,
            order_type=r.order_type,
            status=r.status,
            quantity=float(r.quantity),
            filled_quantity=float(r.filled_quantity),
            filled_price=float(r.avg_fill_price),
            fee=float(r.fee),
            reject_reason=r.reject_reason or "",
            created_at=_fmt_dt(r.created_at),
            updated_at=_fmt_dt(r.updated_at),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}/fills", response_model=List[FillResponse])
def list_fills(
    strategy_id: int,
    symbol: Optional[str] = None,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_session),
):
    query = db.query(FillModel).filter_by(strategy_id=strategy_id)
    if symbol:
        query = query.filter(FillModel.symbol == symbol)
    rows = query.order_by(desc(FillModel.ts)).limit(limit).all()
    return [
        FillResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            side=r.side,
            quantity=float(r.quantity),
            price=float(r.price),
            fee=float(r.fee),
            realized_pnl=float(r.realized_pnl),
            liquidity=r.liquidity,
            ts=_fmt_dt(r.ts),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}/equity", response_model=List[EquitySnapshotResponse])
def list_equity(
    strategy_id: int,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_session),
):
    rows = (
        db.query(EquitySnapshotModel)
        .filter_by(strategy_id=strategy_id)
        .order_by(desc(EquitySnapshotModel.ts))
        .limit(limit)
        .all()
    )
    return [
        EquitySnapshotResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            ts=_fmt_dt(r.ts),
            equity=float(r.equity),
            cash=float(r.cash),
            position_value=float(r.position_value),
            realized_pnl=float(r.realized_pnl),
            unrealized_pnl=float(r.unrealized_pnl),
            drawdown_pct=float(r.drawdown_pct),
        )
        for r in rows
    ]


@router.get("/strategies/{strategy_id}/signals", response_model=List[SignalResponse])
def list_signals(
    strategy_id: int,
    symbol: Optional[str] = None,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_session),
):
    query = db.query(SignalModel).filter_by(strategy_id=strategy_id)
    if symbol:
        query = query.filter(SignalModel.symbol == symbol)
    rows = query.order_by(desc(SignalModel.ts)).limit(limit).all()
    return [
        SignalResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            action=r.action,
            strength=float(r.strength),
            price=float(r.price),
            indicators_json=r.indicators_json or "{}",
            ts=_fmt_dt(r.ts),
        )
        for r in rows
    ]


@router.get("/strategies/key/{key}", response_model=StrategyResponse)
def get_strategy_by_key(key: str, db: Session = Depends(get_session)):
    r = db.query(StrategyModel).filter_by(key=key).first()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyResponse(
        id=r.id,
        key=r.key,
        name=r.name,
        description=r.description or "",
        enabled=r.enabled,
        starting_cash=float(r.starting_cash),
        created_at=_fmt_dt(r.created_at),
    )


@router.get("/strategies/{strategy_id}/metrics")
def get_strategy_metrics(strategy_id: int, db: Session = Depends(get_session)):
    from engine.metrics import (
        win_rate, avg_win, avg_loss, profit_factor,
        max_drawdown_pct, intraday_sharpe, trade_count, avg_hold_time_seconds,
    )
    fills = db.query(FillModel).filter_by(strategy_id=strategy_id).all()
    snapshots = db.query(EquitySnapshotModel).filter_by(strategy_id=strategy_id).all()
    return {
        "win_rate": win_rate(fills),
        "avg_win": avg_win(fills),
        "avg_loss": avg_loss(fills),
        "profit_factor": profit_factor(fills),
        "max_drawdown_pct": max_drawdown_pct(snapshots),
        "intraday_sharpe": intraday_sharpe(snapshots),
        "trade_count": trade_count(fills),
        "avg_hold_time_seconds": avg_hold_time_seconds(fills),
    }


@router.post("/strategies/{strategy_id}/{action}")
def control_strategy(strategy_id: int, action: str):
    account = ENGINE.get_account(strategy_id)
    if account is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not registered")
    if action == "enable":
        account.resume()
    elif action == "disable":
        account.halt("API_DISABLE")
    elif action == "resume":
        account.resume()
    elif action == "reset":
        account.resume()
        account.cash = float(_settings.starting_cash)
        account.realized_pnl = 0.0
        account.fees_paid = 0.0
        account.peak_equity = float(_settings.starting_cash)
        account.is_halted = False
        account.halt_reason = None
        account.positions.clear()
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    return {"status": "ok", "action": action}


@router.post("/orders", status_code=201)
def create_order(
    strategy_id: int,
    symbol: str,
    side: str,
    order_type: str = "MARKET",
    quantity: Optional[float] = None,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    client_order_id: Optional[str] = None,
):
    fill, reason = ENGINE.submit_order(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        client_order_id=client_order_id,
    )
    if fill is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=reason or "ORDER_REJECTED")
    return {"status": "filled", "fill_id": fill.id}


@router.delete("/orders/{client_order_id}")
def cancel_order(client_order_id: str):
    ok = ENGINE.cancel_order(client_order_id)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "cancelled"}


@router.get("/replay")
def replay_portfolio(before: Optional[str] = None, db: Session = Depends(get_session)):
    """V1: deterministic replay of fills up to an optional timestamp.

    Query params:
      before: ISO8601 timestamp (e.g. 2026-01-01T00:00:00Z). If omitted,
              replays all fills.

    Returns:
      {strategy_id: {"cash": float, "positions": {symbol: qty}}}
    """
    fills_by_strategy: Dict[int, List[FillModel]] = {}
    query = db.query(FillModel).order_by(FillModel.ts)
    if before:
        query = query.filter(FillModel.ts < before)
    for f in query.all():
        fills_by_strategy.setdefault(f.strategy_id, []).append(f)
    marks = {sym: MARKET.last(sym) for sym in _settings.symbols if MARKET.last(sym) is not None}
    return ENGINE.rebuild_from_fills(fills_by_strategy, marks, before_ts=before)
