"""Tests for POST /orders (api/strategies.py:create_order).

Regression coverage for a real bug found live: the endpoint returned
``fill.id`` on success, but ``engine.paper_broker.Fill`` has no ``id`` field
(the DB only assigns one later, asynchronously, once
``scheduler._flush_engine_state`` persists it) — so every successful manual
order through this endpoint raised an uncaught AttributeError and returned
500. Nothing in the existing suite drove this endpoint through TestClient,
so it shipped and stayed broken until it was hit on a live server.
"""
import pytest
from fastapi.testclient import TestClient

from main import app, ENGINE
from engine.market_state import MARKET
from feeds.base import Tick
from datetime import datetime, timezone

client = TestClient(app)

_TEST_STRATEGY_ID = 999001


@pytest.fixture
def registered_strategy():
    """Register a strategy directly on the live main.ENGINE, the way
    load_engine_from_db() would at real startup — TestClient(app) without a
    `with` block never runs the app's lifespan, so nothing is registered
    otherwise.
    """
    if ENGINE.get_account(_TEST_STRATEGY_ID) is None:
        ENGINE.register_strategy(_TEST_STRATEGY_ID, "test_orders_api", 100_000.0)
    account = ENGINE.get_account(_TEST_STRATEGY_ID)
    account.cash = 100_000.0
    account.realized_pnl = 0.0
    account.positions.clear()
    account.is_halted = False
    yield account


@pytest.fixture
def seeded_price():
    MARKET.on_tick(Tick(
        symbol="BTC", price=50_000.0, ts=datetime.now(timezone.utc),
        source="test", bid=49_995.0, ask=50_005.0,
    ))
    yield
    MARKET.last_ticks.pop("BTC", None)


class TestCreateOrderResponseShape:
    def test_successful_buy_does_not_500(self, registered_strategy, seeded_price):
        r = client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "BUY", "order_type": "MARKET", "quantity": 0.01,
        })
        assert r.status_code == 201, r.text

    def test_response_has_no_id_field(self, registered_strategy, seeded_price):
        """The exact bug: `id` doesn't exist on the in-memory Fill."""
        r = client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "BUY", "order_type": "MARKET", "quantity": 0.01,
        })
        assert r.status_code == 201, r.text
        assert "fill_id" not in r.json()
        assert "id" not in r.json()

    def test_response_includes_client_order_id(self, registered_strategy, seeded_price):
        r = client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "BUY", "order_type": "MARKET", "quantity": 0.01,
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "filled"
        assert body["client_order_id"]
        assert body["symbol"] == "BTC"
        assert body["side"] == "BUY"
        assert body["quantity"] == pytest.approx(0.01)
        assert body["price"] > 0
        assert body["fee"] >= 0

    def test_sell_response_shape_matches_buy(self, registered_strategy, seeded_price):
        client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "BUY", "order_type": "MARKET", "quantity": 0.01,
        })
        r = client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "SELL", "order_type": "MARKET", "quantity": 0.01,
        })
        assert r.status_code == 201, r.text
        assert r.json()["side"] == "SELL"

    def test_rejected_order_returns_400_not_500(self, registered_strategy, seeded_price):
        """INSUFFICIENT_POSITION etc. must stay a clean 400, not crash."""
        r = client.post("/orders", params={
            "strategy_id": _TEST_STRATEGY_ID, "symbol": "BTC",
            "side": "SELL", "order_type": "MARKET", "quantity": 999.0,
        })
        assert r.status_code == 400
        assert r.json()["detail"] == "INSUFFICIENT_POSITION"
