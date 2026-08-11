import secrets
from settings import get_settings
from feeds.symbols import SYMBOLS

settings = get_settings()

SECRET_KEY = secrets.token_hex(16)
FRONTEND_URL = "http://localhost:5173"
CORS_ORIGINS = settings.cors_origins
SCHEDULER_INTERVAL = settings.strategy_interval_seconds
DATABASE_URL = settings.database_url
BOT_PERIOD = 5
PRICE_RETENTION_HOURS = 24

# Build ASSETS for compatibility with older code/tests
ASSETS = []
for sym in settings.symbols:
    if sym in SYMBOLS:
        ASSETS.append({"symbol": sym, "name": SYMBOLS[sym]["name"]})
