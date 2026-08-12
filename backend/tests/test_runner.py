"""Tests for engine/runner.py — StrategyRunner integration with PaperEngine."""
import pytest

from engine.core import PaperEngine, EngineConfig
from engine.market_state import MarketState
from engine.paper_broker import PaperBroker
from engine.risk import RiskManager, RiskConfig
from engine.runner import StrategyRunner, RunnerStrategyConfig
from strategies.base import Action, Candle
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.rsi_reversion import RSIReversionStrategy
from strategies.registry import STRATEGIES, register


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(market):
    broker = PaperBroker(market, slippage_bps=0, impact_notional=1e12)
    rm = RiskManager(RiskConfig(max_position_pct=0.2))
    engine = PaperEngine(
        market, broker, rm,
        EngineConfig(starting_cash=100000.0),
    )
    return engine


def _make_candles(prices, symbol="BTC"):
    """Build a list of Candle objects from close prices."""
    out = []
    for i, p in enumerate(prices):
        out.append(Candle(
            symbol=symbol,
            open_time=i,
            open=p,
            high=p + 1.0,
            low=p - 1.0,
            close=p,
            volume=10.0,
        ))
    return out


def _candle_provider(symbol, limit):
    return _CANDLES.get(symbol, [])


_CANDLES = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_registry():
    """Keep STRATEGIES clean between tests."""
    old = dict(STRATEGIES)
    STRATEGIES.clear()
    yield
    STRATEGIES.clear()
    STRATEGIES.update(old)


@pytest.fixture
def market():
    return MarketState()


@pytest.fixture
def engine(market):
    return _make_engine(market)


@pytest.fixture
def runner(engine, market):
    return StrategyRunner(engine, market, _candle_provider, ["BTC", "ETH"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_skips_unknown_strategy_key(self, engine, market):
        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="nonexistent")]
        results = runner.run_all(configs)
        assert results == []

    def test_skips_unregistered_strategy_id(self, engine, market):
        register(SMACrossoverStrategy())
        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=999, key="sma_crossover")]
        results = runner.run_all(configs)
        assert results == []

    def test_skips_halted_account(self, engine, market):
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)
        engine.get_account(1).halt("TEST")
        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="sma_crossover")]
        results = runner.run_all(configs)
        assert results == []

    def test_buy_signal_produces_fill(self, engine, market):
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)

        prices = [100.0] * 30 + [120.0]
        _CANDLES["BTC"] = _make_candles(prices)
        market.on_tick_batch([
            {"symbol": "BTC", "price": 120.0, "bid": 119.5, "ask": 120.5},
        ])

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="sma_crossover")]
        results = runner.run_all(configs)

        assert len(results) == 1
        r = results[0]
        assert r.strategy_id == 1
        assert r.symbol == "BTC"
        assert r.decision.action == Action.BUY
        assert r.fill is not None
        assert r.reject_reason is None

    def test_sell_signal_without_position_is_rejected(self, engine, market):
        strategy = RSIReversionStrategy()
        register(strategy)
        engine.register_strategy(2, "rsi_reversion", 100000.0)

        prices = [100.0] * 15 + [95.0] * 5
        _CANDLES["BTC"] = _make_candles(prices)
        market.on_tick_batch([
            {"symbol": "BTC", "price": 95.0, "bid": 94.5, "ask": 95.5},
        ])

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=2, key="rsi_reversion")]
        results = runner.run_all(configs)

        assert len(results) == 1
        r = results[0]
        assert r.decision.action == Action.BUY
        assert r.fill is not None

    def test_insufficient_candles_skips_symbol(self, engine, market):
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)

        _CANDLES["BTC"] = _make_candles([100.0] * 5)
        market.on_tick_batch([
            {"symbol": "BTC", "price": 100.0, "bid": 99.5, "ask": 100.5},
        ])

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="sma_crossover")]
        results = runner.run_all(configs)
        assert results == []

    def test_no_price_skips_symbol(self, engine, market):
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)

        prices = [100.0] * 30 + [120.0]
        _CANDLES["BTC"] = _make_candles(prices)
        # Do NOT feed a tick for BTC → market.last("BTC") returns None

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="sma_crossover")]
        results = runner.run_all(configs)
        assert results == []

    def test_multiple_symbols(self, engine, market):
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)

        prices = [100.0] * 30 + [120.0]
        _CANDLES["BTC"] = _make_candles(prices, "BTC")
        _CANDLES["ETH"] = _make_candles(prices, "ETH")
        market.on_tick_batch([
            {"symbol": "BTC", "price": 120.0, "bid": 119.5, "ask": 120.5},
            {"symbol": "ETH", "price": 120.0,
             "bid": 119.5, "ask": 120.5},
        ])

        runner = StrategyRunner(
            engine, market, _candle_provider, ["BTC", "ETH"],
        )
        configs = [RunnerStrategyConfig(strategy_id=1, key="sma_crossover")]
        results = runner.run_all(configs)

        assert len(results) == 2
        symbols = {r.symbol for r in results}
        assert symbols == {"BTC", "ETH"}

    def test_strategy_exception_is_caught(self, engine, market):
        class BadStrategy:
            key = "bad"
            name = "Bad"
            default_params = {}
            warmup_bars = 1

            def evaluate(self, ctx):
                raise RuntimeError("boom")

        register(BadStrategy())
        engine.register_strategy(1, "bad", 100000.0)

        _CANDLES["BTC"] = _make_candles([100.0] * 5)
        market.on_tick_batch([
            {"symbol": "BTC", "price": 100.0, "bid": 99.5, "ask": 100.5},
        ])

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [RunnerStrategyConfig(strategy_id=1, key="bad")]
        results = runner.run_all(configs)
        assert results == []

    def test_dry_run_param_does_not_trade(self, engine, market):
        """V4: when dry_run is True, runner should not submit orders."""
        strategy = SMACrossoverStrategy()
        register(strategy)
        engine.register_strategy(1, "sma_crossover", 100000.0)

        prices = [100.0] * 30 + [120.0]
        _CANDLES["BTC"] = _make_candles(prices)
        market.on_tick_batch([
            {"symbol": "BTC", "price": 120.0, "bid": 119.5, "ask": 120.5},
        ])

        runner = StrategyRunner(engine, market, _candle_provider, ["BTC"])
        configs = [
            RunnerStrategyConfig(
                strategy_id=1, key="sma_crossover",
                params={"dry_run": True},
            ),
        ]
        results = runner.run_all(configs)

        assert len(results) == 1
        r = results[0]
        assert r.decision.action == Action.BUY
        assert r.fill is None
        assert r.reject_reason is None
