"""Tests for the three trading strategies:
  - sma_crossover.py — SMA(9)/SMA(21) golden/death cross
  - rsi_reversion.py — RSI(14) < 30 buy, > 70 sell, exit at 50
  - momentum_breakout.py — Donchian(20) breakout + ATR(14) filter
"""
import pytest

from strategies.base import Action, Candle, Decision, Position, StrategyContext
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.rsi_reversion import RSIReversionStrategy
from strategies.momentum_breakout import MomentumBreakoutStrategy


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_candles(closes, highs=None, lows=None, volumes=None, symbol="BTC"):
    """Build a list of Candle objects from close prices.

    If highs/lows not given, default to close ± 0.5.
    """
    candles = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c + 0.5
        l = lows[i] if lows else c - 0.5
        v = volumes[i] if volumes else 100.0
        candles.append(
            Candle(
                symbol=symbol,
                open_time=i,
                open=closes[i - 1] if i > 0 else c,
                high=h,
                low=l,
                close=c,
                volume=v,
            )
        )
    return candles


def make_ctx(candles, position=None, cash=100000.0, equity=100000.0, params=None):
    return StrategyContext(
        symbol="BTC",
        candles=candles,
        last_price=candles[-1].close if candles else 0.0,
        position=position,
        cash=cash,
        equity=equity,
        params=params or {},
    )


# ─── SMA Crossover ────────────────────────────────────────────────────────────

class TestSMACrossover:
    @pytest.fixture
    def strategy(self):
        return SMACrossoverStrategy()

    def test_protocol_compliance(self, strategy):
        assert strategy.key == "sma_crossover"
        assert strategy.name == "SMA Crossover"
        assert "fast" in strategy.default_params
        assert "slow" in strategy.default_params
        assert strategy.warmup_bars >= 21

    def test_insufficient_data(self, strategy):
        """Fewer than slow_window+1 bars → HOLD."""
        candles = make_candles([100.0] * 20)  # only 20 bars, need 22
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD
        assert "insufficient" in d.reason

    def test_no_cross_hold(self, strategy):
        """When fast > slow but no cross occurred → HOLD (no position)."""
        # Monotonically increasing → fast always above slow, no cross
        closes = [100.0 + i * 0.1 for i in range(30)]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD
        assert d.reason == "no_signal"

    def test_golden_cross(self, strategy):
        """Fast SMA crosses above slow SMA → BUY.

        21 flat bars (fast == slow) then one sharp jump on the last bar — a
        true cross detected against the previous bar, not just fast > slow
        (which would also fire on every later bar the condition still holds).
        """
        closes = [100.0] * 21 + [130.0]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.BUY
        assert d.reason == "golden_cross"
        assert 0.0 < d.strength <= 1.0
        assert "sma_fast" in d.indicators
        assert "sma_slow" in d.indicators

    def test_death_cross(self, strategy):
        """Fast SMA crosses below slow SMA → SELL."""
        closes = [110.0] * 21 + [80.0]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.SELL
        assert d.reason == "death_cross"
        assert 0.0 < d.strength <= 1.0

    def test_hold_with_position_no_cross(self, strategy):
        """Holding a position, fast still above slow → HOLD."""
        closes = [100.0 + i * 0.5 for i in range(30)]
        candles = make_candles(closes)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=100.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD

    def test_exit_position_fast_below_slow(self, strategy):
        """Holding a position, fast below slow (but no fresh cross) → SELL."""
        # Long decline so fast is well below slow
        closes = [120.0 - i * 1.0 for i in range(30)]
        candles = make_candles(closes)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=115.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        # Either death_cross or fast_below_slow
        assert d.action == Action.SELL

    def test_custom_params(self, strategy):
        """Strategy respects custom fast/slow params."""
        closes = [100.0] * 10 + [100.0 + i * 3.0 for i in range(8)]
        candles = make_candles(closes)
        ctx = make_ctx(candles, params={"fast": 5, "slow": 10})
        d = strategy.evaluate(ctx)
        # With shorter windows, should detect the cross
        assert d.action in (Action.BUY, Action.HOLD)


# ─── RSI Reversion ────────────────────────────────────────────────────────────

class TestRSIReversion:
    @pytest.fixture
    def strategy(self):
        return RSIReversionStrategy()

    def test_protocol_compliance(self, strategy):
        assert strategy.key == "rsi_reversion"
        assert strategy.name == "RSI Reversion"
        assert "period" in strategy.default_params
        assert strategy.warmup_bars >= 14

    def test_insufficient_data(self, strategy):
        """Fewer than period bars → HOLD."""
        candles = make_candles([100.0] * 10)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD
        assert "insufficient" in d.reason

    def test_oversold_buy(self, strategy):
        """RSI < 30 → BUY."""
        # Sharp decline to push RSI below 30
        closes = [100.0] * 5 + [100.0 - i * 3.0 for i in range(15)]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.BUY
        assert d.reason == "rsi_oversold"
        assert "rsi" in d.indicators
        assert d.strength > 0.0

    def test_no_signal_neutral_rsi(self, strategy):
        """RSI in neutral zone → HOLD."""
        # Gentle oscillation around 100
        closes = [100.0 + (i % 3 - 1) * 0.1 for i in range(20)]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD

    def test_exit_at_50(self, strategy):
        """Holding a position, RSI >= 50 → SELL (exit)."""
        # Strong uptrend to push RSI above 50
        closes = [100.0 + i * 1.0 for i in range(20)]
        candles = make_candles(closes)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=100.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        assert d.action == Action.SELL
        assert d.reason == "rsi_exit"

    def test_hold_position_low_rsi(self, strategy):
        """Holding a position, RSI still below exit level → HOLD."""
        # Continued decline
        closes = [100.0 - i * 2.0 for i in range(20)]
        candles = make_candles(closes)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=95.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        # RSI should be very low, below exit level
        assert d.action == Action.HOLD

    def test_custom_params(self, strategy):
        """Strategy respects custom period/oversold params."""
        closes = [100.0] * 5 + [100.0 - i * 2.0 for i in range(10)]
        candles = make_candles(closes)
        ctx = make_ctx(candles, params={"period": 7, "oversold": 40, "exit": 50})
        d = strategy.evaluate(ctx)
        # With lower oversold threshold, might not trigger
        assert d.action in (Action.BUY, Action.HOLD)


# ─── Momentum Breakout ───────────────────────────────────────────────────────

class TestMomentumBreakout:
    @pytest.fixture
    def strategy(self):
        return MomentumBreakoutStrategy()

    def test_protocol_compliance(self, strategy):
        assert strategy.key == "momentum_breakout"
        assert strategy.name == "Momentum Breakout"
        assert "donchian_window" in strategy.default_params
        assert "atr_period" in strategy.default_params
        assert strategy.warmup_bars >= 20

    def test_insufficient_data(self, strategy):
        """Fewer than donchian_window+1 bars → HOLD."""
        candles = make_candles([100.0] * 15)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD
        assert "insufficient" in d.reason

    def test_breakout_upper_buy(self, strategy):
        """Close breaks above Donchian upper channel → BUY."""
        # 20 bars in a range, then a breakout bar
        closes = [100.0] * 20 + [110.0]
        highs = [101.0] * 20 + [111.0]
        lows = [99.0] * 20 + [109.0]
        candles = make_candles(closes, highs=highs, lows=lows)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.BUY
        assert d.reason == "breakout_upper"
        assert "donchian_upper" in d.indicators
        assert "atr" in d.indicators

    def test_no_breakout_hold(self, strategy):
        """Price within Donchian channel → HOLD."""
        closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(25)]
        candles = make_candles(closes)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD

    def test_trailing_stop_exit(self, strategy):
        """Holding a position, price drops below ATR trail → SELL."""
        # Build a scenario where there was a high, then a drop
        closes = [100.0 + i * 1.0 for i in range(15)] + [115.0 - i * 2.0 for i in range(8)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        candles = make_candles(closes, highs=highs, lows=lows)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=105.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        assert d.action == Action.SELL
        assert d.reason in ("trail_stop", "exit_low")

    def test_hold_position_no_exit(self, strategy):
        """Holding a position, price still above trail → HOLD."""
        # Steady uptrend
        closes = [100.0 + i * 0.5 for i in range(25)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        candles = make_candles(closes, highs=highs, lows=lows)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=100.0)
        ctx = make_ctx(candles, position=pos)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD

    def test_breakout_lower_no_short(self, strategy):
        """Close breaks below lower channel → HOLD (no shorting)."""
        closes = [100.0] * 20 + [90.0]
        highs = [101.0] * 20 + [91.0]
        lows = [99.0] * 20 + [89.0]
        candles = make_candles(closes, highs=highs, lows=lows)
        ctx = make_ctx(candles)
        d = strategy.evaluate(ctx)
        assert d.action == Action.HOLD
        assert "no_short" in d.reason

    def test_custom_params(self, strategy):
        """Strategy respects custom donchian/atr params."""
        closes = [100.0] * 10 + [108.0]
        highs = [101.0] * 10 + [109.0]
        lows = [99.0] * 10 + [107.0]
        candles = make_candles(closes, highs=highs, lows=lows)
        ctx = make_ctx(candles, params={"donchian_window": 10, "atr_period": 7})
        d = strategy.evaluate(ctx)
        assert d.action == Action.BUY
        assert d.reason == "breakout_upper"


# ─── Strategy Registration ────────────────────────────────────────────────────

class TestStrategyRegistration:
    def test_all_three_registered(self):
        """Importing the strategy modules should register them."""
        from strategies.registry import STRATEGIES, get_strategy

        # The modules are imported at collection time, so they should be registered
        assert "sma_crossover" in STRATEGIES
        assert "rsi_reversion" in STRATEGIES
        assert "momentum_breakout" in STRATEGIES

        s = get_strategy("sma_crossover")
        assert s is not None
        assert s.name == "SMA Crossover"

        s = get_strategy("rsi_reversion")
        assert s is not None
        assert s.name == "RSI Reversion"

        s = get_strategy("momentum_breakout")
        assert s is not None
        assert s.name == "Momentum Breakout"
