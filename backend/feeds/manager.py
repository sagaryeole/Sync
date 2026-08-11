import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional, Callable, Awaitable
from feeds.base import MarketFeed, Tick
from feeds.coinbase import CoinbaseFeed
from feeds.binance import BinanceFeed
from feeds.synthetic import SyntheticFeed
from feeds.validation import validate_tick, TickValidationError
from feeds.recorder import FeedRecorder
from settings import get_settings

logger = logging.getLogger("feed.manager")
settings = get_settings()

class FeedManager:
    def __init__(self):
        self.providers: Dict[str, MarketFeed] = {
            "coinbase": CoinbaseFeed(),
            "binance": BinanceFeed(),
            "synthetic": SyntheticFeed()
        }
        self.active_provider_name: Optional[str] = None
        self.active_task: Optional[asyncio.Task] = None
        self.last_tick_time: Optional[datetime] = None
        self.reconnect_count = 0
        self.status_since = datetime.now(timezone.utc)
        self.is_running = False
        
        # H1/H4 validation state
        self.last_accepted_prices: Dict[str, float] = {}
        self.pending_confirmations: Dict[str, int] = {}
        self.rejected_count = 0
        self.last_switch_time: Optional[datetime] = None  # H4: for stop-pause-after-switch

        # V2: optional feed recorder
        self.recorder: Optional[FeedRecorder] = None
        if settings.feed_record_path:
            self.recorder = FeedRecorder(settings.feed_record_path)
            self.recorder.open()
        
        # Callbacks
        self.on_tick_cb: Optional[Callable[[Tick], None]] = None
        self.on_status_cb: Optional[Callable[[dict], None]] = None
        self.on_provider_change_cb: Optional[Callable[[str], None]] = None

    def get_status(self) -> dict:
        """Returns the current status of the feed connection."""
        now = datetime.now(timezone.utc)
        age_ms = None
        if self.last_tick_time:
            age_ms = int((now - self.last_tick_time).total_seconds() * 1000)

        # Mode: LIVE (coinbase), DEGRADED (binance), SIM (synthetic)
        mode = "LIVE"
        if self.active_provider_name == "binance":
            mode = "DEGRADED"
        elif self.active_provider_name == "synthetic":
            mode = "SIM"

        status_str = "CONNECTED" if self.is_running and age_ms is not None and age_ms < (settings.feed_stale_seconds * 1000) else "DISCONNECTED"
        if self.is_running and status_str == "CONNECTED" and self.active_provider_name == "binance":
            status_str = "DEGRADED"

        return {
            "status": status_str,
            "provider": self.active_provider_name or "none",
            "mode": mode,
            "since": self.status_since.isoformat(),
            "last_tick_age_ms": age_ms,
            "reconnects": self.reconnect_count,
            "rejected_ticks": self.rejected_count
        }

    async def start(
        self,
        symbols: List[str],
        on_tick: Callable[[Tick], None],
        on_status: Callable[[dict], None],
        on_provider_change: Callable[[str], None]
    ):
        """Starts the feed manager loops (main stream, watchdog, and failback check)."""
        self.is_running = True
        self.on_tick_cb = on_tick
        self.on_status_cb = on_status
        self.on_provider_change_cb = on_provider_change
        
        self.active_provider_name = settings.feed_providers[0]
        self.status_since = datetime.now(timezone.utc)
        
        # Start loops
        asyncio.create_task(self._watchdog_loop())
        asyncio.create_task(self._failback_loop(symbols))
        asyncio.create_task(self._stream_loop(symbols))

    async def _stream_loop(self, symbols: List[str]):
        attempt = 0
        while self.is_running:
            provider = self.providers.get(self.active_provider_name)
            if not provider:
                logger.error("Provider %s not found in registry", self.active_provider_name)
                await asyncio.sleep(5)
                continue

            logger.info("Starting feed stream with provider: %s", self.active_provider_name)
            self._notify_status()
            
            try:
                # Stream ticks
                async for tick in provider.stream(symbols):
                    if not self.is_running:
                        break
                    
                    # H1/H4: validate every tick before it reaches MarketState
                    try:
                        validate_tick(
                            tick,
                            self.last_accepted_prices,
                            self.pending_confirmations,
                        )
                    except TickValidationError as e:
                        self.rejected_count += 1
                        logger.warning("Tick rejected: %s", e)
                        continue
                    
                    self.last_tick_time = datetime.now(timezone.utc)
                    self.last_accepted_prices[tick.symbol] = tick.price
                    attempt = 0  # reset reconnect attempts on successful tick

                    # V2: record the accepted tick for deterministic replay
                    if self.recorder:
                        self.recorder.record(tick)

                    if self.on_tick_cb:
                        self.on_tick_cb(tick)

            except asyncio.CancelledError:
                logger.info("Feed stream task for %s was cancelled.", self.active_provider_name)
                break
            except Exception as e:
                logger.error("Error in feed stream loop for %s: %s", self.active_provider_name, e)
                
            # If we exited the stream abnormally, reconnect/failover
            if self.is_running:
                self.reconnect_count += 1
                attempt += 1
                
                # Check if we should fail over after 3 failed attempts
                if attempt >= 3:
                    logger.warning("Failed to reconnect to %s after 3 attempts. Failing over...", self.active_provider_name)
                    self._failover()
                    attempt = 0
                else:
                    # Exponential backoff with jitter
                    base = settings.feed_reconnect_base_seconds
                    cap = settings.feed_reconnect_max_seconds
                    delay = min(cap, base * (2 ** attempt)) * random.uniform(0.5, 1.5)
                    logger.info("Reconnecting to %s in %.2fs (attempt %d)...", self.active_provider_name, delay, attempt)
                    self._notify_status()
                    await asyncio.sleep(delay)

    def _failover(self):
        """Rotate to the next provider in the settings list."""
        providers_list = settings.feed_providers
        try:
            curr_idx = providers_list.index(self.active_provider_name)
            next_idx = (curr_idx + 1) % len(providers_list)
        except ValueError:
            next_idx = 0
            
        next_provider = providers_list[next_idx]
        self._switch_provider(next_provider)

    def _switch_provider(self, new_provider: str):
        """Switch to a new provider: notify callbacks and trigger fresh candle aggregates."""
        if self.active_provider_name == new_provider:
            return

        logger.warning("SWITCHING FEED PROVIDER: %s -> %s", self.active_provider_name, new_provider)
        self.active_provider_name = new_provider
        self.status_since = datetime.now(timezone.utc)
        self.last_switch_time = datetime.now(timezone.utc)
        self.last_tick_time = None
        # Reset validation state on provider switch — new provider may have different price basis
        self.pending_confirmations.clear()
        
        if self.on_provider_change_cb:
            self.on_provider_change_cb(new_provider)
            
        self._notify_status()

    async def _watchdog_loop(self):
        """Watchdog checks if ticks have stalled and triggers failover."""
        while self.is_running:
            await asyncio.sleep(2)
            
            # Watchdog only applies if we aren't already on synthetic (since synthetic is offline fallback)
            if self.active_provider_name != "synthetic" and self.last_tick_time:
                now = datetime.now(timezone.utc)
                age = (now - self.last_tick_time).total_seconds()
                
                if age > settings.feed_stale_seconds:
                    logger.warning(
                        "FEED WATCHDOG TRIP: No tick received for %s in %ds (last tick age: %ds). Failing over...",
                        self.active_provider_name, settings.feed_stale_seconds, age
                    )
                    self._failover()

    async def _failback_loop(self, symbols: List[str]):
        """Periodically checks if the primary provider is healthy again and promotes it."""
        primary_provider = settings.feed_providers[0]
        
        while self.is_running:
            # Check failback check cadence (default 120s)
            await asyncio.sleep(settings.feed_failback_seconds)
            
            if self.active_provider_name != primary_provider:
                logger.info("Failback probe: Checking health of primary provider %s...", primary_provider)
                provider = self.providers.get(primary_provider)
                if provider:
                    is_healthy = await provider.healthy()
                    if is_healthy:
                        logger.info("Primary provider %s is healthy again. Reverting...", primary_provider)
                        self._switch_provider(primary_provider)

    def _notify_status(self):
        if self.on_status_cb:
            self.on_status_cb(self.get_status())

    async def stop(self):
        self.is_running = False
        if self.active_task:
            self.active_task.cancel()
        if self.recorder:
            self.recorder.close()
        logger.info("Feed manager stopped.")
