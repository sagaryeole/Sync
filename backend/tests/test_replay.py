"""Tests for V1 deterministic replay / time-travel."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from engine.core import PaperEngine, EngineConfig
from engine.paper_broker import PaperBroker, Fill
from engine.risk import RiskManager, RiskConfig
from engine.market_state import MarketState


def make_engine(cash=100000.0, tick_price=50000.0):
    from tests.test_engine_core import make_tick, make_market_state
    tick = make_tick(tick_price)
    ms = make_market_state(tick=tick, prices={"BTC": tick_price}, last_price=tick_price)
    broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
    rm = RiskManager(RiskConfig(max_position_pct=0.95))
    engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=cash))
    engine.register_strategy(1, "test", cash)
    return engine


def make_fill(strategy_id, symbol, side, quantity, price, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return Fill(
        client_order_id="test",
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        fee=0.0,
        order_type="MARKET",
        ts=ts,
    )


class TestReplay:
    def test_rebuild_from_empty_fills(self):
        engine = make_engine()
        fills = {1: []}
        marks = {"BTC": 50000.0}
        result = engine.rebuild_from_fills(fills, marks)
        assert result[1]["cash"] == 100000.0
        assert result[1]["positions"] == {}

    def test_rebuild_after_buy(self):
        engine = make_engine()
        f = make_fill(1, "BTC", "BUY", 1.0, 50000.0)
        fills = {1: [f]}
        marks = {"BTC": 50000.0}
        result = engine.rebuild_from_fills(fills, marks)
        assert result[1]["cash"] == pytest.approx(50000.0)
        assert result[1]["positions"] == {"BTC": 1.0}

    def test_rebuild_after_sell(self):
        engine = make_engine()
        f = make_fill(1, "BTC", "SELL", 1.0, 50000.0)
        fills = {1: [f]}
        marks = {"BTC": 50000.0}
        result = engine.rebuild_from_fills(fills, marks)
        assert result[1]["cash"] == pytest.approx(150000.0)
        assert result[1]["positions"] == {"BTC": -1.0}

    def test_rebuild_with_fee(self):
        engine = make_engine()
        f = make_fill(1, "BTC", "BUY", 1.0, 50000.0)
        f.fee = 10.0
        fills = {1: [f]}
        marks = {"BTC": 50000.0}
        result = engine.rebuild_from_fills(fills, marks)
        assert result[1]["cash"] == pytest.approx(49990.0)
        assert result[1]["positions"] == {"BTC": 1.0}

    def test_rebuild_before_timestamp(self):
        engine = make_engine()
        now = datetime.now(timezone.utc)
        f1 = make_fill(1, "BTC", "BUY", 1.0, 50000.0, ts=now - timedelta(hours=2))
        f2 = make_fill(1, "BTC", "SELL", 0.5, 55000.0, ts=now - timedelta(hours=1))
        f3 = make_fill(1, "ETH", "BUY", 10.0, 3000.0, ts=now)
        fills = {1: [f1, f2, f3]}
        marks = {"BTC": 55000.0, "ETH": 3000.0}

        result_all = engine.rebuild_from_fills(fills, marks)
        assert result_all[1]["positions"] == {"BTC": 0.5, "ETH": 10.0}

        before_latest = now - timedelta(minutes=30)
        result_before = engine.rebuild_from_fills(fills, marks, before_ts=before_latest)
        assert result_before[1]["positions"] == {"BTC": 0.5}
        assert "ETH" not in result_before[1]["positions"]

    def test_rebuild_multiple_strategies(self):
        engine = make_engine()
        engine.register_strategy(2, "test2", 100000.0)
        f1 = make_fill(1, "BTC", "BUY", 1.0, 50000.0)
        f2 = make_fill(2, "ETH", "BUY", 10.0, 3000.0)
        fills = {1: [f1], 2: [f2]}
        marks = {"BTC": 50000.0, "ETH": 3000.0}
        result = engine.rebuild_from_fills(fills, marks)
        assert result[1]["positions"] == {"BTC": 1.0}
        assert result[2]["positions"] == {"ETH": 10.0}
