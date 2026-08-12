"""Tests for engine/paper_broker.py — MARKET/LIMIT/STOP execution, rejections, fees."""
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from engine.paper_broker import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    Quote,
    RejectReason,
)
from engine.portfolio import PortfolioAccount


_SENTINEL = object()


def make_tick(price, bid=_SENTINEL, ask=_SENTINEL, ts=None, symbol="BTC"):
    """Create a mock tick object. Use _SENTINEL to distinguish None from 'not provided'."""
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.bid = price - 1.0 if bid is _SENTINEL else bid
    tick.ask = price + 1.0 if ask is _SENTINEL else ask
    tick.ts = ts or datetime.now(timezone.utc)
    return tick


def make_market_state(tick=None, ticks=None):
    """Create a mock MarketState with the given tick(s)."""
    ms = MagicMock()
    if ticks:
        ms.last_tick.side_effect = lambda sym: ticks.get(sym)
    else:
        ms.last_tick.return_value = tick
    return ms


def make_account(cash=100000.0):
    return PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=cash)


def make_order(symbol="BTC", side=OrderSide.BUY, qty=1.0, order_type=OrderType.MARKET,
               limit_price=None, stop_price=None):
    return Order(
        client_order_id="test-1",
        strategy_id=1,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        limit_price=limit_price,
        stop_price=stop_price,
        created_at=datetime.now(timezone.utc),
    )


class TestQuote:
    def test_quote_from_tick_with_bid_ask(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        q = broker.get_quote("BTC")
        assert q.mid == pytest.approx(50000.0)
        assert q.bid == 49999
        assert q.ask == 50001
        # min spread = mid * 2bps = 50000 * 0.0002 = 10.0, which is > actual spread of 2
        assert q.spread == pytest.approx(10.0)

    def test_quote_from_tick_without_bid_ask(self):
        tick = make_tick(50000, bid=None, ask=None)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        q = broker.get_quote("BTC")
        # bid/ask default to last
        assert q.bid == 50000
        assert q.ask == 50000
        # spread should be min 2bps = 10.0
        assert q.spread == pytest.approx(10.0)

    def test_quote_no_data(self):
        ms = make_market_state(tick=None)
        broker = PaperBroker(ms)
        q = broker.get_quote("BTC")
        assert q is None

    def test_quote_inverted_bid_ask_fixed(self):
        tick = make_tick(50000, bid=50001, ask=49999)  # inverted
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        q = broker.get_quote("BTC")
        # should swap so bid <= ask
        assert q.bid <= q.ask


class TestMarketOrder:
    def test_market_buy_fills_at_ask_plus_slippage(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, slippage_bps=1.5, impact_notional=50000.0)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0)

        fill = broker.execute_market(order, acct)
        assert fill is not None
        assert fill.side == "BUY"
        assert fill.quantity == 1.0
        # fill_price = mid + spread/2 + slip
        # mid=50000, spread=10 (min 2bps), slip = 50000*(1.5/10000)*(1+min(2, 50000/50000)) = 7.5*2 = 15
        # fill_price = 50000 + 5 + 15 = 50020
        assert fill.price == pytest.approx(50020.0, rel=0.01)
        assert order.status == OrderStatus.FILLED
        assert acct.cash < 100000.0

    def test_market_sell_fills_at_bid_minus_slippage(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, slippage_bps=1.5, impact_notional=50000.0)
        acct = make_account(100000.0)
        # First buy to have a position
        buy_order = make_order(side=OrderSide.BUY, qty=1.0)
        broker.execute_market(buy_order, acct)
        avg_entry = acct.get_position("BTC").avg_entry_price
        # Now sell
        sell_order = make_order(side=OrderSide.SELL, qty=1.0)
        fill = broker.execute_market(sell_order, acct)
        assert fill is not None
        assert fill.side == "SELL"
        # fill_price = mid - spread/2 - slip = 50000 - 5 - 15 = 49980
        assert fill.price == pytest.approx(49980.0, rel=0.01)
        # realized_pnl = qty*(sell_price - avg_entry) - fee
        expected_realized = 1.0 * (fill.price - avg_entry) - fill.fee
        assert fill.realized_pnl == pytest.approx(expected_realized, rel=0.01)

    def test_market_buy_insufficient_cash(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        acct = make_account(100.0)  # not enough
        order = make_order(side=OrderSide.BUY, qty=1.0)
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.status == OrderStatus.REJECTED
        assert order.reject_reason == RejectReason.INSUFFICIENT_CASH

    def test_market_sell_no_position(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.SELL, qty=1.0)
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.status == OrderStatus.REJECTED
        assert order.reject_reason == RejectReason.INSUFFICIENT_POSITION

    def test_market_buy_below_min_notional(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, min_notional=100.0)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=0.0001)  # ~$5 notional
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.status == OrderStatus.REJECTED
        assert order.reject_reason == RejectReason.BELOW_MIN_NOTIONAL

    def test_market_no_data(self):
        ms = make_market_state(tick=None)
        broker = PaperBroker(ms)
        acct = make_account()
        order = make_order()
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.reject_reason == RejectReason.NO_MARKET_DATA

    def test_market_stale_price(self):
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=60)
        tick = make_tick(50000, ts=old_ts)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, stale_price_seconds=30.0)
        acct = make_account()
        order = make_order()
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.reject_reason == RejectReason.STALE_PRICE

    def test_market_strategy_halted(self):
        tick = make_tick(50000)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        acct = make_account()
        acct.halt("MAX_DRAWDOWN")
        order = make_order()
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.reject_reason == RejectReason.STRATEGY_HALTED

    def test_market_symbol_not_tradable(self):
        tick = make_tick(50000, symbol="BTC")
        ms = make_market_state(tick)
        broker = PaperBroker(ms, tradable_symbols={"ETH", "SOL"})
        acct = make_account()
        order = make_order(symbol="BTC")
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.reject_reason == RejectReason.SYMBOL_NOT_TRADABLE

    def test_market_fee_is_taker(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, taker_fee_bps=10.0, slippage_bps=0, impact_notional=1e12)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0)
        fill = broker.execute_market(order, acct)
        assert fill is not None
        # fee = notional * 10/10000 = ~50000 * 0.001 = ~50
        expected_fee = fill.price * 1.0 * (10.0 / 10000.0)
        assert fill.fee == pytest.approx(expected_fee, rel=0.01)

    def test_market_max_positions(self):
        tick = make_tick(50000, symbol="BTC")
        ticks = {"BTC": tick, "ETH": make_tick(3000, symbol="ETH"),
                 "SOL": make_tick(150, symbol="SOL"), "XRP": make_tick(1.0, symbol="XRP"),
                 "ADA": make_tick(0.5, symbol="ADA")}
        ms = make_market_state(ticks=ticks)
        broker = PaperBroker(ms)
        acct = make_account(1000000.0)
        # Open 4 positions (qty sized to exceed min_notional $10 but stay within cash)
        qtys = {"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 100.0}
        for sym in ["BTC", "ETH", "SOL", "XRP"]:
            order = make_order(symbol=sym, qty=qtys[sym])
            fill = broker.execute_market(order, acct)
            assert fill is not None, f"Failed to open position in {sym}: {order.reject_reason}"
        # 5th should be rejected
        order = make_order(symbol="ADA", qty=100.0)
        fill = broker.execute_market(order, acct)
        assert fill is None
        assert order.reject_reason == RejectReason.MAX_POSITIONS


class TestLimitOrder:
    def test_limit_buy_fills_when_ask_below_limit(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, maker_fee_bps=4.0)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0, order_type=OrderType.LIMIT, limit_price=50002.0)
        fill = broker.check_limit_fill(order, acct)
        assert fill is not None
        # fills at min(limit, ask) = min(50002, 50001) = 50001
        assert fill.price == pytest.approx(50001.0)
        assert order.status == OrderStatus.FILLED

    def test_limit_buy_no_fill_when_ask_above_limit(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0, order_type=OrderType.LIMIT, limit_price=50000.0)
        fill = broker.check_limit_fill(order, acct)
        assert fill is None
        assert order.status == OrderStatus.PENDING  # stays pending

    def test_limit_sell_fills_when_bid_above_limit(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, maker_fee_bps=4.0)
        acct = make_account(100000.0)
        # Buy first
        buy = make_order(side=OrderSide.BUY, qty=1.0)
        broker.execute_market(buy, acct)
        # Limit sell at 49998 (bid is 49999, above limit)
        order = make_order(side=OrderSide.SELL, qty=1.0, order_type=OrderType.LIMIT, limit_price=49998.0)
        fill = broker.check_limit_fill(order, acct)
        assert fill is not None
        # fills at max(limit, bid) = max(49998, 49999) = 49999
        assert fill.price == pytest.approx(49999.0)

    def test_limit_fee_is_maker(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, maker_fee_bps=4.0)
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0, order_type=OrderType.LIMIT, limit_price=50002.0)
        fill = broker.check_limit_fill(order, acct)
        assert fill is not None
        expected_fee = fill.price * 1.0 * (4.0 / 10000.0)
        assert fill.fee == pytest.approx(expected_fee, rel=0.01)

    def test_limit_no_slippage(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, slippage_bps=100.0)  # huge slippage
        acct = make_account(100000.0)
        order = make_order(side=OrderSide.BUY, qty=1.0, order_type=OrderType.LIMIT, limit_price=50002.0)
        fill = broker.check_limit_fill(order, acct)
        assert fill is not None
        # Should fill at 50001 (the ask), not affected by slippage
        assert fill.price == pytest.approx(50001.0)


class TestStopOrder:
    def test_stop_sell_triggers_when_last_below_stop(self):
        tick = make_tick(49000, bid=48999, ask=49001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        order = make_order(side=OrderSide.SELL, qty=1.0, order_type=OrderType.STOP, stop_price=49500.0)
        assert broker.check_stop_trigger(order) is True

    def test_stop_sell_no_trigger_when_last_above_stop(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        order = make_order(side=OrderSide.SELL, qty=1.0, order_type=OrderType.STOP, stop_price=49500.0)
        assert broker.check_stop_trigger(order) is False

    def test_stop_buy_triggers_when_last_above_stop(self):
        tick = make_tick(51000, bid=50999, ask=51001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms)
        order = make_order(side=OrderSide.BUY, qty=1.0, order_type=OrderType.STOP, stop_price=50500.0)
        assert broker.check_stop_trigger(order) is True

    def test_stop_no_data(self):
        ms = make_market_state(tick=None)
        broker = PaperBroker(ms)
        order = make_order(side=OrderSide.SELL, qty=1.0, order_type=OrderType.STOP, stop_price=49500.0)
        assert broker.check_stop_trigger(order) is False

    def test_stop_stale_data(self):
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=60)
        tick = make_tick(49000, ts=old_ts)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, stale_price_seconds=30.0)
        order = make_order(side=OrderSide.SELL, qty=1.0, order_type=OrderType.STOP, stop_price=49500.0)
        assert broker.check_stop_trigger(order) is False


class TestSlippageImpact:
    def test_large_order_more_slippage(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick)
        broker = PaperBroker(ms, slippage_bps=1.5, impact_notional=50000.0)
        acct_small = make_account(1000000.0)
        acct_large = make_account(10000000.0)

        # Small order: notional ~50000, impact_factor = 1+1 = 2
        order_small = make_order(side=OrderSide.BUY, qty=1.0)
        fill_small = broker.execute_market(order_small, acct_small)
        assert fill_small is not None

        # Large order: notional ~500000, impact_factor = 1+min(2, 10) = 3
        order_large = make_order(side=OrderSide.BUY, qty=10.0)
        fill_large = broker.execute_market(order_large, acct_large)
        assert fill_large is not None

        # Slippage per unit should be larger for the big order
        slip_small = fill_small.price - 50000 - 1.0  # mid + spread/2
        slip_large = fill_large.price - 50000 - 1.0
        assert slip_large > slip_small


class TestSlippageEdgeCases:
    def test_zero_impact_notional_does_not_crash(self):
        """H10: division by zero guard in _compute_slippage."""
        broker = PaperBroker(
            make_market_state(),
            taker_fee_bps=10.0,
            impact_notional=0.0,
        )
        # Should not raise ZeroDivisionError
        slip = broker._compute_slippage(mid=50000.0, notional=100000.0)
        assert slip >= 0.0
