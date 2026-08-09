import pytest
from fastapi.testclient import TestClient
from main import app
from database import init_db, close_db, get_session
from models import Asset, PriceTicker, Portfolio, TradeLog
from datetime import datetime, timezone
import config

client = TestClient(app)


@pytest.fixture(autouse=True)
def test_db():
    """conftest.py resets the in-memory DB before each test; nothing to do here."""
    yield


def test_list_assets():
    r = client.get("/assets")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == len(config.ASSETS)
    assert data[0]["name"] == config.ASSETS[0]["name"]


def test_get_asset():
    r = client.get("/assets/BTC")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "BTC"
    assert data["name"] == "Bitcoin"


def test_get_asset_not_found():
    r = client.get("/assets/XZY")
    assert r.status_code == 404


def test_list_prices():
    r = client.get("/prices")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    # Check all assets
    symbols = set(p["symbol"] for p in data)
    assert symbols == set(a["symbol"] for a in config.ASSETS)


def test_list_prices_filtered():
    r = client.get("/prices?asset=BTC")
    assert r.status_code == 200
    data = r.json()
    assert all(p["symbol"] == "BTC" for p in data)


def test_list_prices_filtered_time():
    r = client.get("/prices?start=2025-01-01T00:00:00Z")
    assert r.status_code == 200
    data = r.json()
    assert all(p["timestamp"] >= "2025-01-01T00:00:00Z" for p in data)


def test_get_portfolio():
    r = client.get("/portfolio/BTC")
    # conftest creates portfolio entries for all assets, so BTC exists.
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "BTC"


def test_get_portfolio_not_found():
    r = client.get("/portfolio/XYZ")
    # XYZ matches the ^[A-Z]{3}$ regex, so it passes validation but no
    # portfolio entry exists -> 404.
    assert r.status_code == 404


def test_execute_trade_success():
    import random
    # Create a condition to trigger BUY signal
    session = get_session()

    # Add history
    for i in range(10):
        price = 10000 + i * 500 + random.uniform(-100, 100)
        session.add(PriceTicker(symbol="BTC", price=price, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Set BTC price low
    session.query(PriceTicker).filter_by(symbol="BTC").delete()
    session.add(PriceTicker(symbol="BTC", price=5000, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Ensure USD balance
    usd_portfolio = session.query(Portfolio).filter_by(symbol="USD").first()
    if not usd_portfolio:
        usd_portfolio = Portfolio(symbol="USD", balance=10000, quantity=0, cost_basis=0)
        session.add(usd_portfolio)
    else:
        usd_portfolio.balance = 10000
    session.commit()
    session.close()

    r = client.post("/trade", json={"type": "BUY", "symbol": "BTC", "quantity": 1})
    assert r.status_code == 201


def test_execute_trade_insufficient_balance():
    r = client.post("/trade", json={"type": "BUY", "symbol": "BTC", "quantity": 1000000})
    assert r.status_code == 400


def test_execute_trade_invalid_symbol():
    r = client.post("/trade", json={"type": "BUY", "symbol": "XYZ", "quantity": 1})
    assert r.status_code == 404


def test_execute_trade_invalid_type():
    r = client.post("/trade", json={"type": "INVALID", "symbol": "BTC", "quantity": 1})
    # Pydantic rejects the invalid type via the Field pattern -> 422 Unprocessable Entity
    assert r.status_code == 422


def test_get_bot_signals():
    r = client.get("/bot/signals")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"BTC", "ETH", "SOL"}
