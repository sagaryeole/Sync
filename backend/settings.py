from functools import lru_cache
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CTA_",
        extra="ignore"
    )

    # General / DB
    database_url: str = "sqlite:///./crypto.db"
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:3355",
        "http://localhost:3356",
        "http://localhost:14567",
    ]
    symbols: List[str] = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK"]

    # Feeds
    feed_providers: List[str] = ["coinbase", "binance", "synthetic"]
    feed_stale_seconds: int = 20
    feed_reconnect_base_seconds: float = 1.0
    feed_reconnect_max_seconds: float = 30.0
    feed_failback_seconds: int = 120
    backfill_candles: int = 300
    max_tick_move_pct: float = 0.10  # H4: reject single-tick moves > 10% unless confirmed
    confirm_ticks: int = 2  # H4: consecutive ticks needed to adopt a large move
    stop_pause_after_switch_seconds: int = 10  # H4: pause SL/TP eval after provider switch
    feed_record_path: Optional[str] = None  # V2: path to record ticks as JSONL (None = disabled)

    # Cadence
    broadcast_hz: float = 4.0
    candle_flush_seconds: int = 5
    engine_tick_seconds: int = 1
    strategy_interval_seconds: int = 15
    equity_snapshot_seconds: int = 30

    # Money
    starting_cash: float = 100000.0
    taker_fee_bps: float = 10.0  # 0.10%
    maker_fee_bps: float = 4.0   # 0.04%
    slippage_bps: float = 1.5    # 0.015%
    impact_notional: float = 50000.0
    min_notional: float = 10.0

    # Risk
    max_open_positions: int = 4
    max_position_pct: float = 0.20
    risk_per_trade_pct: float = 0.02
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    max_drawdown_pct: float = 0.25

    # Retention
    candle_retention_days: int = 7
    equity_retention_hours: int = 48

    @field_validator("symbols", "feed_providers", "cors_origins", mode="before")
    @classmethod
    def split_commas(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

@lru_cache()
def get_settings() -> Settings:
    return Settings()
