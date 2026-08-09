import secrets
from functools import lru_cache
from typing import Final

# Secret key for FastAPI docs / CORS (development only)
SECRET_KEY: Final[str] = secrets.token_hex(16)

# Frontend origin
FRONTEND_URL: Final[str] = "http://localhost:5173"

# CORS allowed origins (add all possible Vite dev server ports)
CORS_ORIGINS: Final[list[str]] = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:3355",
    "http://localhost:3356",
    "http://localhost:14567",
]

# Scheduler interval in seconds
SCHEDULER_INTERVAL: Final[int] = 60

# Database URL
DATABASE_URL: Final[str] = "sqlite:///./crypto.db"

# Asset configuration (mock tickers)
ASSETS: Final[list[dict]] = [
    {"symbol": "BTC", "name": "Bitcoin"},
    {"symbol": "ETH", "name": "Ethereum"},
    {"symbol": "SOL", "name": "Solana"}
]

# Bot parameters (simple MA crossover)
BOT_PERIOD: Final[int] = 5  # minutes to compute moving average

# Price retention: prune records older than this many hours
PRICE_RETENTION_HOURS: Final[int] = 24
