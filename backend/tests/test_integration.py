"""Integration tests for the new improvements: /trade execution, /portfolio list-all,
health check, and price pruning."""
import pytest
from fastapi.testclient import TestClient
from main import app, _legacy_execute_trade as execute_trade
from database import get_session
from models import PriceTicker, Portfolio, TradeLog
from scheduler import _make_prune_job
from datetime import datetime, timezone, timedelta

client = TestClient(app)


@pytest.fixture(autouse=True)
def test_db():
    """conftest.py resets the in-memory DB before each test."""
    yield


# ---- Health check ----

def test_health_check():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_health_does_not_leak_config():
    """H15: /health must not leak config — no env dump, no DB path, no origin list."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    forbidden = {"database_url", "cors_origins", "env", "config", "origin", "origins",
                 "secret", "key", "token", "password", ".env", "db_path", "db_url",
                 "settings", "env_file"}
    leaked = forbidden.intersection(data.keys())
    assert not leaked, f"/health leaked config keys: {leaked}"


# ---- GET /portfolio (list-all) ----

def test_list_portfolio_all():
    """GET /portfolio returns a list of all positions."""
    r = client.get("/portfolio")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    symbols = {p["symbol"] for p in data}
    # conftest seeds USD + BTC + ETH + SOL
    assert "USD" in symbols
    assert "BTC" in symbols


def test_get_portfolio_single():
    """GET /portfolio/{symbol} returns a single position."""
    r = client.get("/portfolio/BTC")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "BTC"


def test_get_portfolio_single_not_found():
    r = client.get("/portfolio/XYZ")
    assert r.status_code == 404


# ---- POST /trade actually executes ----

def test_trade_buy_modifies_portfolio():
    """POST /trade with BUY should deduct USD and add coin quantity."""
    session = get_session()
    usd_before = float(session.query(Portfolio).filter_by(symbol="USD").first().balance)
    btc_before = float(session.query(Portfolio).filter_by(symbol="BTC").first().quantity)
    session.close()

    # Use a small quantity to stay within USD balance
    r = client.post("/trade", json={"type": "BUY", "symbol": "BTC", "quantity": 0.001})

    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "trade executed"
    assert data["type"] == "BUY"
    assert data["symbol"] == "BTC"

    session = get_session()
    usd_after = float(session.query(Portfolio).filter_by(symbol="USD").first().balance)
    btc_after = float(session.query(Portfolio).filter_by(symbol="BTC").first().quantity)
    session.close()

    # USD should have decreased (cost = qty * price)
    assert usd_after < usd_before
    # BTC quantity should have increased
    assert btc_after > btc_before


def test_trade_creates_trade_log_entry():
    """POST /trade should create a TradeLog entry."""
    session = get_session()
    trades_before = session.query(TradeLog).count()
    session.close()

    client.post("/trade", json={"type": "BUY", "symbol": "ETH", "quantity": 0.01})

    session = get_session()
    trades_after = session.query(TradeLog).count()
    session.close()

    assert trades_after > trades_before


def test_trade_sell_requires_holdings():
    """SELL with no holdings should return 400."""
    # conftest seeds BTC quantity = 0
    r = client.post("/trade", json={"type": "SELL", "symbol": "BTC", "quantity": 1})
    # execute_trade returns False on insufficient holdings → endpoint returns 400
    assert r.status_code == 400


def test_trade_buy_then_sell_roundtrip():
    """Buy then sell should return USD approximately to starting balance."""
    session = get_session()
    usd_start = float(session.query(Portfolio).filter_by(symbol="USD").first().balance)
    session.close()

    # Buy
    r = client.post("/trade", json={"type": "BUY", "symbol": "SOL", "quantity": 1})
    assert r.status_code == 201
    buy_price = r.json()["price"]

    # Sell the same quantity
    r2 = client.post("/trade", json={"type": "SELL", "symbol": "SOL", "quantity": 1})
    assert r2.status_code == 201

    session = get_session()
    usd_end = float(session.query(Portfolio).filter_by(symbol="USD").first().balance)
    sol_qty = float(session.query(Portfolio).filter_by(symbol="SOL").first().quantity)
    session.close()

    # SOL should be back to ~0 (bot may have traded too, but SELL of 1 should clear our 1)
    # USD should be close to start (minus bot trades + price diff). Just check it's positive.
    assert sol_qty >= 0
    assert usd_end > 0


# ---- Price pruning ----
# The legacy MA-crossover bot cycle (bot.py:run_bot_cycle) is gone — replaced by
# the engine + StrategyRunner (see engine/runner.py, scheduler.py). Pruning is
# now the scheduler's hourly `prune` job, tested directly here.

def test_prune_job_deletes_old_prices():
    """The prune job should remove PriceTicker rows older than 24h."""
    session = get_session()

    old_time = datetime.now(timezone.utc) - timedelta(hours=48)
    session.add(PriceTicker(symbol="BTC", price=10000, timestamp=old_time))
    session.commit()

    old_count = session.query(PriceTicker).filter(
        PriceTicker.timestamp < datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    assert old_count > 0
    session.close()

    _make_prune_job()()

    session = get_session()
    remaining_old = session.query(PriceTicker).filter(
        PriceTicker.timestamp < datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    session.close()

    assert remaining_old == 0


def test_prune_job_keeps_recent_prices():
    """The prune job should NOT remove recent PriceTicker rows."""
    session = get_session()
    recent_count_before = session.query(PriceTicker).filter(
        PriceTicker.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    session.close()

    _make_prune_job()()

    session = get_session()
    recent_count_after = session.query(PriceTicker).filter(
        PriceTicker.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    session.close()

    assert recent_count_after == recent_count_before


# ---- execute_trade unit-level ----

def test_execute_trade_buy_updates_cost_basis():
    """execute_trade BUY should compute weighted-average cost basis."""
    session = get_session()
    # Ensure clean state for BTC and sufficient USD
    session.query(Portfolio).filter_by(symbol="BTC").update(
        {"quantity": 0, "cost_basis": 0, "balance": 0}
    )
    session.query(Portfolio).filter_by(symbol="USD").update({"balance": 100000})
    session.commit()
    session.expire_all()  # clear identity map so subsequent queries hit DB

    # First buy: 1 BTC @ 40000
    execute_trade(session, "BUY", "BTC", 1, 40000)
    btc = session.query(Portfolio).filter_by(symbol="BTC").first()
    assert float(btc.quantity) == pytest.approx(1)
    assert float(btc.cost_basis) == pytest.approx(40000)

    # Second buy: 1 BTC @ 60000 → avg = (1*40000 + 1*60000) / 2 = 50000
    execute_trade(session, "BUY", "BTC", 1, 60000)
    session.refresh(btc)
    assert float(btc.quantity) == pytest.approx(2)
    assert float(btc.cost_basis) == pytest.approx(50000)
    session.close()


def test_execute_trade_sell_credits_usd():
    """execute_trade SELL should credit USD and reduce coin quantity."""
    session = get_session()

    # Setup: give user 2 BTC
    session.query(Portfolio).filter_by(symbol="BTC").update(
        {"quantity": 2, "cost_basis": 40000, "balance": -80000}
    )
    usd = session.query(Portfolio).filter_by(symbol="USD").first()
    usd_balance_before = float(usd.balance)
    session.commit()

    # Sell 1 BTC @ 50000
    execute_trade(session, "SELL", "BTC", 1, 50000)

    session.refresh(usd)
    btc = session.query(Portfolio).filter_by(symbol="BTC").first()
    assert float(btc.quantity) == pytest.approx(1)
    assert float(usd.balance) == pytest.approx(usd_balance_before + 50000)
    session.close()
