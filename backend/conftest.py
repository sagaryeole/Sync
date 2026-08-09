import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Create in-memory engine for testing. StaticPool keeps a single connection
# alive so that all sessions (including those opened by the FastAPI startup
# event running in the TestClient thread) see the same in-memory database.
test_engine = create_engine(
    'sqlite:///:memory:',
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(scope="session", autouse=True)
def setup_test_engine():
    """Set up in-memory database engine for all tests."""
    from models import Base

    # Create all tables in the in-memory database
    Base.metadata.create_all(bind=test_engine)
    yield
    # Cleanup is automatic with in-memory DB


@pytest.fixture(autouse=True)
def reset_db():
    """Reset database before each test."""
    import database
    from models import Base, Asset, Portfolio
    import config

    # Drop all tables
    Base.metadata.drop_all(bind=test_engine)

    # Recreate all tables
    Base.metadata.create_all(bind=test_engine)

    # Replace the database module's engine and SessionLocal with test versions
    database.engine = test_engine
    database.SessionLocal = sessionmaker(bind=test_engine)

    # Initialize with assets and portfolios (but NOT prices, to avoid affecting tests)
    session = database.SessionLocal()
    for asset in config.ASSETS:
        if not session.query(Asset).filter_by(symbol=asset["symbol"]).first():
            session.add(Asset(symbol=asset["symbol"], name=asset["name"]))

    # Add portfolios
    session.add(Portfolio(symbol="USD", balance=1000, quantity=0, cost_basis=0))
    for asset in config.ASSETS:
        session.add(Portfolio(symbol=asset["symbol"], balance=0, quantity=0, cost_basis=0))

    # Seed a small price history so price-dependent endpoints (/prices, /trade)
    # have data to work with. The bot tests add their own prices as needed.
    from models import PriceTicker
    from datetime import datetime, timezone
    base_prices = {"BTC": 45000, "ETH": 2800, "SOL": 150}
    for asset in config.ASSETS:
        for i in range(10):
            session.add(PriceTicker(
                symbol=asset["symbol"],
                price=base_prices[asset["symbol"]],
                timestamp=datetime.now(timezone.utc)
            ))

    session.commit()
    session.close()

    yield
