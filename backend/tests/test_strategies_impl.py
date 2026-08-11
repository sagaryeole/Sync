"""Tests for the three strategy implementations."""

from strategies.base import Action, Candle, Position, StrategyContext
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.rsi_reversion import RSIReversionStrategy
from strategies.momentum_breakout import MomentumBreakoutStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candles(prices, highs=None, lows=None):
    """Build a list of Candle objects from close prices."""
    out = []
    for i, p in enumerate(prices):
        high = highs[i] if highs else p + 1.0
        low = lows[i] if lows else p - 1.0
        out.append(Candle(
            symbol="BTC", open_time=i, open=p, high=high, low=low, close=p,
            volume=10.0,
        ))
    return out


def _ctx(candles, position=None, cash=100000.0, equity=100000.0, params=None):
    return StrategyContext(
        symbol="BTC",
        candles=candles,
        last_price=candles[-1].close if candles else 0.0,
        position=position,
        cash=cash,
        equity=equity,
        params=params,
    )


# ---------------------------------------------------------------------------
# SMA Crossover
# ---------------------------------------------------------------------------

class TestSMACrossover:
    def test_holds_without_warmup(self):
        strat = SMACrossoverStrategy()
        prices = [100.0 + i for i in range(10)]  # < 21 bars
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.HOLD

    def test_golden_cross_buys(self):
        strat = SMACrossoverStrategy()
        prices = [100.0] * 20 + [110.0] * 5  # sharp rise → fast > slow
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.BUY
        assert d.reason == "golden_cross"

    def test_death_cross_sells(self):
        strat = SMACrossoverStrategy()
        prices = [110.0] * 20 + [100.0] * 5  # decline → fast < slow
        candles = _candles(prices)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=110.0)
        d = strat.evaluate(_ctx(candles, position=pos))
        assert d.action == Action.SELL
        assert d.reason == "death_cross"

    def test_holds_without_signal(self):
        strat = SMACrossoverStrategy()
        prices = [100.0 for _ in range(30)]  # perfectly flat
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.HOLD


# ---------------------------------------------------------------------------
# RSI Reversion
# ---------------------------------------------------------------------------

class TestRSIReversion:
    def test_holds_without_warmup(self):
        strat = RSIReversionStrategy()
        prices = [100.0] * 5  # < 15 bars
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.HOLD

    def test_buys_when_oversold(self):
        strat = RSIReversionStrategy()
        prices = [100.0] * 15 + [95.0] * 5  # decline → RSI < 30
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.BUY
        assert d.reason == "rsi_oversold"

    def test_sells_at_exit(self):
        strat = RSIReversionStrategy()
        prices = [100.0] * 15 + [95.0] * 5 + [105.0] * 10  # recovery
        candles = _candles(prices)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=95.0)
        d = strat.evaluate(_ctx(candles, position=pos))
        assert d.action == Action.SELL
        assert d.reason == "rsi_exit"

    def test_strength_scales_with_rsi(self):
        strat = RSIReversionStrategy()
        prices = [100.0] * 15 + [90.0] * 10  # deep decline
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.BUY
        assert d.strength > 0.0


# ---------------------------------------------------------------------------
# Momentum Breakout
# ---------------------------------------------------------------------------

class TestMomentumBreakout:
    def test_holds_without_warmup(self):
        strat = MomentumBreakoutStrategy()
        prices = [100.0 + i for i in range(10)]
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles))
        assert d.action == Action.HOLD

    def test_buys_on_upper_breakout(self):
        strat = MomentumBreakoutStrategy()
        prices = [100.0 + i * 0.5 for i in range(30)] + [
            200.0, 210.0, 220.0,
        ]
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles, params={"atr_multiplier": 0.1}))
        assert d.action == Action.BUY
        assert d.reason == "breakout_upper"

    def test_sells_on_trail_stop(self):
        strat = MomentumBreakoutStrategy()
        prices = [100.0 + i * 0.5 for i in range(30)] + [
            200.0, 210.0, 220.0, 200.0, 190.0,
        ]
        candles = _candles(prices)
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=200.0)
        d = strat.evaluate(
            _ctx(candles, position=pos, params={"atr_multiplier": 0.1}),
        )
        assert d.action == Action.SELL
        assert d.reason == "trail_stop"

    def test_ignores_lower_breakout(self):
        strat = MomentumBreakoutStrategy()
        prices = [100.0 + i * 0.5 for i in range(30)] + [
            50.0, 45.0, 40.0,
        ]
        candles = _candles(prices)
        d = strat.evaluate(_ctx(candles, params={"atr_multiplier": 0.1}))
        assert d.action == Action.HOLD
        assert d.reason == "breakout_lower_no_short"
