"""V2 — Feed recorder: dump raw ticks to JSONL for deterministic replay.

Records every accepted tick to a JSONL file so they can be replayed through
SyntheticFeed for deterministic integration tests against real market data.

Usage:
    recorder = FeedRecorder("recordings/btc_2024-01-15.jsonl")
    recorder.record(tick)

    # Later, in tests:
    feed = ReplayFeed("recordings/btc_2024-01-15.jsonl")
    async for tick in feed.stream(["BTC"]):
        ...
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, AsyncIterator, Optional

from feeds.base import MarketFeed, Tick

logger = logging.getLogger("feed.recorder")


class FeedRecorder:
    """Appends ticks to a JSONL file. One JSON object per line."""

    def __init__(self, path: str):
        self.path = path
        self._file = None
        self._count = 0

    def open(self) -> None:
        """Open the file for appending. Creates parent dirs."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")
        logger.info("Feed recorder opened: %s", self.path)

    def record(self, tick: Tick) -> None:
        """Append a tick as one JSON line. Silently skips if not open."""
        if self._file is None:
            return
        try:
            line = json.dumps({
                "symbol": tick.symbol,
                "price": tick.price,
                "ts": tick.ts.isoformat(),
                "source": tick.source,
                "bid": tick.bid,
                "ask": tick.ask,
                "volume_24h": tick.volume_24h,
                "change_24h_pct": tick.change_24h_pct,
                "seq": tick.seq,
            })
            self._file.write(line + "\n")
            self._file.flush()
            self._count += 1
        except Exception as e:
            logger.error("Error recording tick: %s", e)

    def close(self) -> None:
        """Close the file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None
            logger.info("Feed recorder closed: %s (%d ticks recorded)", self.path, self._count)

    @property
    def count(self) -> int:
        return self._count


class ReplayFeed(MarketFeed):
    """Replays ticks from a JSONL recording. For deterministic tests only."""

    def __init__(self, path: str, loop: bool = False, speed: float = 1.0):
        self.path = path
        self.loop = loop
        self.speed = speed  # playback speed multiplier (1.0 = real-time, 0 = instant)

    @property
    def name(self) -> str:
        return "replay"

    async def stream(self, symbols: List[str]) -> AsyncIterator[Tick]:
        import asyncio

        symbol_set = set(symbols)
        while True:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if obj.get("symbol") not in symbol_set:
                            continue

                        ts_str = obj.get("ts")
                        ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)

                        tick = Tick(
                            symbol=obj["symbol"],
                            price=obj["price"],
                            ts=ts,
                            source=obj.get("source", "replay"),
                            bid=obj.get("bid"),
                            ask=obj.get("ask"),
                            volume_24h=obj.get("volume_24h"),
                            change_24h_pct=obj.get("change_24h_pct"),
                            seq=obj.get("seq"),
                        )
                        yield tick

                        # Optional real-time pacing
                        if self.speed > 0:
                            await asyncio.sleep(1.0 / self.speed)
            except FileNotFoundError:
                logger.warning("Replay file not found: %s", self.path)
                return

            if not self.loop:
                return

    async def healthy(self) -> bool:
        return os.path.exists(self.path)
