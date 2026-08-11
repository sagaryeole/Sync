"""Trading strategy protocol and shared types.

No external dependencies — pure dataclasses / protocols so that strategies
can be unit-tested in isolation from the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Action vocabulary
# ---------------------------------------------------------------------------

class Action:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

@dataclass
class Candle:
    """1-minute OHLCV bar."""
    symbol: str
    open_time: int          # unix ts seconds (bucket floor)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trades: int = 0


@dataclass
class Position:
    """Current position state for a symbol."""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class StrategyContext:
    """Snapshot of everything a strategy needs to evaluate a symbol.

    Passed to ``Strategy.evaluate()``.  All prices are floats.
    """
    symbol: str
    candles: List[Candle] = field(default_factory=list)
    last_price: float = 0.0
    position: Optional[Position] = None
    cash: float = 0.0
    equity: float = 0.0
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """Strategy output for one evaluation cycle."""
    action: str = Action.HOLD
    strength: float = 0.0       # 0.0 – 1.0 confidence
    reason: str = ""
    indicators: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Strategy(Protocol):
    """Minimal interface every strategy must implement."""

    key: str
    name: str
    default_params: Dict[str, Any]
    warmup_bars: int

    def evaluate(self, ctx: StrategyContext) -> Decision:
        ...


# ---------------------------------------------------------------------------
# Indicator helper
# ---------------------------------------------------------------------------

class IndicatorBundle:
    """Convenience wrapper that pre-computes common indicators from context
    candles so individual strategies don't have to repeat the same calls.

    Usage::

        inds = IndicatorBundle(ctx.candles, **ctx.params)
        sma_val = inds.sma(20)
    """

    def __init__(self, candles: list, **kwargs):
        self.closes = [c.close for c in candles]
        self.highs = [c.high for c in candles]
        self.lows = [c.low for c in candles]
        self.params = kwargs

    def sma(self, window: int):
        from strategies.indicators import sma
        return sma(self.closes, window)

    def ema(self, span: int):
        from strategies.indicators import ema
        return ema(self.closes, span)

    def rsi(self, period: int = 14):
        from strategies.indicators import rsi
        return rsi(self.closes, period)

    def atr(self, period: int = 14):
        from strategies.indicators import atr
        return atr(self.highs, self.lows, self.closes, period)

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9):
        from strategies.indicators import macd
        return macd(self.closes, fast, slow, signal)

    def bbands(self, window: int = 20, num_std: float = 2.0):
        from strategies.indicators import bbands
        return bbands(self.closes, window, num_std)

    def donchian(self, window: int = 20):
        from strategies.indicators import donchian
        return donchian(self.highs, self.lows, window)
