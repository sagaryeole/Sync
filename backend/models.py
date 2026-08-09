from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), unique=True, nullable=False)
    name = Column(String(50), nullable=False)


class PriceTicker(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    price = Column(Numeric, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Composite index for the common query pattern: filter by symbol, order by timestamp desc
    __table_args__ = (
        Index("ix_prices_symbol_timestamp", "symbol", "timestamp"),
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    symbol = Column(String(10), primary_key=True)
    balance = Column(Numeric, default=0)
    quantity = Column(Numeric, default=0)
    cost_basis = Column(Numeric, default=0)  # average cost per coin


class TradeLog(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(10), nullable=False)  # BUY or SELL
    symbol = Column(String(10), nullable=False)
    quantity = Column(Numeric, nullable=False)
    price = Column(Numeric, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
