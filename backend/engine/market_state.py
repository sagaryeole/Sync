import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple
from feeds.base import Tick
from models import Candle
from database import SessionLocal

logger = logging.getLogger("engine.market_state")

def bucket_time(ts: datetime) -> datetime:
    """Bucket a timestamp to the floor minute (e.g. 10:15:34 -> 10:15:00)."""
    return ts.replace(second=0, microsecond=0)
class MarketState:
    def __init__(self):
        self.lock = threading.RLock()
        self.last_ticks: Dict[str, Tick] = {}
        self.tick_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=600))
        self.open_candles: Dict[str, Dict] = {}  # symbol -> dict representation of active candle
        self.closed_candles_queue: List[Candle] = []
        self.dirty_symbols: Set[str] = set()

    def last(self, symbol: str) -> Optional[float]:
        with self.lock:
            tick = self.last_ticks.get(symbol)
            return tick.price if tick else None

    def last_tick(self, symbol: str) -> Optional[Tick]:
        with self.lock:
            return self.last_ticks.get(symbol)

    def snapshot(self) -> Dict[str, float]:
        with self.lock:
            return {sym: tick.price for sym, tick in self.last_ticks.items()}

    def age_seconds(self, symbol: str) -> float:
        with self.lock:
            tick = self.last_ticks.get(symbol)
            if not tick:
                return 999999.0
            return (datetime.now(timezone.utc) - tick.ts).total_seconds()

    def recent_ticks(self, symbol: str, n: int = 100) -> List[Tick]:
        with self.lock:
            history = self.tick_history[symbol]
            return list(history)[-n:]

    def open_candle(self, symbol: str) -> Optional[Dict]:
        with self.lock:
            return self.open_candles.get(symbol)

    def take_dirty(self) -> Set[str]:
        with self.lock:
            dirty = set(self.dirty_symbols)
            self.dirty_symbols.clear()
            return dirty

    def drain_closed_candles(self) -> List[Candle]:
        with self.lock:
            candles = list(self.closed_candles_queue)
            self.closed_candles_queue.clear()
            return candles

    def close_all_candles(self) -> List[Candle]:
        """Force close all open in-progress candles (e.g. on provider switch or shutdown)."""
        with self.lock:
            closed = []
            for symbol, candle_dict in list(self.open_candles.items()):
                candle_obj = Candle(
                    symbol=symbol,
                    interval="1m",
                    open_time=candle_dict["open_time"],
                    open=candle_dict["open"],
                    high=candle_dict["high"],
                    low=candle_dict["low"],
                    close=candle_dict["close"],
                    volume=candle_dict["volume"],
                    trades=candle_dict["trades"],
                    source=candle_dict["source"]
                )
                self.closed_candles_queue.append(candle_obj)
                closed.append(candle_obj)
                logger.info("Forced close open candle for %s on provider change/shutdown", symbol)
            self.open_candles.clear()
            return closed

    def on_tick_batch(self, raw_ticks: List[Dict]) -> List[Optional[Candle]]:
        """Convenience wrapper: build Tick objects from plain dicts and feed them
        through on_tick(). Each dict needs at least symbol/price; bid/ask/source/ts
        default sensibly. Mainly useful for tests and REPL-style seeding.
        """
        results = []
        for raw in raw_ticks:
            tick = Tick(
                symbol=raw["symbol"],
                price=raw["price"],
                ts=raw.get("ts") or datetime.now(timezone.utc),
                source=raw.get("source", "test"),
                bid=raw.get("bid"),
                ask=raw.get("ask"),
                volume_24h=raw.get("volume_24h"),
                change_24h_pct=raw.get("change_24h_pct"),
                seq=raw.get("seq"),
            )
            results.append(self.on_tick(tick))
        return results

    def on_tick(self, tick: Tick) -> Optional[Candle]:
        """Processes an incoming tick: updates tick cache, aggregates OHLC, rolls candle on rollover.

        H11: Candle bucketing uses server receive time, not exchange timestamp,
        to prevent a wrong/spoofed exchange clock from placing candles in the future
        or reordering bars.
        """
        with self.lock:
            symbol = tick.symbol
            self.last_ticks[symbol] = tick
            self.tick_history[symbol].append(tick)
            self.dirty_symbols.add(symbol)
            
            closed_candle: Optional[Candle] = None
            
            # H11: Aggregate candles (1m buckets) on SERVER RECEIVE TIME
            receive_time = datetime.now(timezone.utc)
            bucket_ts = bucket_time(receive_time)
            open_c = self.open_candles.get(symbol)
            
            if open_c is None:
                # Start new candle
                self.open_candles[symbol] = {
                    "open_time": bucket_ts,
                    "open": tick.price,
                    "high": tick.price,
                    "low": tick.price,
                    "close": tick.price,
                    "volume": 0.0,
                    "trades": 1,
                    "source": tick.source
                }
            elif bucket_ts > open_c["open_time"]:
                # Roller rollover: close old, start new
                closed_candle = Candle(
                    symbol=symbol,
                    interval="1m",
                    open_time=open_c["open_time"],
                    open=open_c["open"],
                    high=open_c["high"],
                    low=open_c["low"],
                    close=open_c["close"],
                    volume=open_c["volume"],
                    trades=open_c["trades"],
                    source=open_c["source"]
                )
                self.closed_candles_queue.append(closed_candle)
                
                # Start new
                self.open_candles[symbol] = {
                    "open_time": bucket_ts,
                    "open": tick.price,
                    "high": tick.price,
                    "low": tick.price,
                    "close": tick.price,
                    "volume": 0.0,
                    "trades": 1,
                    "source": tick.source
                }
            else:
                # Update current candle
                open_c["high"] = max(open_c["high"], tick.price)
                open_c["low"] = min(open_c["low"], tick.price)
                open_c["close"] = tick.price
                open_c["trades"] += 1
                
            return closed_candle

    def warm_from_db(self) -> None:
        """Warms the market state last tick price and aggregates from DB on startup."""
        session = SessionLocal()
        try:
            from settings import get_settings
            settings = get_settings()
            
            with self.lock:
                for sym in settings.symbols:
                    # Fetch latest closed candle
                    last_c = session.query(Candle).filter_by(
                        symbol=sym, interval="1m"
                    ).order_by(Candle.open_time.desc()).first()
                    
                    if last_c:
                        # Construct a mock last tick to seed the engine
                        mock_tick = Tick(
                            symbol=sym,
                            price=float(last_c.close),
                            ts=last_c.open_time + timedelta(minutes=1),
                            source=last_c.source
                        )
                        self.last_ticks[sym] = mock_tick
                        # Warm tick history with a few synthetic ticks so strategies
                        # that use recent_ticks() have data on startup.
                        for i in range(10):
                            hist_tick = Tick(
                                symbol=sym,
                                price=float(last_c.close),
                                ts=last_c.open_time - timedelta(minutes=10-i),
                                source=last_c.source
                            )
                            self.tick_history[sym].append(hist_tick)
                        logger.info("Warmed last tick for %s from DB: %f", sym, mock_tick.price)
        except Exception as e:
            logger.error("Error warming MarketState from DB: %s", e)
        finally:
            session.close()

# Module Singleton
MARKET = MarketState()
