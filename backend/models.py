import datetime
from datetime import timezone
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Text, Index,
    ForeignKey, UniqueConstraint, Boolean, TypeDecorator
)
from sqlalchemy.orm import declarative_base, DeclarativeBase

Base = declarative_base()

class UtcDateTime(TypeDecorator):
    """Custom decorator to enforce UTC datetime objects and prevent naive datetime errors."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, str):
                # Try parsing if string (e.g. from JSON/Pydantic)
                try:
                    value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if value.tzinfo is None:
                raise ValueError("Naive datetime is not allowed in UtcDateTime columns")
            return value.astimezone(datetime.timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=datetime.timezone.utc)
            return value.astimezone(datetime.timezone.utc)
        return value


# --- New Schema Models ---

class Meta(Base):
    __tablename__ = "meta"
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Candle(Base):
    __tablename__ = "candles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    interval = Column(String(10), nullable=False, index=True)
    open_time = Column(UtcDateTime, nullable=False, index=True)
    open = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    high = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    low = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    close = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    volume = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    trades = Column(Integer, default=0)
    source = Column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", name="uq_candles_symbol_interval_time"),
        Index("ix_candles_sym_int_time_desc", "symbol", "interval", "open_time"),
    )


class Strategy(Base):
    __tablename__ = "strategies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, default=True, nullable=False)
    params_json = Column(Text, default="{}")
    starting_cash = Column(Numeric(20, 8, asdecimal=False), default=100000.0, nullable=False)
    created_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)


class PortfolioAccount(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), unique=True, nullable=False)
    cash = Column(Numeric(20, 8, asdecimal=False), default=100000.0, nullable=False)
    realized_pnl = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    fees_paid = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    peak_equity = Column(Numeric(20, 8, asdecimal=False), default=100000.0, nullable=False)
    is_halted = Column(Boolean, default=False, nullable=False)
    halt_reason = Column(String(200))
    updated_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol = Column(String(10), nullable=False)
    quantity = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    avg_entry_price = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    realized_pnl = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    stop_loss_price = Column(Numeric(20, 8, asdecimal=False))
    take_profit_price = Column(Numeric(20, 8, asdecimal=False))
    opened_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    updated_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("strategy_id", "symbol", name="uq_positions_strategy_symbol"),
    )


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_order_id = Column(String(50), unique=True, nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)  # BUY, SELL
    order_type = Column(String(10), nullable=False)  # MARKET, LIMIT, STOP
    quantity = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    limit_price = Column(Numeric(20, 8, asdecimal=False))
    stop_price = Column(Numeric(20, 8, asdecimal=False))
    time_in_force = Column(String(10), default="GTC", nullable=False)  # GTC, IOC
    status = Column(String(20), default="PENDING", nullable=False)  # PENDING, FILLED, CANCELLED, REJECTED
    filled_quantity = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    avg_fill_price = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    reason = Column(String(200))
    reject_reason = Column(String(200))
    created_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    updated_at = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)


class Fill(Base):
    __tablename__ = "fills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)  # BUY, SELL
    quantity = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    price = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    fee = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    realized_pnl = Column(Numeric(20, 8, asdecimal=False), default=0.0, nullable=False)
    mark_price = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    liquidity = Column(String(10), nullable=False)  # MAKER, TAKER
    ts = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    ts = Column(UtcDateTime, nullable=False, index=True)
    equity = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    cash = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    position_value = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    realized_pnl = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    unrealized_pnl = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    drawdown_pct = Column(Numeric(20, 8, asdecimal=False), nullable=False)


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)  # BUY, SELL, HOLD
    strength = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    price = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    indicators_json = Column(Text, default="{}")
    ts = Column(UtcDateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)


# --- Legacy Schema Models for Back-Compatibility ---

class PriceTicker(Base):
    __tablename__ = "prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    price = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_prices_symbol_timestamp", "symbol", "timestamp"),
    )


class Portfolio(Base):
    __tablename__ = "portfolios_legacy"
    symbol = Column(String(10), primary_key=True)
    balance = Column(Numeric(20, 8, asdecimal=False), default=0)
    quantity = Column(Numeric(20, 8, asdecimal=False), default=0)
    cost_basis = Column(Numeric(20, 8, asdecimal=False), default=0)


class TradeLog(Base):
    __tablename__ = "trades_legacy"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(10), nullable=False)
    symbol = Column(String(10), nullable=False)
    quantity = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    price = Column(Numeric(20, 8, asdecimal=False), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(UtcDateTime, nullable=False, default=lambda: datetime.datetime.now(timezone.utc), index=True)
    actor = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    target = Column(String(100), nullable=False)
    before = Column(Text)
    after = Column(Text)
