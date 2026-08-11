"""Tests for engine/portfolio.py — cost-basis accounting, H5 identity, H10 division guards."""
import math
import random
from datetime import datetime, timezone

import pytest
from engine.portfolio import PortfolioAccount, Position, _is_finite


class TestPositionBasics:
    def test_new_position_is_empty(self):
        pos = Position(symbol="BTC")
        assert not pos.is_open
        assert pos.market_value(100.0) == 0.0
        assert pos.unrealized_pnl(100.0) == 0.0
        assert pos.unrealized_pnl_pct(100.0) == 0.0

    def test_market_value(self):
        pos = Position(symbol="BTC", quantity=2.0, avg_entry_price=100.0)
        assert pos.market_value(150.0) == 300.0

    def test_market_value_bad_mark(self):
        pos = Position(symbol="BTC", quantity=2.0, avg_entry_price=100.0)
        assert pos.market_value(0.0) == 0.0
        assert pos.market_value(-1.0) == 0.0
        assert pos.market_value(float("nan")) == 0.0

    def test_unrealized_pnl(self):
        pos = Position(symbol="BTC", quantity=2.0, avg_entry_price=100.0)
        # price 150 -> (150-100)*2 = 100
        assert pos.unrealized_pnl(150.0) == 100.0
        # price 50 -> (50-100)*2 = -100
        assert pos.unrealized_pnl(50.0) == -100.0

    def test_unrealized_pnl_pct(self):
        pos = Position(symbol="BTC", quantity=2.0, avg_entry_price=100.0)
        # price 150 -> (150-100)/100 = 0.5
        assert pos.unrealized_pnl_pct(150.0) == pytest.approx(0.5)


class TestApplyFillBuy:
    def test_buy_deducts_cash(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=5.0)
        assert acct.cash == pytest.approx(100000.0 - 50000.0 - 5.0)
        assert acct.positions["BTC"].quantity == 1.0
        assert acct.positions["BTC"].avg_entry_price == pytest.approx(50005.0)  # fee capitalised

    def test_buy_weighted_average(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=200000.0)
        # First buy: 1 BTC at 50000, fee 5
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=5.0)
        # Second buy: 1 BTC at 60000, fee 6
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=60000.0, fee=6.0)
        # avg = (1*50005 + 1*60006) / 2 = 55005.5
        assert acct.positions["BTC"].quantity == pytest.approx(2.0)
        assert acct.positions["BTC"].avg_entry_price == pytest.approx(55005.5)

    def test_buy_insufficient_cash_raises(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0)


class TestApplyFillSell:
    def test_sell_credits_cash_and_realized(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=0.0)
        # Sell at 55000, fee 5
        acct.apply_fill("SELL", "BTC", quantity=1.0, price=55000.0, fee=5.0)
        # cash = 100000 - 50000 + 55000 - 5 = 104995
        assert acct.cash == pytest.approx(104995.0)
        # realized = 1*(55000 - 50000) - 5 = 4995
        assert acct.realized_pnl == pytest.approx(4995.0)
        assert acct.positions["BTC"].quantity == 0.0
        assert acct.positions["BTC"].avg_entry_price == 0.0  # reset on full exit

    def test_partial_sell_keeps_avg_entry(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.apply_fill("BUY", "BTC", quantity=2.0, price=50000.0, fee=0.0)
        acct.apply_fill("SELL", "BTC", quantity=1.0, price=55000.0, fee=0.0)
        # avg_entry should stay at 50000 (not reset)
        assert acct.positions["BTC"].quantity == pytest.approx(1.0)
        assert acct.positions["BTC"].avg_entry_price == pytest.approx(50000.0)
        assert acct.realized_pnl == pytest.approx(5000.0)

    def test_sell_no_position_raises(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=10000.0)
        with pytest.raises(ValueError, match="Insufficient position"):
            acct.apply_fill("SELL", "BTC", quantity=1.0, price=50000.0)


class TestH1NaNRejection:
    """H1: non-finite values must never enter the portfolio."""

    def test_nan_quantity_rejected(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        with pytest.raises(ValueError, match="Non-finite"):
            acct.apply_fill("BUY", "BTC", quantity=float("nan"), price=100.0)

    def test_inf_price_rejected(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        with pytest.raises(ValueError, match="Non-finite"):
            acct.apply_fill("BUY", "BTC", quantity=1.0, price=float("inf"))

    def test_zero_quantity_rejected(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        with pytest.raises(ValueError, match="Non-positive"):
            acct.apply_fill("BUY", "BTC", quantity=0.0, price=100.0)

    def test_negative_price_rejected(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        with pytest.raises(ValueError, match="Non-positive"):
            acct.apply_fill("BUY", "BTC", quantity=1.0, price=-100.0)


class TestH10DivisionGuards:
    """H10: every division must return a defined value, never inf/NaN."""

    def test_drawdown_with_zero_peak(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=0.0)
        acct.peak_equity = 0.0
        assert acct.drawdown_pct({}) == 0.0  # no crash

    def test_unrealized_pnl_pct_no_position(self):
        pos = Position(symbol="BTC", quantity=0.0, avg_entry_price=0.0)
        assert pos.unrealized_pnl_pct(100.0) == 0.0

    def test_unrealized_pnl_pct_zero_avg_entry(self):
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=0.0)
        assert pos.unrealized_pnl_pct(100.0) == 0.0


class TestEquityIdentity:
    """H5/H7: The accounting identity — equity == starting_cash + realized + unrealized.

    This is the single most important test in the suite. It runs random
    buy/sell sequences and asserts the identity holds at every step.
    """

    def test_equity_identity_random_sequence(self):
        """Property test: equity identity holds after every fill."""
        random.seed(42)
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        marks = {"BTC": 50000.0, "ETH": 3000.0, "SOL": 150.0}

        for step in range(500):
            symbol = random.choice(["BTC", "ETH", "SOL"])
            side = random.choice(["BUY", "SELL"])
            price = marks[symbol] * random.uniform(0.9, 1.1)  # ±10% from mark
            price = max(price, 1.0)  # never zero
            qty = random.uniform(0.01, 1.0)
            fee = qty * price * 0.001  # 10 bps

            # Update mark to the trade price
            marks[symbol] = price

            try:
                acct.apply_fill(side, symbol, quantity=qty, price=price, fee=fee)
            except ValueError:
                # Insufficient cash or position — skip this step
                continue

            # Assert the accounting identity
            equity = acct.equity(marks)
            unrealized = acct.unrealized_pnl(marks)
            expected = acct.starting_cash + acct.realized_pnl + unrealized
            assert math.isclose(equity, expected, rel_tol=1e-9, abs_tol=1e-6), (
                f"Step {step}: equity={equity} != starting_cash({acct.starting_cash}) "
                f"+ realized({acct.realized_pnl}) + unrealized({unrealized}) = {expected}"
            )

            # Cash should never go negative (we check before applying)
            assert acct.cash >= -1e-6, f"Step {step}: cash={acct.cash} is negative"

    def test_equity_identity_no_trades(self):
        """With no trades, equity == starting_cash."""
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=50000.0)
        marks = {"BTC": 50000.0}
        assert acct.equity(marks) == 50000.0
        assert acct.unrealized_pnl(marks) == 0.0
        assert acct.realized_pnl == 0.0

    def test_equity_identity_after_buy(self):
        """After a buy, equity == cash + position_value."""
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=5.0)
        marks = {"BTC": 55000.0}
        equity = acct.equity(marks)
        # cash = 100000 - 50005 = 49995
        # position_value = 1 * 55000 = 55000
        # equity = 49995 + 55000 = 104995
        assert equity == pytest.approx(104995.0)
        # identity: starting_cash + realized + unrealized
        # realized = 0, unrealized = 1*(55000 - 50005) = 4995
        # 100000 + 0 + 4995 = 104995 ✓
        assert equity == pytest.approx(acct.starting_cash + acct.realized_pnl + acct.unrealized_pnl(marks))


class TestHaltResume:
    def test_halt_sets_flag(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.halt("MAX_DRAWDOWN")
        assert acct.is_halted
        assert acct.halt_reason == "MAX_DRAWDOWN"

    def test_resume_clears_flag(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.halt("MAX_DRAWDOWN")
        acct.resume()
        assert not acct.is_halted
        assert acct.halt_reason is None


class TestPeakEquity:
    def test_update_peak_on_new_high(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        marks = {"BTC": 50000.0}
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=0.0)
        marks = {"BTC": 55000.0}  # position goes up
        updated = acct.update_peak(marks)
        assert updated
        assert acct.peak_equity > 100000.0

    def test_no_update_on_drawdown(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        marks = {"BTC": 50000.0}
        acct.apply_fill("BUY", "BTC", quantity=1.0, price=50000.0, fee=0.0)
        marks = {"BTC": 45000.0}  # position goes down
        updated = acct.update_peak(marks)
        assert not updated
        assert acct.peak_equity == 100000.0

    def test_drawdown_calculation(self):
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.peak_equity = 100000.0
        marks = {}
        # cash = 100000, no positions, equity = 100000, no drawdown
        assert acct.drawdown_pct(marks) == 0.0
        # Simulate a loss: set cash to 80000
        acct.cash = 80000.0
        assert acct.drawdown_pct(marks) == pytest.approx(0.20)
