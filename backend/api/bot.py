"""Bot router — strategy signals."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_session
from models import Signal
import config

router = APIRouter()


@router.get("/bot/signals")
def get_bot_signals(db: Session = Depends(get_session)):
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
