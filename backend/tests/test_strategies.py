"""Tests for strategies/base.py and strategies/registry.py."""
import pytest

from strategies.base import (
    Action,
    Candle,
    Position,
    StrategyContext,
    Decision,
    Strategy,
    IndicatorBundle,
)
from strategies.registry import register, get_strategy, list_strategies, STRATEGIES


# ---------------------------------------------------------------------------
# Dummy strategy for registry tests
# ---------------------------------------------------------------------------

class DummyStrategy:
    key = "dummy"
    name = "Dummy Strategy"
    default_params = {"window": 10}
    warmup_bars = 5

    def evaluate(self, ctx):
        return Decision(action=Action.HOLD, reason="noop")


# ---------------------------------------------------------------------------
# StrategyContext / Decision
# ---------------------------------------------------------------------------

class TestStrategyContext:
    def test_defaults(self):
        ctx = StrategyContext(symbol="BTC")
        assert ctx.symbol == "BTC"
        assert ctx.candles == []
        assert ctx.last_price == 0.0
        assert ctx.position is None
        assert ctx.cash == 0.0
        assert ctx.equity == 0.0
        assert ctx.params == {}

    def test_with_position(self):
        pos = Position(symbol="ETH", quantity=1.0, avg_entry_price=3000.0)
        ctx = StrategyContext(symbol="ETH", position=pos, cash=5000.0)
        assert ctx.position.quantity == 1.0
        assert ctx.cash == 5000.0


class TestDecision:
    def test_default_decision(self):
        d = Decision()
        assert d.action == Action.HOLD
        assert d.strength == 0.0
        assert d.reason == ""
        assert d.indicators == {}

    def test_custom_decision(self):
        d = Decision(action=Action.BUY, strength=0.8, reason="sma_cross",
                     indicators={"sma": 100.0})
        assert d.action == Action.BUY
        assert d.strength == 0.8
        assert d.reason == "sma_cross"
        assert d.indicators["sma"] == 100.0


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestStrategyProtocol:
    def test_dummy_is_strategy(self):
        assert isinstance(DummyStrategy(), Strategy)

    def test_missing_key_rejects(self):
        class Bad:
            def evaluate(self, ctx):
                return Decision()

        with pytest.raises(TypeError):
            register(Bad())


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def setup_method(self):
        # Isolate registry state between tests
        STRATEGIES.clear()

    def test_register_adds_strategy(self):
        register(DummyStrategy())
        assert "dummy" in STRATEGIES

    def test_register_duplicate_raises(self):
        register(DummyStrategy())
        with pytest.raises(KeyError):
            register(DummyStrategy())

    def test_get_existing(self):
        register(DummyStrategy())
        assert get_strategy("dummy") is not None

    def test_get_missing_returns_none(self):
        assert get_strategy("nonexistent") is None

    def test_list_strategies(self):
        register(DummyStrategy())
        keys = list_strategies()
        assert keys == ["dummy"]


# ---------------------------------------------------------------------------
# IndicatorBundle
# ---------------------------------------------------------------------------

class TestIndicatorBundle:
    @pytest.fixture
    def candles(self):
        return [
            Candle(symbol="BTC", open_time=i, open=100.0 + i, high=101.0 + i,
                   low=99.0 + i, close=100.0 + i, volume=10.0)
            for i in range(20)
        ]

    def test_sma(self, candles):
        bundle = IndicatorBundle(candles)
        val = bundle.sma(5)
        assert val is not None
        assert 114.0 < val < 118.0

    def test_rsi(self, candles):
        bundle = IndicatorBundle(candles)
        val = bundle.rsi(14)
        assert val is not None
        assert 99.0 < val <= 100.0

    def test_bbands(self, candles):
        bundle = IndicatorBundle(candles)
        result = bundle.bbands(5, 2.0)
        assert result is not None
        lower, middle, upper = result
        assert lower < middle < upper
