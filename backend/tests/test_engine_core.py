"""Tests for engine/core.py — PaperEngine orchestration, order lifecycle, SL/TP, kill-switch."""
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from engine.core import PaperEngine, EngineConfig
from engine.paper_broker import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    RejectReason,
)
from engine.portfolio import PortfolioAccount
from engine.risk import RiskConfig, RiskManager


def make_tick(price, bid=None, ask=None, ts=None, symbol="BTC"):
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.bid = bid if bid is not None else price - 1.0
    tick.ask = ask if ask is not None else price + 1.0
    tick.ts = ts or datetime.now(timezone.utc)
    return tick


def make_market_state(tick=None, ticks=None, prices=None, last_price=None):
    ms = MagicMock()
    if ticks:
        ms.last_tick.side_effect = lambda sym: ticks.get(sym)
    else:
        ms.last_tick.return_value = tick
    if prices:
        ms.snapshot.return_value = prices
    else:
        ms.snapshot.return_value = {}
    if last_price is not None:
        ms.last.return_value = last_price
    elif tick is not None:
        ms.last.return_value = tick.price
    else:
        ms.last.return_value = None
    return ms


def make_engine(cash=100000.0, tick_price=50000.0, risk_config=None):
    tick = make_tick(tick_price)
    ms = make_market_state(tick=tick, prices={"BTC": tick_price}, last_price=tick_price)
    broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
    rm = RiskManager(risk_config or RiskConfig(max_position_pct=0.95))
    engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=cash))
    engine.register_strategy(1, "test", cash)
    return engine


class TestRegisterStrategy:
    def test_register_creates_account(self):
        engine = make_engine()
        assert engine.get_account(1) is not None
        assert engine.get_account(1).strategy_key == "test"

    def test_register_duplicate_ignored(self):
        engine = make_engine()
        engine.register_strategy(1, "test2", 50000.0)
        # Should not overwrite
        assert engine.get_account(1).strategy_key == "test"

    def test_get_nonexistent_returns_none(self):
        engine = make_engine()
        assert engine.get_account(999) is None


class TestSubmitMarketOrder:
    def test_market_buy_fills(self):
        engine = make_engine(tick_price=50000.0)
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is not None
        assert reason is None
        assert fill.side == "BUY"
        assert engine.get_account(1).cash < 100000.0

    def test_market_sell_fills(self):
        engine = make_engine(tick_price=50000.0)
        # Buy first
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        # Sell
        fill, reason = engine.submit_order(1, "BTC", "SELL", "MARKET", quantity=1.0)
        assert fill is not None
        assert reason is None
        assert fill.side == "SELL"

    def test_market_buy_with_auto_sizing(self):
        """When quantity is None, risk manager sizes the order."""
        engine = make_engine(tick_price=50000.0)
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET")  # no quantity
        assert fill is not None
        assert reason is None
        assert fill.quantity > 0

    def test_market_buy_with_stops_attached(self):
        engine = make_engine(tick_price=50000.0)
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "MARKET", quantity=1.0, attach_stops=True
        )
        assert fill is not None
        pos = engine.get_account(1).get_position("BTC")
        assert pos.stop_loss_price is not None
        assert pos.take_profit_price is not None

    def test_strategy_not_found(self):
        engine = make_engine()
        fill, reason = engine.submit_order(999, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is None
        assert reason == "STRATEGY_NOT_FOUND"

    def test_strategy_halted_rejects(self):
        engine = make_engine()
        engine.get_account(1).halt("MAX_DRAWDOWN")
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is None
        assert reason == RejectReason.STRATEGY_HALTED.value

    def test_invalid_quantity_rejects(self):
        engine = make_engine()
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=-1.0)
        assert fill is None
        assert reason == "INVALID_QUANTITY"

    def test_invalid_side_rejects(self):
        engine = make_engine()
        fill, reason = engine.submit_order(1, "BTC", "HOLD", "MARKET", quantity=1.0)
        assert fill is None
        assert reason == "INVALID_ORDER_PARAMS"


class TestSubmitLimitOrder:
    def test_limit_buy_goes_working_if_not_crossed(self):
        engine = make_engine(tick_price=50000.0)
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=49000.0
        )
        # Not crossed — should be working, not filled, not rejected
        assert fill is None
        assert reason is None
        assert len(engine.get_working_orders()) == 1

    def test_limit_buy_fills_immediately_if_crossed(self):
        engine = make_engine(tick_price=50000.0)
        # ask is 50001, limit at 50002 should fill immediately
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=50002.0
        )
        assert fill is not None
        assert reason is None
        assert len(engine.get_working_orders()) == 0


class TestSubmitStopOrder:
    def test_stop_sell_goes_working_if_not_triggered(self):
        engine = make_engine(tick_price=50000.0)
        fill, reason = engine.submit_order(
            1, "BTC", "SELL", "STOP", quantity=1.0, stop_price=49000.0
        )
        # last is 50000, stop at 49000 — not triggered for SELL (needs last <= stop)
        assert fill is None
        assert reason is None
        assert len(engine.get_working_orders()) == 1

    def test_stop_sell_triggers_immediately(self):
        engine = make_engine(tick_price=49000.0)
        # Buy first to have a position
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        # Stop sell at 49500 — last is 49000, which is <= 49500 → triggers
        fill, reason = engine.submit_order(
            1, "BTC", "SELL", "STOP", quantity=1.0, stop_price=49500.0
        )
        assert fill is not None
        assert reason is None


class TestCancelOrder:
    def test_cancel_working_order(self):
        engine = make_engine(tick_price=50000.0)
        engine.submit_order(1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=49000.0)
        assert len(engine.get_working_orders()) == 1
        order_id = engine.get_working_orders()[0].client_order_id
        assert engine.cancel_order(order_id) is True
        assert len(engine.get_working_orders()) == 0

    def test_cancel_nonexistent_returns_false(self):
        engine = make_engine()
        assert engine.cancel_order("nonexistent") is False


class TestOnTickBatch:
    def test_limit_fills_on_tick(self):
        """A working limit order should fill when the market crosses it."""
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick=tick, prices={"BTC": 50000.0})
        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_position_pct=1.0))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        # Place a limit buy at 50002 (should fill immediately since ask=50001)
        # Actually let's place at 49000 (not crossed) then move the market
        engine.submit_order(1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=49000.0)
        assert len(engine.get_working_orders()) == 1

        # Move market down so ask <= 49000
        new_tick = make_tick(48900, bid=48899, ask=48901)
        ms.last_tick.return_value = new_tick
        ms.snapshot.return_value = {"BTC": 48900.0}

        fills = engine.on_tick_batch()
        assert len(fills) == 1
        assert fills[0].side == "BUY"
        assert len(engine.get_working_orders()) == 0

    def test_stop_triggers_on_tick(self):
        """A working stop order should trigger when last crosses the stop price."""
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick=tick, prices={"BTC": 50000.0})
        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_position_pct=1.0))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        # Buy a position first
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)

        # Place a stop sell at 49000 (not triggered yet, last=50000)
        engine.submit_order(1, "BTC", "SELL", "STOP", quantity=1.0, stop_price=49000.0)
        assert len(engine.get_working_orders()) == 1

        # Move market down to 48900 — stop should trigger
        new_tick = make_tick(48900, bid=48899, ask=48901)
        ms.last_tick.return_value = new_tick
        ms.snapshot.return_value = {"BTC": 48900.0}

        fills = engine.on_tick_batch()
        # Should have at least the stop fill
        stop_fills = [f for f in fills if f.side == "SELL"]
        assert len(stop_fills) >= 1
        assert len(engine.get_working_orders()) == 0

    def test_sl_triggers_on_tick(self):
        """SL on an open position should trigger when price drops."""
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick=tick, prices={"BTC": 50000.0})
        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_position_pct=1.0, stop_loss_pct=0.02))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        # Buy with SL attached (SL = 50000 * 0.98 = 49000)
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, attach_stops=True)
        pos = engine.get_account(1).get_position("BTC")
        assert pos.stop_loss_price is not None

        # Move price down to 48900 — below SL
        new_tick = make_tick(48900, bid=48899, ask=48901)
        ms.last_tick.return_value = new_tick
        ms.snapshot.return_value = {"BTC": 48900.0}

        fills = engine.on_tick_batch()
        sell_fills = [f for f in fills if f.side == "SELL"]
        assert len(sell_fills) == 1
        # Position should be closed
        assert not engine.get_account(1).get_position("BTC").is_open

    def test_tp_triggers_on_tick(self):
        """TP on an open position should trigger when price rises."""
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick=tick, prices={"BTC": 50000.0})
        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_position_pct=1.0, take_profit_pct=0.04))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        # Buy with TP attached (TP = fill_price * 1.04)
        fill, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, attach_stops=True)
        pos = engine.get_account(1).get_position("BTC")
        expected_tp = fill.price * 1.04
        assert pos.take_profit_price == pytest.approx(expected_tp)

        # Move price above TP
        new_tick = make_tick(expected_tp + 100, bid=expected_tp + 99, ask=expected_tp + 101)
        ms.last_tick.return_value = new_tick
        ms.snapshot.return_value = {"BTC": expected_tp + 100}

        fills = engine.on_tick_batch()
        sell_fills = [f for f in fills if f.side == "SELL"]
        assert len(sell_fills) == 1
        assert not engine.get_account(1).get_position("BTC").is_open

    def test_no_fills_when_nothing_to_do(self):
        engine = make_engine(tick_price=50000.0)
        fills = engine.on_tick_batch()
        assert len(fills) == 0


class TestKillSwitch:
    def test_drawdown_triggers_halt_and_flatten(self):
        tick = make_tick(50000, bid=49999, ask=50001)
        ms = make_market_state(tick=tick, prices={"BTC": 50000.0})
        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_drawdown_pct=0.10, max_position_pct=1.0))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        # Buy a position
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        account = engine.get_account(1)
        account.peak_equity = 100000.0  # set peak

        # Crash the price to trigger >10% drawdown
        # equity = cash + position_value
        # cash ~ 50000, position = 1 * 40000 = 40000, equity ~ 90000
        # drawdown = (100000 - 90000) / 100000 = 10% → triggers
        new_tick = make_tick(40000, bid=39999, ask=40001)
        ms.last_tick.return_value = new_tick
        ms.snapshot.return_value = {"BTC": 40000.0}

        engine.on_tick_batch()

        assert account.is_halted
        assert account.halt_reason == "MAX_DRAWDOWN"
        # Position should be flattened
        assert not account.get_position("BTC").is_open

    def test_resume_strategy(self):
        engine = make_engine()
        engine.get_account(1).halt("MAX_DRAWDOWN")
        assert engine.resume_strategy(1) is True
        assert not engine.get_account(1).is_halted

    def test_resume_nonexistent_returns_false(self):
        engine = make_engine()
        assert engine.resume_strategy(999) is False


class TestFillManagement:
    def test_drain_pending_fills(self):
        engine = make_engine(tick_price=50000.0)
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        fills = engine.drain_pending_fills()
        assert len(fills) == 1
        # Second drain should be empty
        assert len(engine.drain_pending_fills()) == 0

    def test_get_pending_fill_count(self):
        engine = make_engine(tick_price=50000.0)
        assert engine.get_pending_fill_count() == 0
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert engine.get_pending_fill_count() == 1


class TestStatus:
    def test_get_status(self):
        engine = make_engine()
        status = engine.get_status()
        assert status["strategies"] == 1
        assert status["working_orders"] == 0
        assert status["pending_fills"] == 0
        assert status["halted"] == 0

    def test_get_all_equity(self):
        engine = make_engine(tick_price=50000.0)
        equity = engine.get_all_equity()
        assert 1 in equity
        assert equity[1] == pytest.approx(100000.0)


class TestClientOrderIdValidation:
    def test_accepts_valid_uuid(self):
        engine = make_engine()
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "MARKET", quantity=1.0,
            client_order_id="550e8400-e29b-41d4-a716-446655440000"
        )
        assert fill is not None
        assert reason is None

    def test_rejects_none_uuid(self):
        engine = make_engine()
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "MARKET", quantity=1.0,
            client_order_id="not-a-uuid"
        )
        assert fill is None
        assert reason == RejectReason.CLIENT_ORDER_ID_INVALID.value

    def test_rejects_too_long(self):
        engine = make_engine()
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "MARKET", quantity=1.0,
            client_order_id="a" * 51
        )
        assert fill is None
        assert reason == RejectReason.CLIENT_ORDER_ID_TOO_LONG.value

    def test_rejects_when_working_orders_full(self):
        engine = make_engine(tick_price=50000.0)
        for _ in range(1000):
            engine.submit_order(
                1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=49000.0
            )
        assert len(engine.get_working_orders()) == 1000
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=49000.0,
            client_order_id="550e8400-e29b-41d4-a716-446655440001"
        )
        assert fill is None
        assert reason == RejectReason.TOO_MANY_WORKING_ORDERS.value
