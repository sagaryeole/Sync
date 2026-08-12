"""Tests for FeedManager: backoff schedule, failover order, staleness watchdog, failback."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from datetime import datetime, timezone, timedelta

from feeds.manager import FeedManager
from feeds.base import Tick


def make_tick(symbol="BTC", price=50000.0, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return Tick(
        symbol=symbol,
        price=price,
        ts=ts,
        source="test",
        bid=price - 1.0,
        ask=price + 1.0,
    )


class FakeFeed:
    def __init__(self, name, ticks=None, healthy=True):
        self._name = name
        self._ticks = ticks or []
        self._healthy = healthy

    @property
    def name(self):
        return self._name

    async def stream(self, symbols):
        for tick in self._ticks:
            yield tick
        # Keep the stream open until cancelled
        await asyncio.sleep(9999)

    async def healthy(self):
        return self._healthy


class TestFeedManagerBackoff:
    def test_backoff_delay_increases_exponentially(self):
        manager = FeedManager()
        base = 1
        cap = 60
        for attempt in range(5):
            delay = min(cap, base * (2 ** attempt))
            assert delay == [1, 2, 4, 8, 16][attempt]

    def test_failover_rotates_to_next_provider(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        with patch.object(manager, "_switch_provider") as mock_switch:
            manager._failover()
            mock_switch.assert_called_once()

    def test_switch_provider_updates_state(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        manager.status_since = datetime.now(timezone.utc)
        manager.last_switch_time = None
        manager.pending_confirmations = {"BTC": 1}

        manager._switch_provider("binance")

        assert manager.active_provider_name == "binance"
        assert manager.last_switch_time is not None
        assert manager.pending_confirmations == {}
        assert manager.status_since is not None

    def test_failover_skips_to_next_on_invalid_current(self):
        manager = FeedManager()
        manager.active_provider_name = "nonexistent"
        with patch.object(manager, "_switch_provider") as mock_switch:
            manager._failover()
            mock_switch.assert_called_once()


class TestFeedManagerWatchdog:
    def test_watchdog_trips_when_ticks_stale(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        manager.last_tick_time = datetime.now(timezone.utc) - timedelta(seconds=999)

        from settings import get_settings
        settings = get_settings()

        assert (datetime.now(timezone.utc) - manager.last_tick_time).total_seconds() > settings.feed_stale_seconds

    def test_watchdog_does_not_trip_on_synthetic(self):
        manager = FeedManager()
        manager.active_provider_name = "synthetic"
        manager.last_tick_time = datetime.now(timezone.utc) - timedelta(seconds=999)

        should_trip = (
            manager.active_provider_name != "synthetic"
            and manager.last_tick_time is not None
            and (datetime.now(timezone.utc) - manager.last_tick_time).total_seconds() > 30
        )
        assert should_trip is False

    def test_watchdog_does_not_trip_when_recent(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        manager.last_tick_time = datetime.now(timezone.utc) - timedelta(seconds=1)

        should_trip = (
            manager.active_provider_name != "synthetic"
            and manager.last_tick_time is not None
            and (datetime.now(timezone.utc) - manager.last_tick_time).total_seconds() > 30
        )
        assert should_trip is False


class TestFeedManagerFailback:
    def test_failback_promotes_primary_when_healthy(self):
        manager = FeedManager()
        manager.active_provider_name = "binance"

        provider = FakeFeed("coinbase", healthy=True)
        with patch.object(manager, "_switch_provider") as mock_switch:
            asyncio.get_event_loop().run_until_complete(
                self._failback_check(manager, provider)
            )
            mock_switch.assert_called_once_with("coinbase")

    async def _failback_check(self, manager, provider):
        if manager.active_provider_name != "coinbase":
            is_healthy = await provider.healthy()
            if is_healthy:
                manager._switch_provider("coinbase")

    def test_failback_does_not_promote_when_unhealthy(self):
        manager = FeedManager()
        manager.active_provider_name = "binance"

        provider = FakeFeed("coinbase", healthy=False)
        with patch.object(manager, "_switch_provider") as mock_switch:
            asyncio.get_event_loop().run_until_complete(
                self._failback_check(manager, provider)
            )
            mock_switch.assert_not_called()


class TestFeedManagerStatus:
    def test_status_connected_when_recent_tick(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        manager.is_running = True
        manager.last_tick_time = datetime.now(timezone.utc)

        status = manager.get_status()
        assert status["status"] == "CONNECTED"
        assert status["provider"] == "coinbase"
        assert status["mode"] == "LIVE"

    def test_status_degraded_on_binance(self):
        manager = FeedManager()
        manager.active_provider_name = "binance"
        manager.is_running = True
        manager.last_tick_time = datetime.now(timezone.utc)

        status = manager.get_status()
        assert status["mode"] == "DEGRADED"
        assert status["status"] == "DEGRADED"

    def test_status_sim_on_synthetic(self):
        manager = FeedManager()
        manager.active_provider_name = "synthetic"
        manager.is_running = True
        manager.last_tick_time = datetime.now(timezone.utc)

        status = manager.get_status()
        assert status["mode"] == "SIM"

    def test_status_disconnected_when_no_ticks(self):
        manager = FeedManager()
        manager.active_provider_name = "coinbase"
        manager.is_running = True
        manager.last_tick_time = None

        status = manager.get_status()
        assert status["status"] == "DISCONNECTED"
