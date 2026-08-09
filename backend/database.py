from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from models import Base, Asset, PriceTicker, Portfolio, TradeLog
from datetime import datetime, timezone
import config

# NullPool: each SessionLocal() gets a fresh connection that is closed on
# session.close(). This avoids the "identity map is no longer valid" error
# that occurs when the bot's background thread commits writes while a
# FastAPI request thread is reading — shared pooled connections get their
# identity maps corrupted under SQLite's limited concurrency.
# check_same_thread=False lets SQLAlchemy connections cross thread boundaries
# (FastAPI runs sync endpoints in a threadpool; APScheduler runs in its own thread).
engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    # Insert assets if not present
    for asset in config.ASSETS:
        if not session.query(Asset).filter_by(symbol=asset["symbol"]).first():
            session.add(Asset(**asset))
    session.commit()
    
    # Generate mock price history for last 60 minutes for each asset
    base_prices = {"BTC": 45000, "ETH": 2800, "SOL": 150}
    volatility = {"BTC": 0.01, "ETH": 0.015, "SOL": 0.025}
    
    for asset in config.ASSETS:
        price = base_prices[asset["symbol"]]
        for i in range(60):  # 60 minutes of history
            session.add(PriceTicker(
                symbol=asset["symbol"],
                price=price,
                timestamp=datetime.now(timezone.utc).replace(minute=(datetime.now(timezone.utc).minute - i) % 60)
            ))
            # Random walk with volatility
            drift = (i - 29) * 0.05  # slight trend in the middle
            noise = volatility[asset["symbol"]] * (0.8 if drift < 0 else 1.2)
            price = price * (1 + drift * 0.1)
            price = price * (1 + (-1 if i % 2 == 0 else 1) * volatility[asset["symbol"]] * noise)
    session.commit()
    
    # Initialize portfolio with $1000 if not already present
    usd_portfolio = session.query(Portfolio).filter_by(symbol="USD").first()
    if not usd_portfolio:
        session.add(Portfolio(symbol="USD", balance=1000, quantity=0, cost_basis=0))
    
    # Create portfolio entries for all coin assets
    for asset in config.ASSETS:
        coin_portfolio = session.query(Portfolio).filter_by(symbol=asset["symbol"]).first()
        if not coin_portfolio:
            session.add(Portfolio(symbol=asset["symbol"], balance=0, quantity=0, cost_basis=0))
    session.commit()
    session.close()


def get_session():
    return SessionLocal()


def close_db():
    """Dispose the engine and release all pooled connections."""
    engine.dispose()
