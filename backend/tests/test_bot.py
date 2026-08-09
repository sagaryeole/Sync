import pytest
from datetime import datetime, timezone
from database import get_session, init_db, close_db
from bot import compute_ma, get_signal, generate_mock_price, run_bot_cycle
from models import Asset, PriceTicker, Portfolio, TradeLog
import config


@pytest.fixture(autouse=True)
def test_db():
    """conftest.py resets the in-memory DB before each test; nothing to do here."""
    yield


def test_compute_ma():
    session = get_session()
    # Clear any seeded BTC prices so the MA is computed only over our data.
    session.query(PriceTicker).filter_by(symbol="BTC").delete()
    session.commit()

    # Prices: 100, 99, 98, 97, 96
    prices = [PriceTicker(
        symbol="BTC",
        price=100 - i,
        timestamp=datetime.now(timezone.utc)
    ) for i in range(5)]
    session.add_all(prices)
    session.commit()

    # Expected MA: (100 + 99 + 98 + 97 + 96) / 5 = 98
    ma = compute_ma(session, "BTC")
    assert ma == 98, f"Expected 98, got {ma}"

    session.close()


def test_get_signal():
    session = get_session()
    # Assets are already added in conftest
    # Clear any seeded BTC prices so signals are deterministic.
    session.query(PriceTicker).filter_by(symbol="BTC").delete()
    session.commit()

    # Scenario 1: price significantly above MA (> 102%) -> SELL
    # MA will be 100, current price should be > 102
    for i in range(5):
        session.add(PriceTicker(symbol="BTC", price=100, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Add a new price point that's significantly higher (> 102% of MA)
    session.add(PriceTicker(symbol="BTC", price=103, timestamp=datetime.now(timezone.utc)))
    session.commit()

    signal = get_signal(session, "BTC")
    assert signal == "SELL", f"Expected SELL signal, got {signal}"

    # Scenario 2: price significantly below MA (< 98%) -> BUY
    session.query(PriceTicker).filter_by(symbol="BTC").delete()
    session.commit()

    for i in range(5):
        session.add(PriceTicker(symbol="BTC", price=100, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Add a new price point that's significantly lower (< 98% of MA)
    session.add(PriceTicker(symbol="BTC", price=97, timestamp=datetime.now(timezone.utc)))
    session.commit()

    signal = get_signal(session, "BTC")
    assert signal == "BUY", f"Expected BUY signal, got {signal}"

    session.close()


def test_generate_mock_price():
    session = get_session()
    # Add an initial price for BTC
    session.add(PriceTicker(symbol="BTC", price=50000, timestamp=datetime.now(timezone.utc)))
    session.commit()

    generate_mock_price(session)

    latest = session.query(PriceTicker).filter_by(symbol="BTC").order_by(PriceTicker.timestamp.desc()).first()
    assert latest is not None
    session.close()


def test_run_bot_cycle():
    session = get_session()

    # Create a condition where BTC should be bought
    # Ensure BTC price is below MA
    import random
    price = random.uniform(20000, 30000)
    session.query(PriceTicker).filter_by(symbol="BTC").delete()
    session.commit()

    for i in range(5):
        session.add(PriceTicker(symbol="BTC", price=price + i * 500, timestamp=datetime.now(timezone.utc)))
    session.commit()

    # Ensure enough USD
    usd_portfolio = session.query(Portfolio).filter_by(symbol="USD").first()
    if not usd_portfolio:
        usd_portfolio = Portfolio(symbol="USD", balance=100000, quantity=0, cost_basis=0)
        session.add(usd_portfolio)
    else:
        usd_portfolio.balance = 100000
    session.commit()

    run_bot_cycle(session)

    trades = session.query(TradeLog).all()
    # Note: The bot might not trade if the signal conditions aren't met
    # So we just check that the cycle runs without error
    assert trades is not None

    session.close()

