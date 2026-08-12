"""Risk manager — position sizing, SL/TP attachment, drawdown kill-switch.

All risk checks happen before an order reaches the broker. The RiskManager
is stateless between calls — it reads from PortfolioAccount and MarketState
and returns a sized order or a rejection.

Key rules:
  - size_order(): risk 2% of equity against stop distance, capped at 20% of equity
  - max_open_positions = 4
  - SL 2% / TP 4% attached on entry
  - COOLDOWN_BARS = 3 per symbol after a close (prevents immediate re-entry)
  - Max-drawdown kill-switch: equity < peak * 0.75 → flatten all + halt
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from engine.portfolio import PortfolioAccount, Position
from engine.market_state import MarketState

logger = logging.getLogger("engine.risk")

_EPS = 1e-9


@dataclass
class RiskConfig:
    """Risk parameters — all overridable via settings."""
    max_open_positions: int = 4
    max_position_pct: float = 0.20       # max 20% of equity in one position
    risk_per_trade_pct: float = 0.02     # risk 2% of equity per trade
    stop_loss_pct: float = 0.02          # SL 2% below entry
    take_profit_pct: float = 0.04        # TP 4% above entry
    max_drawdown_pct: float = 0.25       # halt at 25% drawdown from peak
    cooldown_bars: int = 3               # bars to wait after closing a position
    min_notional: float = 10.0           # minimum order size in USD
    trailing_stop: bool = False          # optional trailing stop
    trailing_stop_pct: float = 0.02      # trail by 2%
    halt_manual_portfolio: bool = False  # H18: kill-switch also halts manual portfolio


@dataclass
class CooldownState:
    """Per-symbol cooldown tracking after a position close."""
    symbol: str
    bars_remaining: int
    closed_at: datetime


class RiskManager:
    """Pre-trade risk checks and position sizing.

    Called by the engine before submitting an order to the broker.
    Returns a sized quantity and SL/TP prices, or a rejection reason.
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        # Per-strategy cooldown state: {strategy_id: {symbol: CooldownState}}
        self._cooldowns: Dict[int, Dict[str, CooldownState]] = {}

    def size_order(
        self,
        account: PortfolioAccount,
        symbol: str,
        entry_price: float,
        marks: Dict[str, float],
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
        """Size an order based on risk rules.

        Returns (quantity, stop_loss_price, take_profit_price, reject_reason).
        If reject_reason is not None, the order should not be placed.
        """
        # H1: validate entry price
        if not math.isfinite(entry_price) or entry_price <= 0:
            return None, None, None, "INVALID_PRICE"

        # Strategy halted
        if account.is_halted:
            return None, None, None, "STRATEGY_HALTED"

        # Compute current equity
        equity = account.equity(marks)
        if equity <= 0:
            return None, None, None, "INSUFFICIENT_EQUITY"

        # Check cooldown
        if self._is_in_cooldown(account.strategy_id, symbol):
            return None, None, None, "COOLDOWN"

        # Check max open positions
        pos = account.get_position(symbol)
        is_new_position = pos is None or not pos.is_open
        if is_new_position and account.open_position_count() >= self.config.max_open_positions:
            return None, None, None, "MAX_POSITIONS"

        # Compute stop distance
        stop_loss_price = entry_price * (1.0 - self.config.stop_loss_pct)
        stop_distance = entry_price - stop_loss_price
        if stop_distance <= _EPS:
            return None, None, None, "INVALID_STOP_DISTANCE"

        # Risk amount = equity * risk_per_trade_pct
        risk_amount = equity * self.config.risk_per_trade_pct

        # Quantity = risk_amount / stop_distance
        quantity = risk_amount / stop_distance

        # Cap at max_position_pct of equity
        max_notional = equity * self.config.max_position_pct
        max_qty = max_notional / entry_price
        if quantity > max_qty:
            quantity = max_qty

        # Floor at min_notional
        min_qty = self.config.min_notional / entry_price
        if quantity < min_qty:
            # If we can't even afford the minimum, check if we have enough cash
            cost = min_qty * entry_price
            if account.cash < cost - _EPS:
                return None, None, None, "INSUFFICIENT_CASH"
            quantity = min_qty

        # Final cash check
        cost = quantity * entry_price
        if account.cash < cost - _EPS:
            # Scale down to what we can afford
            quantity = account.cash / entry_price
            if quantity * entry_price < self.config.min_notional - _EPS:
                return None, None, None, "INSUFFICIENT_CASH"

        # Compute take profit
        take_profit_price = entry_price * (1.0 + self.config.take_profit_pct)

        # H1: validate outputs
        if not math.isfinite(quantity) or quantity <= 0:
            return None, None, None, "INVALID_QUANTITY"

        return quantity, stop_loss_price, take_profit_price, None

    def check_drawdown(
        self,
        account: PortfolioAccount,
        marks: Dict[str, float],
    ) -> bool:
        """Check if max drawdown has been breached.

        Returns True if the kill-switch should trigger (equity < peak * (1 - max_dd_pct)).
        Also updates peak equity.
        """
        account.update_peak(marks)
        dd = account.drawdown_pct(marks)
        if dd >= self.config.max_drawdown_pct:
            logger.warning(
                "Strategy %s hit max drawdown: %.2f%% (peak=%.2f, current=%.2f)",
                account.strategy_key,
                dd * 100,
                account.peak_equity,
                account.equity(marks),
            )
            return True
        return False

    def flatten_all(
        self,
        account: PortfolioAccount,
        market: MarketState,
    ) -> list:
        """Flatten all open positions at market. Returns list of (symbol, qty) to sell.

        The engine calls this when the kill-switch triggers. It returns the
        list of positions to flatten — the engine executes the sells through
        the broker.
        """
        to_flatten = []
        marks = market.snapshot()
        for symbol, pos in list(account.positions.items()):
            if pos.is_open:
                to_flatten.append((symbol, pos.quantity))
        return to_flatten

    def attach_stops(
        self,
        position: Position,
        entry_price: float,
    ) -> None:
        """Attach SL/TP to a position after entry fill."""
        position.stop_loss_price = entry_price * (1.0 - self.config.stop_loss_pct)
        position.take_profit_price = entry_price * (1.0 + self.config.take_profit_pct)

    def update_trailing_stop(
        self,
        position: Position,
        current_price: float,
    ) -> None:
        """Update trailing stop if enabled and price has moved favorably."""
        if not self.config.trailing_stop or not position.is_open:
            return
        new_stop = current_price * (1.0 - self.config.trailing_stop_pct)
        if position.stop_loss_price is None or new_stop > position.stop_loss_price:
            position.stop_loss_price = new_stop

    # --- Cooldown management ---

    def start_cooldown(self, strategy_id: int, symbol: str) -> None:
        """Start cooldown for a symbol after a position close."""
        if strategy_id not in self._cooldowns:
            self._cooldowns[strategy_id] = {}
        self._cooldowns[strategy_id][symbol] = CooldownState(
            symbol=symbol,
            bars_remaining=self.config.cooldown_bars,
            closed_at=datetime.now(timezone.utc),
        )
        logger.info("Cooldown started for strategy %d, %s (%d bars)",
                     strategy_id, symbol, self.config.cooldown_bars)

    def tick_cooldowns(self, strategy_id: int) -> None:
        """Decrement cooldown counters by one bar. Called every strategy tick."""
        cooldowns = self._cooldowns.get(strategy_id)
        if not cooldowns:
            return
        expired = []
        for symbol, cd in cooldowns.items():
            cd.bars_remaining -= 1
            if cd.bars_remaining <= 0:
                expired.append(symbol)
        for sym in expired:
            del cooldowns[sym]
            logger.info("Cooldown expired for strategy %d, %s", strategy_id, sym)

    def _is_in_cooldown(self, strategy_id: int, symbol: str) -> bool:
        """Check if a symbol is in cooldown for a strategy."""
        cooldowns = self._cooldowns.get(strategy_id)
        if not cooldowns:
            return False
        return symbol in cooldowns

    def get_cooldowns(self, strategy_id: int) -> Dict[str, CooldownState]:
        """Get current cooldown state for a strategy (for inspection/debugging)."""
        return self._cooldowns.get(strategy_id, {})
