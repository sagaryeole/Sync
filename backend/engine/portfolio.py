"""Portfolio accounting — in-memory authoritative hot state per strategy.

The DB is a durable log; this is the hot state. Fills are append-only and the
single source of truth (H5). Positions and cash are a derived cache rebuilt
by replaying fills on startup.

Accounting identity (enforced by property test):
    equity == starting_cash + realized_pnl + unrealized_pnl   (exactly)

Key rules:
  BUY:  cash -= qty*price + fee; avg_entry capitalises fees
  SELL: realized = qty*(price - avg_entry) - fee; cash += qty*price - fee
  avg_entry unchanged until qty == 0, then reset to 0
"""
import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("engine.portfolio")

# Epsilon for float comparisons
_EPS = 1e-9


def _is_finite(value: float) -> bool:
    """H1/H10: guard against NaN/Inf in all money math."""
    return value is not None and math.isfinite(value)


@dataclass
class Position:
    """A single position in one symbol. Derived from fills — not authoritative."""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    opened_at: Optional[object] = None  # datetime
    updated_at: Optional[object] = None  # datetime

    @property
    def is_open(self) -> bool:
        return abs(self.quantity) > _EPS

    def market_value(self, mark_price: float) -> float:
        """Current market value of the position at the given mark price."""
        if not _is_finite(mark_price) or mark_price <= 0:
            return 0.0
        return self.quantity * mark_price

    def unrealized_pnl(self, mark_price: float) -> float:
        """Unrealized P&L at the given mark price. Returns 0 for no position."""
        if not self.is_open or not _is_finite(mark_price) or mark_price <= 0:
            return 0.0
        return self.quantity * (mark_price - self.avg_entry_price)

    def unrealized_pnl_pct(self, mark_price: float) -> float:
        """Unrealized P&L as a percentage of cost basis. Returns 0 for no position."""
        if not self.is_open or self.avg_entry_price <= _EPS:
            return 0.0
        return (mark_price - self.avg_entry_price) / self.avg_entry_price


@dataclass
class PortfolioAccount:
    """In-memory authoritative hot state for one strategy.

    All money math happens here. The DB stores fills (append-only) and
    snapshots of this state, but fills are the source of truth (H5).
    """
    strategy_id: int
    strategy_key: str
    starting_cash: float = 100000.0
    cash: float = 100000.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    peak_equity: float = 100000.0
    is_halted: bool = False
    halt_reason: Optional[str] = None
    positions: Dict[str, Position] = field(default_factory=dict)

    def __post_init__(self):
        """Set cash and peak_equity to starting_cash on initialization."""
        self.cash = self.starting_cash
        self.peak_equity = self.starting_cash

    # --- H5: rebuild from fills (the source of truth) ---

    def reset(self) -> None:
        """Reset to starting state — used when rebuilding from fills."""
        self.cash = self.starting_cash
        self.realized_pnl = 0.0
        self.fees_paid = 0.0
        self.peak_equity = self.starting_cash
        self.is_halted = False
        self.halt_reason = None
        self.positions.clear()

    def apply_fill(
        self,
        side: str,          # "BUY" or "SELL"
        symbol: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        ts: Optional[object] = None,
    ) -> None:
        """Apply a fill to the portfolio. This is the single mutation point.

        Ported from bot.py:execute_trade lines ~85-92 (weighted-average cost basis),
        with fees capitalised into cost basis on BUY (standard broker convention).

        Raises:
            ValueError: if any input is non-finite (H1/H10) or if a SELL
                        exceeds the position quantity.
        """
        # H1/H10: validate all inputs are finite
        for name, val in [("quantity", quantity), ("price", price), ("fee", fee)]:
            if not _is_finite(val):
                raise ValueError(
                    f"Non-finite {name}={val} in apply_fill for {self.strategy_key}"
                )

        if quantity <= 0:
            raise ValueError(f"Non-positive quantity={quantity} in apply_fill")
        if price <= 0:
            raise ValueError(f"Non-positive price={price} in apply_fill")
        if fee < 0:
            raise ValueError(f"Negative fee={fee} in apply_fill")

        pos = self.positions.get(symbol)
        if pos is None:
            pos = Position(symbol=symbol, opened_at=ts, updated_at=ts)
            self.positions[symbol] = pos

        if side == "BUY":
            cost = quantity * price + fee  # fees capitalised into cost basis
            if self.cash < cost - _EPS:
                raise ValueError(
                    f"Insufficient cash for {self.strategy_key}: "
                    f"need {cost:.2f}, have {self.cash:.2f}"
                )

            # Weighted-average cost basis (ported from bot.py)
            old_qty = pos.quantity
            old_avg = pos.avg_entry_price
            new_qty = old_qty + quantity
            if new_qty > _EPS:
                pos.avg_entry_price = (old_qty * old_avg + quantity * price + fee) / new_qty
            else:
                pos.avg_entry_price = 0.0

            pos.quantity = new_qty
            self.cash -= cost
            self.fees_paid += fee

        elif side == "SELL":
            if pos.quantity <= _EPS:
                raise ValueError(
                    f"Insufficient position for {self.strategy_key} {symbol}: "
                    f"have {pos.quantity:.8f}"
                )

            qty_to_sell = min(pos.quantity, quantity)
            revenue = qty_to_sell * price
            realized = qty_to_sell * (price - pos.avg_entry_price) - fee

            self.cash += revenue - fee
            self.realized_pnl += realized
            self.fees_paid += fee

            remaining = pos.quantity - qty_to_sell
            pos.quantity = remaining
            if remaining <= _EPS:
                # Full exit — reset cost basis
                pos.quantity = 0.0
                pos.avg_entry_price = 0.0

        else:
            raise ValueError(f"Invalid side={side} in apply_fill")

        pos.updated_at = ts

        # H1: assert no NaN/Inf after every fill
        if not _is_finite(self.cash):
            raise ValueError(f"Cash became non-finite after fill: {self.cash}")
        if not _is_finite(self.realized_pnl):
            raise ValueError(f"Realized P&L became non-finite after fill: {self.realized_pnl}")
        if not _is_finite(pos.avg_entry_price):
            raise ValueError(f"Avg entry became non-finite after fill: {pos.avg_entry_price}")

    # --- Derived values ---

    def position_value(self, marks: Dict[str, float]) -> float:
        """Total market value of all open positions at the given mark prices."""
        total = 0.0
        for sym, pos in self.positions.items():
            if pos.is_open:
                mark = marks.get(sym)
                if mark is not None and _is_finite(mark) and mark > 0:
                    total += pos.market_value(mark)
        return total

    def unrealized_pnl(self, marks: Dict[str, float]) -> float:
        """Total unrealized P&L across all positions."""
        total = 0.0
        for sym, pos in self.positions.items():
            if pos.is_open:
                mark = marks.get(sym)
                if mark is not None and _is_finite(mark) and mark > 0:
                    total += pos.unrealized_pnl(mark)
        return total

    def equity(self, marks: Dict[str, float]) -> float:
        """Total equity = cash + position value.

        This is NEVER a stored column — always derived (H7).
        """
        return self.cash + self.position_value(marks)

    def drawdown_pct(self, marks: Dict[str, float]) -> float:
        """Current drawdown from peak equity as a fraction (0.0 = no drawdown).

        H10: guarded against peak_equity == 0.
        """
        if self.peak_equity <= _EPS:
            return 0.0
        current = self.equity(marks)
        if current >= self.peak_equity:
            return 0.0
        return (self.peak_equity - current) / self.peak_equity

    def update_peak(self, marks: Dict[str, float]) -> bool:
        """Update peak equity if current equity is higher. Returns True if updated."""
        current = self.equity(marks)
        if not _is_finite(current):
            return False
        if current > self.peak_equity:
            self.peak_equity = current
            return True
        return False

    def open_position_count(self) -> int:
        """Count of currently open positions."""
        return sum(1 for p in self.positions.values() if p.is_open)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def halt(self, reason: str) -> None:
        """Halt the strategy — no new trades allowed."""
        self.is_halted = True
        self.halt_reason = reason
        logger.warning("Strategy %s HALTED: %s", self.strategy_key, reason)

    def resume(self) -> None:
        """Resume a halted strategy."""
        self.is_halted = False
        self.halt_reason = None
        logger.info("Strategy %s resumed", self.strategy_key)
