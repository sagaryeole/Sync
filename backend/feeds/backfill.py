import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List
import httpx
from sqlalchemy.dialects.sqlite import insert
from models import Candle
from database import SessionLocal
from feeds.symbols import to_provider
from settings import get_settings

logger = logging.getLogger("feed.backfill")
settings = get_settings()

async def backfill_symbol(session, symbol: str, limit: int = 300) -> bool:
    """Backfills 1-minute candles for a single symbol from Coinbase, falling back to Binance."""
    coinbase_pid = to_provider(symbol, "coinbase")
    binance_sym = to_provider(symbol, "binance")

    # 1. Try Coinbase REST candles
    if coinbase_pid:
        url = f"https://api.exchange.coinbase.com/products/{coinbase_pid}/candles?granularity=60"
        try:
            logger.info("Attempting Coinbase candle backfill for %s (url: %s)...", symbol, url)
            headers = {"User-Agent": "CryptoTradeApp/1.0"}
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, timeout=10.0)
                if r.status_code == 429:  # H13: honor rate limit
                    retry_after = int(r.headers.get("Retry-After", "60"))
                    logger.warning("Coinbase rate-limited (429). Retrying after %ds.", retry_after)
                    await asyncio.sleep(retry_after)
                    r = await client.get(url, headers=headers, timeout=10.0)
                if r.status_code == 200:
                    rows = r.json()
                    # Rows are: [time, low, high, open, close, volume]
                    # Coinbase returns newest-first
                    count = 0
                    for row in rows[:limit]:
                        ts = datetime.fromtimestamp(row[0], timezone.utc)
                        stmt = insert(Candle).values(
                            symbol=symbol,
                            interval="1m",
                            open_time=ts,
                            low=float(row[1]),
                            high=float(row[2]),
                            open=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                            trades=0,
                            source="coinbase"
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["symbol", "interval", "open_time"],
                            set_={
                                "open": stmt.excluded.open,
                                "high": stmt.excluded.high,
                                "low": stmt.excluded.low,
                                "close": stmt.excluded.close,
                                "volume": stmt.excluded.volume,
                                "source": stmt.excluded.source
                            }
                        )
                        session.execute(stmt)
                        count += 1
                    session.commit()
                    logger.info("Successfully backfilled %d candles for %s from Coinbase", count, symbol)
                    return True
                else:
                    logger.warning("Coinbase candle REST query failed for %s: Status %d", symbol, r.status_code)
        except Exception as e:
            logger.error("Error backfilling %s from Coinbase: %s", symbol, e)

    # 2. Try Binance REST candles fallback
    if binance_sym:
        url = f"https://api.binance.com/api/v3/klines?symbol={binance_sym}&interval=1m&limit={limit}"
        try:
            logger.info("Attempting Binance candle backfill for %s...", symbol)
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=10.0)
                if r.status_code == 429:  # H13: honor rate limit
                    retry_after = int(r.headers.get("Retry-After", "60"))
                    logger.warning("Binance rate-limited (429). Retrying after %ds.", retry_after)
                    await asyncio.sleep(retry_after)
                    r = await client.get(url, timeout=10.0)
                if r.status_code == 200:
                    rows = r.json()
                    count = 0
                    for row in rows:
                        ts = datetime.fromtimestamp(row[0] / 1000.0, timezone.utc)
                        stmt = insert(Candle).values(
                            symbol=symbol,
                            interval="1m",
                            open_time=ts,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                            trades=int(row[8]),
                            source="binance"
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["symbol", "interval", "open_time"],
                            set_={
                                "open": stmt.excluded.open,
                                "high": stmt.excluded.high,
                                "low": stmt.excluded.low,
                                "close": stmt.excluded.close,
                                "volume": stmt.excluded.volume,
                                "trades": stmt.excluded.trades,
                                "source": stmt.excluded.source
                            }
                        )
                        session.execute(stmt)
                        count += 1
                    session.commit()
                    logger.info("Successfully backfilled %d candles for %s from Binance", count, symbol)
                    return True
                else:
                    logger.warning("Binance candle REST query failed for %s: Status %d", symbol, r.status_code)
        except Exception as e:
            logger.error("Error backfilling %s from Binance: %s", symbol, e)

    return False

async def backfill_candles(symbols: List[str]) -> None:
    """Run candle backfill for all symbols on startup, honoring rate-limits and safety buffers."""
    session = SessionLocal()
    try:
        # Check if we recently updated candles to prevent API bans during hot-reloads
        newest = session.query(Candle).order_by(Candle.open_time.desc()).first()
        if newest:
            age = datetime.now(timezone.utc) - newest.open_time
            if age < timedelta(minutes=2):
                logger.info("Skipping candle backfill: newest candle is only %s old", age)
                return

        logger.info("Starting startup candle backfill for symbols: %s", symbols)
        for sym in symbols:
            # 250 ms stagger
            await asyncio.sleep(0.250)
            await backfill_symbol(session, sym, limit=settings.backfill_candles)

    except Exception as e:
        logger.error("Failed during candle backfill task: %s", e)
    finally:
        session.close()
