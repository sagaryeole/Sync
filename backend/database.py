import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from models import Base, Asset, PriceTicker, Portfolio, TradeLog, Meta, Strategy, PortfolioAccount
import config
from settings import get_settings
from feeds.symbols import SYMBOLS

settings = get_settings()
logger = logging.getLogger("db")

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enables SQLite Write-Ahead Logging (WAL) and timeout defaults to prevent locked DBs."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(bind=engine)

CURRENT_SCHEMA_VERSION = "2"

def init_db():
    session = SessionLocal()
    try:
        # Check if meta table and correct schema version exist
        schema_ok = False
        try:
            meta_ver = session.query(Meta).filter_by(key="schema_version").first()
            if meta_ver and meta_ver.value == CURRENT_SCHEMA_VERSION:
                schema_ok = True
        except Exception:
            # Meta table doesn't exist, which means fresh DB or old schema
            pass

        if not schema_ok:
            logger.warning("SCHEMA RESET: Dropping all tables and rebuilding database schema...")
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            
            # Record schema version
            session.add(Meta(key="schema_version", value=CURRENT_SCHEMA_VERSION))
            session.commit()

        # Seed assets if not present
        display_order = 0
        for symbol, cfg in SYMBOLS.items():
            if not session.query(Asset).filter_by(symbol=symbol).first():
                session.add(Asset(
                    symbol=symbol,
                    name=cfg["name"],
                    display_order=display_order,
                    is_active=True
                ))
                display_order += 1
        session.commit()

        # Seed strategies
        strategies_to_seed = [
            {"key": "manual", "name": "Manual Portfolio", "description": "User manual trades and execution"},
            {"key": "sma_crossover", "name": "SMA Crossover", "description": "SMA(9) vs SMA(21) Golden/Death Cross"},
            {"key": "rsi_reversion", "name": "RSI Reversion", "description": "RSI(14) Oversold reversion strategy"},
            {"key": "momentum_breakout", "name": "Momentum Breakout", "description": "Donchian channel breakout strategy"}
        ]
        
        for strat in strategies_to_seed:
            strategy_row = session.query(Strategy).filter_by(key=strat["key"]).first()
            if not strategy_row:
                strategy_row = Strategy(
                    key=strat["key"],
                    name=strat["name"],
                    description=strat["description"],
                    starting_cash=settings.starting_cash,
                    enabled=True
                )
                session.add(strategy_row)
                session.flush()
            
            # Seed matching portfolio account
            portfolio_acc = session.query(PortfolioAccount).filter_by(strategy_id=strategy_row.id).first()
            if not portfolio_acc:
                session.add(PortfolioAccount(
                    strategy_id=strategy_row.id,
                    cash=settings.starting_cash,
                    realized_pnl=0.0,
                    fees_paid=0.0,
                    peak_equity=settings.starting_cash
                ))
        session.commit()

        # --- Legacy Seeding for Compatibility ---
        usd_portfolio = session.query(Portfolio).filter_by(symbol="USD").first()
        if not usd_portfolio:
            session.add(Portfolio(symbol="USD", balance=1000.0, quantity=0.0, cost_basis=0.0))
        
        for asset in config.ASSETS:
            coin_portfolio = session.query(Portfolio).filter_by(symbol=asset["symbol"]).first()
            if not coin_portfolio:
                session.add(Portfolio(symbol=asset["symbol"], balance=0.0, quantity=0.0, cost_basis=0.0))
        session.commit()

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        session.rollback()
        raise e
    finally:
        session.close()

def get_session():
    return SessionLocal()

def close_db():
    engine.dispose()
