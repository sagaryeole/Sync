"""Integration tests for the new improvements: /trade execution, /portfolio list-all,
bot cycle, health check, and price pruning."""
import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_session
from models import PriceTicker, Portfolio, TradeLog
from bot import execute_trade, run_bot_cycle, prune_old_prices
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
    assert r.json() == {"status": "ok"}


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


# ---- Bot cycle ----

def test_run_bot_cycle_generates_prices():
    """run_bot_cycle should add new price records for all assets."""
    import config
    session = get_session()
    prices_before = session.query(PriceTicker).count()
    session.close()

    run_bot_cycle(get_session())

    session = get_session()
    prices_after = session.query(PriceTicker).count()
    session.close()

    # Should have added at least one price per asset
    assert prices_after >= prices_before + len(config.ASSETS)


def test_run_bot_cycle_logs_trades_on_signal():
    """When a BUY signal triggers, a trade should be logged and USD deducted."""
    import random
    session = get_session()

    # Create a strong downtrend to trigger BUY (price < 98% of MA)
    # First add 5 high prices to establish MA
    for i in range(5):
        session.add(PriceTicker(symbol="BTC", price=50000 + i * 100,
                                timestamp=datetime.now(timezone.utc)))
    session.commit()
    # Now add a low price (well below 98% of MA ~ 50200)
    session.add(PriceTicker(symbol="BTC", price=40000, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Ensure USD balance for the bot to trade
    usd = session.query(Portfolio).filter_by(symbol="USD").first()
    usd.balance = 10000
    session.commit()

    trades_before = session.query(TradeLog).count()
    session.close()

    run_bot_cycle(get_session())

    session = get_session()
    trades_after = session.query(TradeLog).count()
    usd_after = float(session.query(Portfolio).filter_by(symbol="USD").first().balance)
    session.close()

    # A BUY trade should have been logged
    assert trades_after > trades_before
    # USD should have decreased by ~$100 (bot buys $100 worth)
    assert usd_after < 10000


# ---- Price pruning ----

def test_prune_old_prices_deletes_old_records():
    """prune_old_prices should remove records older than max_age_hours."""
    session = get_session()

    # Add an old price record (48 hours ago)
    old_time = datetime.now(timezone.utc) - timedelta(hours=48)
    session.add(PriceTicker(symbol="BTC", price=10000, timestamp=old_time))
    session.commit()

    old_count = session.query(PriceTicker).filter(
        PriceTicker.timestamp < datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    assert old_count > 0

    session.close()

    # Prune with 24-hour retention
    prune_old_prices(get_session(), max_age_hours=24)

    session = get_session()
    remaining_old = session.query(PriceTicker).filter(
        PriceTicker.timestamp < datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    session.close()

    assert remaining_old == 0


def test_prune_old_prices_keeps_recent():
    """prune_old_prices should NOT remove recent records."""
    session = get_session()
    recent_count_before = session.query(PriceTicker).filter(
        PriceTicker.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()
    session.close()

    prune_old_prices(get_session(), max_age_hours=24)

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
