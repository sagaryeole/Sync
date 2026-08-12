"""Paper broker — simulates order execution against live market data.

No real money, no real exchange. Models:
  - MARKET orders: fill immediately at mid + spread/2 + slippage (taker)
  - LIMIT orders: fill when market crosses the limit price (maker, no slippage)
  - STOP orders: trigger on last price, convert to MARKET (models stop slippage)

Fees: taker 10 bps / maker 4 bps, always in USD.

Cuts (stated in docs, not implemented):
  - Partial fills (top-of-book can't model queue position)
  - Shorting/margin (long-only)

All price discovery goes through MarketState (the in-memory hot state).
The broker never touches the DB — it produces Fill objects that the engine
persists in one transaction with the portfolio mutation (H5).
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

from engine.portfolio import PortfolioAccount
from engine.market_state import MarketState

logger = logging.getLogger("engine.paper_broker")

# Epsilon for float comparisons
_EPS = 1e-9


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class RejectReason(str, Enum):
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    BELOW_MIN_NOTIONAL = "BELOW_MIN_NOTIONAL"
    MAX_POSITIONS = "MAX_POSITIONS"
    STRATEGY_HALTED = "STRATEGY_HALTED"
    NO_MARKET_DATA = "NO_MARKET_DATA"
    STALE_PRICE = "STALE_PRICE"
    SYMBOL_NOT_TRADABLE = "SYMBOL_NOT_TRADABLE"
    CLIENT_ORDER_ID_TOO_LONG = "CLIENT_ORDER_ID_TOO_LONG"
    CLIENT_ORDER_ID_INVALID = "CLIENT_ORDER_ID_INVALID"
    TOO_MANY_WORKING_ORDERS = "TOO_MANY_WORKING_ORDERS"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class Order:
    """An order submitted to the broker."""
    client_order_id: str
    strategy_id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: Optional[float] = None   # for LIMIT orders
    stop_price: Optional[float] = None     # for STOP orders
    time_in_force: str = "GTC"             # GTC, IOC, FOK
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    reject_reason: Optional[RejectReason] = None
    created_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None


@dataclass
class Fill:
    """A fill produced by the broker. This is the append-only source of truth (H5)."""
    client_order_id: str
    strategy_id: int
    symbol: str
    side: str           # "BUY" or "SELL"
    quantity: float
    price: float
    fee: float
    order_type: str     # "MARKET", "LIMIT", "STOP"
    ts: datetime
    reject_reason: Optional[str] = None
    realized_pnl: float = 0.0  # 0.0 for BUY; qty*(price-avg_entry_before)-fee for SELL


@dataclass
class Quote:
    """Current market quote for a symbol, derived from MarketState."""
    mid: float
    bid: float
    ask: float
    last: float
    spread: float
    ts: datetime
    age_seconds: float


class PaperBroker:
    """Simulates order execution against live market data.

    The broker is stateless between calls — it reads from MarketState and
    produces Fill objects. The engine owns order lifecycle and persistence.
    """

    def __init__(
        self,
        market_state: MarketState,
        taker_fee_bps: float = 10.0,
        maker_fee_bps: float = 4.0,
        slippage_bps: float = 1.5,
        impact_notional: float = 50000.0,
        min_notional: float = 10.0,
        stale_price_seconds: float = 30.0,
        tradable_symbols: Optional[set] = None,
    ):
        self.market = market_state
        self.taker_fee_bps = taker_fee_bps
        self.maker_fee_bps = maker_fee_bps
        self.slippage_bps = slippage_bps
        self.impact_notional = impact_notional
        self.min_notional = min_notional
        self.stale_price_seconds = stale_price_seconds
        self.tradable_symbols = tradable_symbols  # None = all symbols tradable

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Build a quote from the latest tick in MarketState.

        Returns None if no data exists for the symbol.
        """
        tick = self.market.last_tick(symbol)
        if tick is None:
            return None

        last = tick.price
        bid = tick.bid if tick.bid is not None and tick.bid > 0 else last
        ask = tick.ask if tick.ask is not None and tick.ask > 0 else last

        # If bid/ask are missing or invalid, synthesize from last
        if bid <= 0 or ask <= 0:
            bid = last
            ask = last

        # Ensure bid <= ask (fix any inverted quotes)
        if bid > ask:
            bid, ask = ask, bid

        mid = (bid + ask) / 2.0
        # Minimum spread of 2 bps to avoid zero-spread when bid==ask==last
        min_spread = mid * 0.0002  # 2 bps
        spread = max(ask - bid, min_spread)

        now = datetime.now(timezone.utc)
        age = (now - tick.ts).total_seconds()

        return Quote(
            mid=mid,
            bid=bid,
            ask=ask,
            last=last,
            spread=spread,
            ts=tick.ts,
            age_seconds=age,
        )

    def _is_tradable(self, symbol: str) -> bool:
        """Check if a symbol is tradable."""
        if self.tradable_symbols is not None:
            return symbol in self.tradable_symbols
        return True

    def _compute_slippage(self, mid: float, notional: float) -> float:
        """Compute slippage as a price delta.

        slip = mid * (slippage_bps / 1e4) * (1 + min(2.0, notional / impact_notional))

        Larger orders get more slippage (market impact), capped at 3x base.
        """
        base_slip = mid * (self.slippage_bps / 10000.0)
        if self.impact_notional > _EPS:
            impact_factor = 1.0 + min(2.0, notional / self.impact_notional)
        else:
            impact_factor = 1.0
        return base_slip * impact_factor

    def _compute_fee(self, notional: float, is_maker: bool) -> float:
        """Compute fee in USD."""
        bps = self.maker_fee_bps if is_maker else self.taker_fee_bps
        return notional * (bps / 10000.0)

    def execute_market(
        self,
        order: Order,
        account: PortfolioAccount,
    ) -> Optional[Fill]:
        """Execute a MARKET order immediately at the current quote.

        Returns a Fill on success, or None on rejection (order.reject_reason set).
        """
        # Pre-checks
        reject = self._pre_check(order, account)
        if reject is not None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = reject
            return None

        quote = self.get_quote(order.symbol)
        if quote is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.NO_MARKET_DATA
            return None

        if quote.age_seconds > self.stale_price_seconds:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.STALE_PRICE
            return None

        # MARKET execution: taker pricing
        slip = self._compute_slippage(quote.mid, order.quantity * quote.mid)
        if order.side == OrderSide.BUY:
            fill_price = quote.mid + quote.spread / 2.0 + slip
        else:
            fill_price = quote.mid - quote.spread / 2.0 - slip

        # H1: validate fill price
        if not math.isfinite(fill_price) or fill_price <= 0:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.NO_MARKET_DATA
            logger.error("Invalid fill price %s for %s", fill_price, order.symbol)
            return None

        notional = order.quantity * fill_price
        fee = self._compute_fee(notional, is_maker=False)

        # Min notional check
        if notional < self.min_notional - _EPS:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.BELOW_MIN_NOTIONAL
            return None

        # Cash/position check (before applying)
        if order.side == OrderSide.BUY:
            cost = notional + fee
            if account.cash < cost - _EPS:
                order.status = OrderStatus.REJECTED
                order.reject_reason = RejectReason.INSUFFICIENT_CASH
                return None
        else:
            pos = account.get_position(order.symbol)
            if pos is None or pos.quantity < order.quantity - _EPS:
                order.status = OrderStatus.REJECTED
                order.reject_reason = RejectReason.INSUFFICIENT_POSITION
                return None

        # Capture the pre-fill avg entry price for SELL realized P&L — apply_fill
        # mutates (and on full exit, resets) it.
        realized_pnl = 0.0
        if order.side == OrderSide.SELL:
            pos_before = account.get_position(order.symbol)
            if pos_before is not None:
                qty_to_sell = min(pos_before.quantity, order.quantity)
                realized_pnl = qty_to_sell * (fill_price - pos_before.avg_entry_price) - fee

        # Apply the fill
        now = datetime.now(timezone.utc)
        try:
            account.apply_fill(
                side=order.side.value,
                symbol=order.symbol,
                quantity=order.quantity,
                price=fill_price,
                fee=fee,
                ts=now,
            )
        except ValueError as e:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.INSUFFICIENT_CASH  # could be position too
            logger.warning("Fill rejected by portfolio: %s", e)
            return None

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.fee = fee
        order.filled_at = now

        return Fill(
            client_order_id=order.client_order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            order_type=order.order_type.value,
            ts=now,
            realized_pnl=realized_pnl,
        )

    def check_limit_fill(
        self,
        order: Order,
        account: PortfolioAccount,
    ) -> Optional[Fill]:
        """Check if a LIMIT order should fill against the current quote.

        LIMIT BUY fills when ask <= limit_price, at min(limit_price, ask) — MAKER.
        LIMIT SELL fills when bid >= limit_price, at max(limit_price, bid) — MAKER.
        No slippage on limit orders (you're the maker).

        Returns a Fill if the order fills, None otherwise (order stays PENDING).
        """
        quote = self.get_quote(order.symbol)
        if quote is None:
            return None

        if quote.age_seconds > self.stale_price_seconds:
            return None  # don't fill on stale data, but don't reject either

        if order.limit_price is None or order.limit_price <= 0:
            return None

        fill_price = None
        if order.side == OrderSide.BUY:
            if quote.ask <= order.limit_price + _EPS:
                fill_price = min(order.limit_price, quote.ask)
        else:
            if quote.bid >= order.limit_price - _EPS:
                fill_price = max(order.limit_price, quote.bid)

        if fill_price is None:
            return None  # not crossed yet

        # Min notional check
        notional = order.quantity * fill_price
        if notional < self.min_notional - _EPS:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.BELOW_MIN_NOTIONAL
            return None

        fee = self._compute_fee(notional, is_maker=True)

        # Cash/position check
        if order.side == OrderSide.BUY:
            cost = notional + fee
            if account.cash < cost - _EPS:
                order.status = OrderStatus.REJECTED
                order.reject_reason = RejectReason.INSUFFICIENT_CASH
                return None
        else:
            pos = account.get_position(order.symbol)
            if pos is None or pos.quantity < order.quantity - _EPS:
                order.status = OrderStatus.REJECTED
                order.reject_reason = RejectReason.INSUFFICIENT_POSITION
                return None

        realized_pnl = 0.0
        if order.side == OrderSide.SELL:
            pos_before = account.get_position(order.symbol)
            if pos_before is not None:
                qty_to_sell = min(pos_before.quantity, order.quantity)
                realized_pnl = qty_to_sell * (fill_price - pos_before.avg_entry_price) - fee

        now = datetime.now(timezone.utc)
        try:
            account.apply_fill(
                side=order.side.value,
                symbol=order.symbol,
                quantity=order.quantity,
                price=fill_price,
                fee=fee,
                ts=now,
            )
        except ValueError as e:
            order.status = OrderStatus.REJECTED
            order.reject_reason = RejectReason.INSUFFICIENT_CASH
            logger.warning("Limit fill rejected by portfolio: %s", e)
            return None

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.fee = fee
        order.filled_at = now

        return Fill(
            client_order_id=order.client_order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            order_type=order.order_type.value,
            ts=now,
            realized_pnl=realized_pnl,
        )

    def check_stop_trigger(
        self,
        order: Order,
    ) -> bool:
        """Check if a STOP order should trigger.

        STOP BUY triggers when last >= stop_price (buy on breakout).
        STOP SELL triggers when last <= stop_price (sell on breakdown / SL).

        Returns True if triggered (convert to MARKET), False otherwise.
        """
        quote = self.get_quote(order.symbol)
        if quote is None:
            return False

        if quote.age_seconds > self.stale_price_seconds:
            return False

        if order.stop_price is None or order.stop_price <= 0:
            return False

        if order.side == OrderSide.BUY:
            return quote.last >= order.stop_price - _EPS
        else:
            return quote.last <= order.stop_price + _EPS

    def _pre_check(self, order: Order, account: PortfolioAccount) -> Optional[RejectReason]:
        """Common pre-execution checks. Returns a RejectReason or None if OK."""
        # Strategy halted
        if account.is_halted:
            return RejectReason.STRATEGY_HALTED

        # Symbol tradable
        if not self._is_tradable(order.symbol):
            return RejectReason.SYMBOL_NOT_TRADABLE

        # Max open positions (BUY only — SELL reduces positions)
        if order.side == OrderSide.BUY:
            pos = account.get_position(order.symbol)
            if pos is None or not pos.is_open:
                if account.open_position_count() >= 4:  # max_open_positions
                    return RejectReason.MAX_POSITIONS

        return None
