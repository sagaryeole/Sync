"""Paper engine — central orchestrator for paper trading.

One PortfolioAccount per strategy. All mutations funnel through submit_order()
under a single RLock. Manual REST orders and bot orders call the same method —
one code path, no divergence.

The engine_tick (1s job) evaluates:
  1. Working LIMIT orders (fill if market crosses)
  2. STOP orders (trigger if last crosses stop price → convert to MARKET)
  3. SL/TP on open positions (trigger → MARKET sell)
  4. Max-drawdown kill-switch check

The engine never touches the DB directly — it produces Fill objects that
the scheduler persists in one transaction with the portfolio snapshot (H5).
"""
import logging
import math
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from engine.portfolio import PortfolioAccount, Position
from engine.paper_broker import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    RejectReason,
)
from engine.risk import RiskConfig, RiskManager
from engine.market_state import MarketState

logger = logging.getLogger("engine.core")

_EPS = 1e-9
_MAX_CLIENT_ORDER_ID_LEN = 50
_MAX_WORKING_ORDERS = 1000
_MAX_SEEN_ORDER_IDS = 10000


@dataclass
class EngineConfig:
    """Engine-level configuration."""
    starting_cash: float = 100000.0
    max_open_positions: int = 4


class PaperEngine:
    """Central paper trading engine.

    Owns one PortfolioAccount per strategy. All order submission and
    tick evaluation happens under a single RLock for thread safety.

    The engine is the single entry point for:
      - Manual REST orders (from the API)
      - Bot/strategy orders (from the StrategyRunner)
      - Tick evaluation (SL/TP, limit fills, stop triggers)

    All of these go through submit_order() — one code path, no divergence.
    """

    def __init__(
        self,
        market_state: MarketState,
        broker: PaperBroker,
        risk_manager: RiskManager,
        config: EngineConfig = None,
    ):
        self.market = market_state
        self.broker = broker
        self.risk = risk_manager
        self.config = config or EngineConfig()

        # Single lock for all engine state mutations
        self._lock = threading.RLock()

        # strategy_id -> PortfolioAccount
        self._accounts: Dict[int, PortfolioAccount] = {}

        # client_order_id -> Order (working orders only)
        self._working_orders: Dict[str, Order] = {}

        # H14: bounded dedupe set for all seen client_order_ids
        self._seen_order_ids: OrderedDict[str, None] = OrderedDict()

        # List of fills produced since last flush (for DB persistence)
        self._pending_fills: List[Fill] = []

        # strategy_ids halted since last flush (WS: emit "halt" only after the
        # halt + flatten fills are durably persisted, same rule as fills)
        self._pending_halts: List[int] = []

        # List of closed positions (for cooldown tracking)
        self._recent_closes: List[Tuple[int, str, datetime]] = []

    # --- Account management ---

    def register_strategy(self, strategy_id: int, strategy_key: str, starting_cash: float = None) -> None:
        """Register a new strategy with the engine."""
        with self._lock:
            if strategy_id in self._accounts:
                logger.warning("Strategy %d already registered", strategy_id)
                return
            cash = starting_cash if starting_cash is not None else self.config.starting_cash
            self._accounts[strategy_id] = PortfolioAccount(
                strategy_id=strategy_id,
                strategy_key=strategy_key,
                starting_cash=cash,
            )
            logger.info("Registered strategy %d (%s) with $%.2f", strategy_id, strategy_key, cash)

    def get_account(self, strategy_id: int) -> Optional[PortfolioAccount]:
        """Get the portfolio account for a strategy."""
        with self._lock:
            return self._accounts.get(strategy_id)

    def get_all_accounts(self) -> Dict[int, PortfolioAccount]:
        """Get all portfolio accounts (snapshot under lock)."""
        with self._lock:
            return dict(self._accounts)

    # --- Order submission (the single entry point) ---

    def submit_order(
        self,
        strategy_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Optional[float] = None,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        attach_stops: bool = False,
        size_scale: float = 1.0,
    ) -> Tuple[Optional[Fill], Optional[str]]:
        """Submit an order to the engine. This is THE method for placing trades.

        Manual REST orders and bot orders both call this — one code path.

        Returns (Fill, reject_reason). Exactly one is None.
        For LIMIT/STOP orders that go working, returns (None, None) — the order
        is now in _working_orders and will be evaluated on tick.
        """
        with self._lock:
            account = self._accounts.get(strategy_id)
            if account is None:
                return None, "STRATEGY_NOT_FOUND"

            if account.is_halted:
                return None, RejectReason.STRATEGY_HALTED.value

            # Generate client_order_id if not provided
            if client_order_id is None:
                client_order_id = str(uuid.uuid4())
            else:
                if len(client_order_id) > _MAX_CLIENT_ORDER_ID_LEN:
                    return None, RejectReason.CLIENT_ORDER_ID_TOO_LONG.value
                try:
                    uuid.UUID(client_order_id)
                except ValueError:
                    return None, RejectReason.CLIENT_ORDER_ID_INVALID.value

            # H14: bound the dedupe set
            if client_order_id in self._seen_order_ids:
                return None, "DUPLICATE_CLIENT_ORDER_ID"
            self._seen_order_ids[client_order_id] = None
            if len(self._seen_order_ids) > _MAX_SEEN_ORDER_IDS:
                self._seen_order_ids.popitem(last=False)

            # H14: bound working orders
            if len(self._working_orders) >= _MAX_WORKING_ORDERS:
                self._seen_order_ids.popitem(last=False)
                return None, RejectReason.TOO_MANY_WORKING_ORDERS.value

            # Parse side and type
            try:
                side_enum = OrderSide(side)
                type_enum = OrderType(order_type)
            except ValueError:
                return None, "INVALID_ORDER_PARAMS"

            # For MARKET orders, size through risk manager if qty not specified
            if type_enum == OrderType.MARKET and quantity is None:
                marks = self.market.snapshot()
                last = self.market.last(symbol)
                if last is None:
                    return None, RejectReason.NO_MARKET_DATA.value
                quantity, sl_price, tp_price, reason = self.risk.size_order(
                    account, symbol, last, marks, size_scale=size_scale
                )
                if reason is not None:
                    return None, reason
                if attach_stops:
                    stop_price = sl_price
                    limit_price = tp_price  # will be used as TP limit

            if quantity is None or quantity <= 0:
                return None, "INVALID_QUANTITY"

            order = Order(
                client_order_id=client_order_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side_enum,
                order_type=type_enum,
                quantity=quantity,
                limit_price=limit_price,
                stop_price=stop_price,
                created_at=datetime.now(timezone.utc),
            )

            # Execute based on order type
            if type_enum == OrderType.MARKET:
                fill = self.broker.execute_market(order, account)
                if fill is not None:
                    self._pending_fills.append(fill)
                    # Attach SL/TP if requested
                    if attach_stops and side_enum == OrderSide.BUY:
                        pos = account.get_position(symbol)
                        if pos is not None:
                            self.risk.attach_stops(pos, fill.price)
                    return fill, None
                else:
                    return None, order.reject_reason.value if order.reject_reason else "UNKNOWN"

            elif type_enum == OrderType.LIMIT:
                fill = self.broker.check_limit_fill(order, account)
                if fill is not None:
                    self._pending_fills.append(fill)
                    if attach_stops and side_enum == OrderSide.BUY:
                        pos = account.get_position(order.symbol)
                        if pos is not None:
                            self.risk.attach_stops(pos, fill.price)
                    return fill, None
                if order.reject_reason is not None:
                    return None, order.reject_reason.value
                self._working_orders[client_order_id] = order
                return None, None  # working, not rejected

            elif type_enum == OrderType.STOP:
                # Check if already triggered
                if self.broker.check_stop_trigger(order):
                    # Convert to MARKET and execute
                    order.order_type = OrderType.MARKET
                    fill = self.broker.execute_market(order, account)
                    if fill is not None:
                        self._pending_fills.append(fill)
                        return fill, None
                    else:
                        return None, order.reject_reason.value if order.reject_reason else "UNKNOWN"
                # Not triggered — add to working orders
                self._working_orders[client_order_id] = order
                logger.info("STOP order %s working for %s %s %s @ stop %.2f",
                           client_order_id, side_enum.value, quantity, symbol, stop_price or 0)
                return None, None  # working, not rejected

            return None, "UNSUPPORTED_ORDER_TYPE"

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a working order. Returns True if cancelled, False if not found."""
        with self._lock:
            order = self._working_orders.pop(client_order_id, None)
            if order is not None:
                order.status = OrderStatus.CANCELLED
                logger.info("Order %s cancelled", client_order_id)
                return True
            return False

    def get_working_orders(self) -> List[Order]:
        """Get all working orders (snapshot under lock)."""
        with self._lock:
            return list(self._working_orders.values())

    # --- Tick evaluation (the 1s job) ---

    def on_tick_batch(self) -> List[Fill]:
        """Evaluate all working orders and SL/TP on every tick batch (1s job).

        This is called by the scheduler every second. It:
        1. Checks working LIMIT orders for fills
        2. Checks working STOP orders for triggers → convert to MARKET
        3. Checks SL/TP on all open positions
        4. Checks max-drawdown kill-switch

        Returns list of fills produced.
        """
        with self._lock:
            fills = []
            marks = self.market.snapshot()

            # 1. Evaluate working LIMIT orders
            filled_limit_ids = []
            for client_id, order in list(self._working_orders.items()):
                if order.order_type != OrderType.LIMIT:
                    continue
                account = self._accounts.get(order.strategy_id)
                if account is None:
                    continue
                fill = self.broker.check_limit_fill(order, account)
                if fill is not None:
                    fills.append(fill)
                    self._pending_fills.append(fill)
                    filled_limit_ids.append(client_id)
                    if order.side == OrderSide.BUY:
                        pos = account.get_position(order.symbol)
                        if pos is not None and pos.stop_loss_price is None:
                            self.risk.attach_stops(pos, fill.price)
                elif order.reject_reason is not None:
                    filled_limit_ids.append(client_id)

            for cid in filled_limit_ids:
                self._working_orders.pop(cid, None)

            # 2. Evaluate working STOP orders
            triggered_stop_ids = []
            for client_id, order in list(self._working_orders.items()):
                if order.order_type != OrderType.STOP:
                    continue
                if self.broker.check_stop_trigger(order):
                    triggered_stop_ids.append(client_id)

            for cid in triggered_stop_ids:
                order = self._working_orders.pop(cid)
                order.order_type = OrderType.MARKET
                account = self._accounts.get(order.strategy_id)
                if account is None:
                    continue
                fill = self.broker.execute_market(order, account)
                if fill is not None:
                    fills.append(fill)
                    self._pending_fills.append(fill)

            # 3. Evaluate SL/TP on open positions
            sl_tp_fills = self._evaluate_stops(marks)
            fills.extend(sl_tp_fills)

            # 4. Max-drawdown kill-switch
            self._check_all_drawdowns(marks)

            return fills

    def _evaluate_stops(self, marks: Dict[str, float]) -> List[Fill]:
        """Check SL/TP on all open positions across all strategies."""
        fills = []
        for strategy_id, account in self._accounts.items():
            if account.is_halted:
                continue
            for symbol, pos in list(account.positions.items()):
                if not pos.is_open:
                    continue
                if pos.stop_loss_price is None and pos.take_profit_price is None:
                    continue

                last = marks.get(symbol)
                if last is None or last <= 0:
                    continue

                # Check SL
                if pos.stop_loss_price is not None and last <= pos.stop_loss_price + _EPS:
                    fill = self._close_position(account, pos, "STOP_LOSS")
                    if fill is not None:
                        fills.append(fill)
                        self._pending_fills.append(fill)
                        self.risk.start_cooldown(strategy_id, symbol)
                        continue  # position is closed, skip TP check
                    # If close was rejected (e.g. stale price), fall through to TP check

                # Check TP
                if pos.take_profit_price is not None and last >= pos.take_profit_price - _EPS:
                    fill = self._close_position(account, pos, "TAKE_PROFIT")
                    if fill is not None:
                        fills.append(fill)
                        self._pending_fills.append(fill)
                        self.risk.start_cooldown(strategy_id, symbol)

                # Update trailing stop if enabled
                self.risk.update_trailing_stop(pos, last)

        return fills

    def _close_position(self, account: PortfolioAccount, pos: Position, reason: str) -> Optional[Fill]:
        """Close a position at market. Used by SL/TP and kill-switch."""
        order = Order(
            client_order_id=f"{reason}_{uuid.uuid4()}",
            strategy_id=account.strategy_id,
            symbol=pos.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            created_at=datetime.now(timezone.utc),
        )
        fill = self.broker.execute_market(order, account)
        if fill is not None:
            logger.info("Position closed (%s): %s %s qty=%.8f @ %.2f",
                       reason, account.strategy_key, pos.symbol, fill.quantity, fill.price)
            # Clear stops on the position
            pos.stop_loss_price = None
            pos.take_profit_price = None
        return fill

    def _check_all_drawdowns(self, marks: Dict[str, float]) -> None:
        """Check max-drawdown kill-switch for all strategies."""
        for strategy_id, account in self._accounts.items():
            if account.is_halted:
                continue
            # H18: optionally skip the manual portfolio
            if not self.risk.config.halt_manual_portfolio and account.strategy_key == "manual":
                continue
            if self.risk.check_drawdown(account, marks):
                self._halt_strategy(account, marks)

    def _halt_strategy(self, account: PortfolioAccount, marks: Dict[str, float]) -> None:
        """Halt a strategy and flatten all positions.

        Flatten first, then halt — the broker rejects orders from halted strategies.
        If some positions fail to close, they remain open but the strategy is still
        halted; an error is logged for each failure.
        """
        logger.warning("Kill-switch triggered for %s — flattening all positions",
                      account.strategy_key)
        failures = []
        for symbol, pos in list(account.positions.items()):
            if pos.is_open:
                fill = self._close_position(account, pos, "KILL_SWITCH")
                if fill is not None:
                    self._pending_fills.append(fill)
                else:
                    failures.append(symbol)
        # Halt after flattening so the broker doesn't reject the sell orders
        account.halt("MAX_DRAWDOWN")
        self._pending_halts.append(account.strategy_id)
        if failures:
            logger.error("Kill-switch partial failure for %s: failed to close %s",
                        account.strategy_key, failures)

    # --- Fill management (for DB persistence) ---

    def drain_pending_fills(self) -> List[Fill]:
        """Get and clear pending fills for DB persistence.

        Unlike get_pending_fills()/commit_pending_fills(), this clears
        unconditionally at read time — a caller that drains, then fails to
        persist, loses the fills. Kept for existing callers/tests; new code
        that persists to a DB should use the get/commit/restore trio below
        so a failed transaction never drops a fill (see scheduler.py's
        _flush_engine_state, which is exactly the caller this matters for).
        """
        with self._lock:
            fills = list(self._pending_fills)
            self._pending_fills.clear()
            return fills

    def get_pending_fills(self) -> List[Fill]:
        """Snapshot pending fills WITHOUT clearing them.

        Pairs with commit_pending_fills() (remove after a successful DB
        write) and restore_pending_fills() (no-op by construction here,
        since nothing was removed — the fills are simply still pending,
        ready for the next tick's retry). Fills appended concurrently by
        another scheduler job thread between this snapshot and the matching
        commit/restore call are untouched either way, since both operate by
        object identity, not by clearing the whole list.
        """
        with self._lock:
            return list(self._pending_fills)

    def commit_pending_fills(self, fills: List[Fill]) -> None:
        """Remove specific fills from the pending list after successful persistence."""
        with self._lock:
            fill_ids = {id(f) for f in fills}
            self._pending_fills = [f for f in self._pending_fills if id(f) not in fill_ids]

    def restore_pending_fills(self, fills: List[Fill]) -> None:
        """Return fills to the pending list after a failed DB flush."""
        with self._lock:
            existing_ids = {id(f) for f in self._pending_fills}
            for f in fills:
                if id(f) not in existing_ids:
                    self._pending_fills.append(f)

    def get_pending_fill_count(self) -> int:
        """Get count of pending fills (for monitoring)."""
        with self._lock:
            return len(self._pending_fills)

    def drain_pending_halts(self) -> List[int]:
        """Get and clear strategy_ids halted since the last flush (WS: emit
        "halt" only once the halt + flatten fills are durably persisted).
        """
        with self._lock:
            halts = list(self._pending_halts)
            self._pending_halts.clear()
            return halts

    # --- Status / inspection ---

    def get_status(self) -> Dict:
        """Get engine status for monitoring/debugging."""
        with self._lock:
            return {
                "strategies": len(self._accounts),
                "working_orders": len(self._working_orders),
                "pending_fills": len(self._pending_fills),
                "halted": sum(1 for a in self._accounts.values() if a.is_halted),
            }

    def get_all_equity(self) -> Dict[int, float]:
        """Get equity for all strategies."""
        with self._lock:
            marks = self.market.snapshot()
            return {sid: acct.equity(marks) for sid, acct in self._accounts.items()}

    def rebuild_from_fills(
        self,
        fills_by_strategy: Dict[int, List[Fill]],
        marks: Dict[str, float],
        before_ts: Optional[datetime] = None,
    ) -> Dict[int, Dict]:
        """H5/V1: deterministic replay of fills to rebuild account state.

        Args:
            fills_by_strategy: {strategy_id: [Fill, ...]} from DB, oldest-first
            marks: current market prices for unrealized P&L
            before_ts: if provided, only replay fills with ts < before_ts

        Returns:
            {strategy_id: {"cash": float, "positions": {symbol: qty}, "realized_pnl": float, "fees": float}}
        """
        rebuilt = {}
        with self._lock:
            for strategy_id, account in self._accounts.items():
                cash = float(account.starting_cash)
                positions: Dict[str, float] = {}
                avg_prices: Dict[str, float] = {}
                realized_pnl = 0.0
                fees = 0.0

                for f in fills_by_strategy.get(strategy_id, []):
                    if before_ts is not None and f.ts >= before_ts:
                        break
                    fees += float(f.fee)
                    qty = float(f.quantity)
                    price = float(f.price)
                    fee = float(f.fee)
                    if f.side == "BUY":
                        cash -= qty * price + fee
                        old_qty = positions.get(f.symbol, 0.0)
                        old_avg = avg_prices.get(f.symbol, 0.0)
                        new_qty = old_qty + qty
                        if new_qty > _EPS:
                            avg_prices[f.symbol] = (old_qty * old_avg + qty * price + fee) / new_qty
                        positions[f.symbol] = new_qty
                    else:
                        cash += qty * price - fee
                        old_qty = positions.get(f.symbol, 0.0)
                        old_avg = avg_prices.get(f.symbol, 0.0)
                        if old_qty > _EPS:
                            realized_pnl += qty * (price - old_avg) - fee
                        positions[f.symbol] = old_qty - qty

                # Round positions to 0 if tiny
                for sym in list(positions.keys()):
                    if abs(positions[sym]) < 1e-9:
                        del positions[sym]
                        avg_prices.pop(sym, None)

                rebuilt[strategy_id] = {
                    "cash": cash,
                    "positions": positions,
                    "realized_pnl": realized_pnl,
                    "fees": fees,
                }
        return rebuilt

    def resume_strategy(self, strategy_id: int) -> bool:
        """Resume a halted strategy."""
        with self._lock:
            account = self._accounts.get(strategy_id)
            if account is None:
                return False
            if not account.is_halted:
                return True
            account.resume()
            logger.info("Strategy %d resumed", strategy_id)
            return True
