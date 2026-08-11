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

        # List of fills produced since last flush (for DB persistence)
        self._pending_fills: List[Fill] = []

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
            if len(self._working_orders) >= _MAX_WORKING_ORDERS:
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
                    account, symbol, last, marks
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
                # Try immediate fill first
                fill = self.broker.check_limit_fill(order, account)
                if fill is not None:
                    self._pending_fills.append(fill)
                    if attach_stops and side_enum == OrderSide.BUY:
                        pos = account.get_position(symbol)
                        if pos is not None:
                            self.risk.attach_stops(pos, fill.price)
                    return fill, None
                # Not filled — add to working orders
                self._working_orders[client_order_id] = order
                logger.info("LIMIT order %s working for %s %s %s @ %.2f",
                           client_order_id, side_enum.value, quantity, symbol, limit_price or 0)
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
                    # Attach stops if this was a BUY with stops
                    if order.side == OrderSide.BUY:
                        pos = account.get_position(order.symbol)
                        if pos is not None and pos.stop_loss_price is None:
                            self.risk.attach_stops(pos, fill.price)

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
            if self.risk.check_drawdown(account, marks):
                self._halt_strategy(account, marks)

    def _halt_strategy(self, account: PortfolioAccount, marks: Dict[str, float]) -> None:
        """Halt a strategy and flatten all positions.

        Flatten first, then halt — the broker rejects orders from halted strategies.
        """
        logger.warning("Kill-switch triggered for %s — flattening all positions",
                      account.strategy_key)
        for symbol, pos in list(account.positions.items()):
            if pos.is_open:
                fill = self._close_position(account, pos, "KILL_SWITCH")
                if fill is not None:
                    self._pending_fills.append(fill)
        # Halt after flattening so the broker doesn't reject the sell orders
        account.halt("MAX_DRAWDOWN")

    # --- Fill management (for DB persistence) ---

    def drain_pending_fills(self) -> List[Fill]:
        """Get and clear pending fills for DB persistence."""
        with self._lock:
            fills = list(self._pending_fills)
            self._pending_fills.clear()
            return fills

    def get_pending_fill_count(self) -> int:
        """Get count of pending fills (for monitoring)."""
        with self._lock:
            return len(self._pending_fills)

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
