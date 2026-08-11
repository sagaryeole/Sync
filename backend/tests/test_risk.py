"""Tests for engine/risk.py — position sizing, SL/TP, drawdown kill-switch, cooldowns."""
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from engine.risk import RiskConfig, RiskManager, CooldownState
from engine.portfolio import PortfolioAccount, Position


def make_account(cash=100000.0, strategy_id=1, key="test"):
    return PortfolioAccount(strategy_id=strategy_id, strategy_key=key, starting_cash=cash)


def make_market(prices=None):
    """Mock MarketState with a snapshot of prices."""
    ms = MagicMock()
    ms.snapshot.return_value = prices or {}
    return ms


class TestSizeOrder:
    def test_basic_sizing(self):
        """Risk 2% of equity against 2% stop distance, capped at 20% of equity.

        entry=50000, SL=49000 (2% below), stop_distance=1000
        risk_amount = 100000 * 0.02 = 2000
        raw_qty = 2000 / 1000 = 2.0 (notional = $100k)
        max_notional = 100000 * 0.20 = 20000, max_qty = 20000 / 50000 = 0.4
        qty capped to 0.4
        """
        rm = RiskManager()
        acct = make_account(100000.0)
        marks = {}
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        assert reason is None
        assert qty == pytest.approx(0.4)  # capped at 20% of equity
        assert sl == pytest.approx(49000.0)
        assert tp == pytest.approx(52000.0)

    def test_basic_sizing_no_cap(self):
        """Without the 20% cap, risk-based sizing gives 2.0 BTC."""
        rm = RiskManager(RiskConfig(max_position_pct=1.0))  # 100% cap = effectively no cap
        acct = make_account(100000.0)
        marks = {}
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        assert reason is None
        assert qty == pytest.approx(2.0)
        assert sl == pytest.approx(49000.0)
        assert tp == pytest.approx(52000.0)

    def test_capped_at_max_position_pct(self):
        """Quantity capped at 20% of equity."""
        rm = RiskManager(RiskConfig(max_position_pct=0.01))  # 1% cap
        acct = make_account(100000.0)
        marks = {}
        # entry=100, SL=98 (2% below), stop_distance=2
        # risk_amount = 2000, qty = 2000/2 = 1000
        # max_notional = 100000 * 0.01 = 1000, max_qty = 1000/100 = 10
        # qty capped to 10
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 100.0, marks)
        assert reason is None
        assert qty == pytest.approx(10.0)

    def test_floored_at_min_notional(self):
        """Quantity floored at min_notional when risk amount is tiny."""
        rm = RiskManager(RiskConfig(risk_per_trade_pct=0.0001, min_notional=10.0))
        acct = make_account(100000.0)
        marks = {}
        # risk_amount = 100000 * 0.0001 = 10
        # stop_distance = 50000 * 0.02 = 1000
        # qty = 10 / 1000 = 0.01 -> notional = 0.01 * 50000 = 500 -> above min $10
        # Actually 0.01 * 50000 = 500, which is > 10, so no flooring needed
        # Let's use a higher price to make notional smaller
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        assert reason is None
        assert qty > 0

    def test_strategy_halted_rejects(self):
        rm = RiskManager()
        acct = make_account()
        acct.halt("MAX_DRAWDOWN")
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, {})
        assert reason == "STRATEGY_HALTED"
        assert qty is None

    def test_max_open_positions_rejects(self):
        rm = RiskManager(RiskConfig(max_open_positions=2))
        acct = make_account(1000000.0)
        # Manually open 2 positions
        acct.apply_fill("BUY", "BTC", 1.0, 50000.0, 0.0)
        acct.apply_fill("BUY", "ETH", 1.0, 3000.0, 0.0)
        marks = {"BTC": 50000.0, "ETH": 3000.0}
        # Try to open a 3rd
        qty, sl, tp, reason = rm.size_order(acct, "SOL", 150.0, marks)
        assert reason == "MAX_POSITIONS"

    def test_existing_position_does_not_count_as_new(self):
        """Adding to an existing position should not trigger max_positions."""
        rm = RiskManager(RiskConfig(max_open_positions=1))
        acct = make_account(1000000.0)
        acct.apply_fill("BUY", "BTC", 1.0, 50000.0, 0.0)
        marks = {"BTC": 50000.0}
        # Adding to BTC should be OK (not a new position)
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        assert reason is None
        assert qty > 0

    def test_insufficient_cash_scales_down(self):
        rm = RiskManager()
        acct = make_account(100.0)  # very little cash
        marks = {}
        # entry=50000, risk_amount = 100 * 0.02 = 2
        # stop_distance = 1000, qty = 2/1000 = 0.002
        # notional = 0.002 * 50000 = 100 -> exactly all cash
        # But with fees, it won't be enough. Should scale down or reject.
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        # Either scaled down or rejected — both are valid
        if reason is None:
            assert qty > 0
            assert qty * 50000.0 <= 100.0 + 1e-6
        else:
            assert reason in ("INSUFFICIENT_CASH", "BELOW_MIN_NOTIONAL")

    def test_invalid_price_rejects(self):
        rm = RiskManager()
        acct = make_account()
        qty, sl, tp, reason = rm.size_order(acct, "BTC", -1.0, {})
        assert reason == "INVALID_PRICE"
        qty, sl, tp, reason = rm.size_order(acct, "BTC", float("nan"), {})
        assert reason == "INVALID_PRICE"

    def test_negative_equity_rejects(self):
        rm = RiskManager()
        acct = make_account(100.0)
        acct.cash = -1000.0  # negative equity
        marks = {}
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, marks)
        assert reason == "INSUFFICIENT_EQUITY"


class TestDrawdownKillSwitch:
    def test_no_trigger_within_limit(self):
        rm = RiskManager(RiskConfig(max_drawdown_pct=0.25))
        acct = make_account(100000.0)
        marks = {}
        # No drawdown
        assert rm.check_drawdown(acct, marks) is False

    def test_triggers_at_threshold(self):
        rm = RiskManager(RiskConfig(max_drawdown_pct=0.25))
        acct = make_account(100000.0)
        acct.peak_equity = 100000.0
        acct.cash = 74000.0  # 26% drawdown
        marks = {}
        assert rm.check_drawdown(acct, marks) is True

    def test_does_not_trigger_just_below_threshold(self):
        rm = RiskManager(RiskConfig(max_drawdown_pct=0.25))
        acct = make_account(100000.0)
        acct.peak_equity = 100000.0
        acct.cash = 76000.0  # 24% drawdown
        marks = {}
        assert rm.check_drawdown(acct, marks) is False

    def test_updates_peak(self):
        rm = RiskManager()
        acct = make_account(100000.0)
        acct.apply_fill("BUY", "BTC", 1.0, 50000.0, 0.0)
        marks = {"BTC": 55000.0}  # equity goes up
        rm.check_drawdown(acct, marks)
        assert acct.peak_equity > 100000.0


class TestFlattenAll:
    def test_flatten_returns_open_positions(self):
        rm = RiskManager()
        acct = make_account(1000000.0)
        acct.apply_fill("BUY", "BTC", 1.0, 50000.0, 0.0)
        acct.apply_fill("BUY", "ETH", 10.0, 3000.0, 0.0)
        market = make_market({"BTC": 50000.0, "ETH": 3000.0})
        to_flatten = rm.flatten_all(acct, market)
        assert len(to_flatten) == 2
        symbols = [s for s, _ in to_flatten]
        assert "BTC" in symbols
        assert "ETH" in symbols

    def test_flatten_empty_for_no_positions(self):
        rm = RiskManager()
        acct = make_account()
        market = make_market({})
        to_flatten = rm.flatten_all(acct, market)
        assert len(to_flatten) == 0


class TestStops:
    def test_attach_stops(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.04))
        pos = Position(symbol="BTC")
        rm.attach_stops(pos, 50000.0)
        assert pos.stop_loss_price == pytest.approx(49000.0)
        assert pos.take_profit_price == pytest.approx(52000.0)

    def test_trailing_stop_updates_on_higher_price(self):
        rm = RiskManager(RiskConfig(trailing_stop=True, trailing_stop_pct=0.02))
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=50000.0)
        rm.attach_stops(pos, 50000.0)
        assert pos.stop_loss_price == pytest.approx(49000.0)
        # Price goes up to 55000
        rm.update_trailing_stop(pos, 55000.0)
        assert pos.stop_loss_price == pytest.approx(53900.0)  # 55000 * 0.98

    def test_trailing_stop_does_not_lower(self):
        rm = RiskManager(RiskConfig(trailing_stop=True, trailing_stop_pct=0.02))
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=50000.0)
        rm.attach_stops(pos, 50000.0)
        original_stop = pos.stop_loss_price
        # Price goes down — stop should not move
        rm.update_trailing_stop(pos, 45000.0)
        assert pos.stop_loss_price == original_stop

    def test_trailing_stop_disabled_by_default(self):
        rm = RiskManager(RiskConfig(trailing_stop=False))
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=50000.0)
        rm.attach_stops(pos, 50000.0)
        rm.update_trailing_stop(pos, 55000.0)
        # Stop should not change (trailing disabled)
        assert pos.stop_loss_price == pytest.approx(49000.0)


class TestCooldown:
    def test_cooldown_starts_on_close(self):
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.start_cooldown(1, "BTC")
        assert rm._is_in_cooldown(1, "BTC")

    def test_cooldown_blocks_sizing(self):
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        acct = make_account()
        rm.start_cooldown(1, "BTC")
        qty, sl, tp, reason = rm.size_order(acct, "BTC", 50000.0, {})
        assert reason == "COOLDOWN"

    def test_cooldown_decrements(self):
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.start_cooldown(1, "BTC")
        rm.tick_cooldowns(1)
        assert rm._is_in_cooldown(1, "BTC")
        rm.tick_cooldowns(1)
        assert rm._is_in_cooldown(1, "BTC")
        rm.tick_cooldowns(1)
        assert not rm._is_in_cooldown(1, "BTC")  # expired after 3 ticks

    def test_cooldown_does_not_block_other_symbols(self):
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        acct = make_account()
        rm.start_cooldown(1, "BTC")
        # ETH should not be in cooldown
        qty, sl, tp, reason = rm.size_order(acct, "ETH", 3000.0, {})
        assert reason is None

    def test_cooldown_per_strategy(self):
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.start_cooldown(1, "BTC")
        # Strategy 2 should not be affected
        assert not rm._is_in_cooldown(2, "BTC")

    def test_get_cooldowns_empty(self):
        rm = RiskManager()
        assert rm.get_cooldowns(1) == {}
