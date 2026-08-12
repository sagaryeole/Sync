"""Tests for the strategy metrics endpoints.

Regression coverage for two bugs found live:

1. GET /strategies/{id}/metrics returned 500 on every call. engine.metrics'
   trade-level functions take *matched* (buy, sell, pnl) tuples from
   _pair_trades() and its snapshot functions take dicts (they use .get()),
   but the endpoint passed raw SQLAlchemy Fill/EquitySnapshot rows straight
   in — "TypeError: cannot unpack non-iterable Fill object".

2. GET /strategies/key/{key}/metrics did not exist at all (404). The frontend
   routes on key, called it anyway, and did not check response.ok — so it
   parsed the 404 body as metrics and crashed rendering on undefined.

Neither was caught because no test drove these endpoints.
"""
import math

import pytest
from fastapi.testclient import TestClient

from main import app
from database import get_session
from models import (
    Strategy as StrategyModel,
    Order as OrderModel,
    Fill as FillModel,
    EquitySnapshot as EquitySnapshotModel,
)
from datetime import datetime, timezone, timedelta

client = TestClient(app)

METRIC_KEYS = {
    "total_return_pct", "win_rate", "avg_win", "avg_loss", "profit_factor",
    "max_drawdown_pct", "intraday_sharpe", "trade_count", "avg_hold_time_seconds",
}


@pytest.fixture
def strategy_with_history():
    """A strategy with one full round trip (BUY then SELL) and two snapshots."""
    session = get_session()
    try:
        strat = StrategyModel(
            key="metrics_fixture",
            name="Metrics Fixture",
            description="",
            starting_cash=100000.0,
            enabled=True,
        )
        session.add(strat)
        session.flush()

        t0 = datetime.now(timezone.utc) - timedelta(hours=1)

        def _order(coid, side, price, ts):
            # fills.order_id is NOT NULL, so each fill needs a real parent row.
            o = OrderModel(
                client_order_id=coid, strategy_id=strat.id, symbol="BTC",
                side=side, order_type="MARKET", quantity=1.0, status="FILLED",
                filled_quantity=1.0, avg_fill_price=price,
                created_at=ts, updated_at=ts,
            )
            session.add(o)
            session.flush()
            return o.id

        buy_id = _order("metrics-fixture-buy", "BUY", 50000.0, t0)
        sell_id = _order("metrics-fixture-sell", "SELL", 51000.0, t0 + timedelta(minutes=30))

        session.add(FillModel(
            order_id=buy_id, strategy_id=strat.id, symbol="BTC", side="BUY",
            quantity=1.0, price=50000.0, fee=50.0, realized_pnl=0.0,
            mark_price=50000.0, liquidity="TAKER", ts=t0,
        ))
        session.add(FillModel(
            order_id=sell_id, strategy_id=strat.id, symbol="BTC", side="SELL",
            quantity=1.0, price=51000.0, fee=51.0, realized_pnl=899.0,
            mark_price=51000.0, liquidity="TAKER", ts=t0 + timedelta(minutes=30),
        ))
        session.add(EquitySnapshotModel(
            strategy_id=strat.id, ts=t0, equity=100000.0, cash=100000.0,
            position_value=0.0, realized_pnl=0.0, unrealized_pnl=0.0,
            drawdown_pct=0.0,
        ))
        session.add(EquitySnapshotModel(
            strategy_id=strat.id, ts=t0 + timedelta(minutes=30), equity=100899.0,
            cash=100899.0, position_value=0.0, realized_pnl=899.0,
            unrealized_pnl=0.0, drawdown_pct=0.0,
        ))
        session.commit()
        sid, skey = strat.id, strat.key
    finally:
        session.close()
    return sid, skey


class TestMetricsById:
    def test_returns_200_not_500(self, strategy_with_history):
        sid, _ = strategy_with_history
        r = client.get(f"/strategies/{sid}/metrics")
        assert r.status_code == 200, r.text

    def test_has_all_metric_keys(self, strategy_with_history):
        sid, _ = strategy_with_history
        body = client.get(f"/strategies/{sid}/metrics").json()
        assert METRIC_KEYS.issubset(body.keys())

    def test_pairs_the_round_trip(self, strategy_with_history):
        """The BUY/SELL pair must be matched into exactly one closed trade."""
        sid, _ = strategy_with_history
        body = client.get(f"/strategies/{sid}/metrics").json()
        assert body["trade_count"] == 1
        # 1.0 * (51000 - 50000) - 51 sell fee = 949 gross of the buy fee
        assert body["win_rate"] == pytest.approx(1.0)
        assert body["avg_win"] > 0

    def test_hold_time_computed_from_fill_timestamps(self, strategy_with_history):
        sid, _ = strategy_with_history
        body = client.get(f"/strategies/{sid}/metrics").json()
        assert body["avg_hold_time_seconds"] == pytest.approx(1800.0, rel=1e-3)

    def test_empty_strategy_returns_zeros_not_error(self):
        """No fills at all must still be a clean 200."""
        session = get_session()
        try:
            strat = StrategyModel(key="metrics_empty", name="Empty", description="",
                                  starting_cash=100000.0, enabled=True)
            session.add(strat)
            session.commit()
            sid = strat.id
        finally:
            session.close()

        r = client.get(f"/strategies/{sid}/metrics")
        assert r.status_code == 200, r.text
        assert r.json()["trade_count"] == 0

    def test_unknown_id_returns_200_with_zeros(self):
        r = client.get("/strategies/99999999/metrics")
        assert r.status_code == 200, r.text
        assert r.json()["trade_count"] == 0


class TestMetricsByKey:
    def test_by_key_route_exists(self, strategy_with_history):
        _, skey = strategy_with_history
        r = client.get(f"/strategies/key/{skey}/metrics")
        assert r.status_code == 200, r.text

    def test_by_key_matches_by_id(self, strategy_with_history):
        sid, skey = strategy_with_history
        assert (
            client.get(f"/strategies/key/{skey}/metrics").json()
            == client.get(f"/strategies/{sid}/metrics").json()
        )

    def test_unknown_key_is_404(self):
        r = client.get("/strategies/key/no_such_strategy/metrics")
        assert r.status_code == 404


class TestJsonSafety:
    def test_no_infinity_or_nan_in_response(self, strategy_with_history):
        """profit_factor is legitimately inf with wins and no losses. Bare
        Infinity/NaN is invalid JSON and JSON.parse() rejects it, so the API
        must emit null instead — otherwise one value breaks the whole
        response client-side.
        """
        sid, _ = strategy_with_history
        raw = client.get(f"/strategies/{sid}/metrics").text
        assert "Infinity" not in raw
        assert "NaN" not in raw

        for key, value in client.get(f"/strategies/{sid}/metrics").json().items():
            if isinstance(value, float):
                assert math.isfinite(value), f"{key} is not finite"


class TestCancelOrderRoute:
    def test_cancel_unknown_order_is_404_not_500(self):
        """DELETE /orders/{id} referenced ENGINE without importing it, so it
        raised NameError -> 500 on every call instead of a clean 404."""
        r = client.delete("/orders/does-not-exist")
        assert r.status_code == 404, r.text
