"""Tests for candle bucketing, OHLC aggregation, rollover, and drain."""
import pytest
from datetime import datetime, timezone, timedelta
from threading import Lock
from unittest.mock import patch

from engine.market_state import MarketState, bucket_time
from models import Candle
from feeds.base import Tick


def make_tick(symbol, price, ts=None, source="test"):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return Tick(
        symbol=symbol,
        price=price,
        ts=ts,
        source=source,
        bid=price - 1.0,
        ask=price + 1.0,
    )


class TestBucketTime:
    def test_bucket_time_floors_to_minute(self):
        ts = datetime(2024, 1, 15, 10, 15, 34, 123456, tzinfo=timezone.utc)
        assert bucket_time(ts) == datetime(2024, 1, 15, 10, 15, 0, 0, tzinfo=timezone.utc)

    def test_bucket_time_at_exact_minute(self):
        ts = datetime(2024, 1, 15, 10, 15, 0, 0, tzinfo=timezone.utc)
        assert bucket_time(ts) == datetime(2024, 1, 15, 10, 15, 0, 0, tzinfo=timezone.utc)

    def test_bucket_time_at_59_999(self):
        ts = datetime(2024, 1, 15, 10, 15, 59, 999000, tzinfo=timezone.utc)
        assert bucket_time(ts) == datetime(2024, 1, 15, 10, 15, 0, 0, tzinfo=timezone.utc)

    def test_bucket_time_at_00_000(self):
        ts = datetime(2024, 1, 15, 10, 16, 0, 0, tzinfo=timezone.utc)
        assert bucket_time(ts) == datetime(2024, 1, 15, 10, 16, 0, 0, tzinfo=timezone.utc)


class TestCandleOHLC:
    def test_first_tick_opens_candle(self):
        ms = MarketState()
        tick = make_tick("BTC", 50000.0, ts=datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc))
        result = ms.on_tick(tick)
        assert result is None

        candle = ms.open_candle("BTC")
        assert candle is not None
        assert candle["open"] == 50000.0
        assert candle["high"] == 50000.0
        assert candle["low"] == 50000.0
        assert candle["close"] == 50000.0
        assert candle["volume"] == 0.0
        assert candle["trades"] == 1

    def test_multiple_ticks_update_ohlc(self):
        ms = MarketState()
        base_ts = datetime(2024, 1, 15, 10, 15, 0, tzinfo=timezone.utc)

        with patch("engine.market_state.datetime") as mock_dt:
            mock_dt.now.return_value = base_ts
            mock_dt.timezone = timezone
            ms.on_tick(make_tick("BTC", 50000.0, ts=base_ts))

            mock_dt.now.return_value = base_ts + timedelta(seconds=10)
            ms.on_tick(make_tick("BTC", 51000.0, ts=base_ts + timedelta(seconds=10)))

            mock_dt.now.return_value = base_ts + timedelta(seconds=20)
            ms.on_tick(make_tick("BTC", 49000.0, ts=base_ts + timedelta(seconds=20)))

            mock_dt.now.return_value = base_ts + timedelta(seconds=30)
            ms.on_tick(make_tick("BTC", 50500.0, ts=base_ts + timedelta(seconds=30)))

        candle = ms.open_candle("BTC")
        assert candle["open"] == 50000.0
        assert candle["high"] == 51000.0
        assert candle["low"] == 49000.0
        assert candle["close"] == 50500.0
        assert candle["trades"] == 4

    def test_tick_in_new_minute_rolls_candle(self):
        ms = MarketState()
        ts1 = datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 10, 16, 0, tzinfo=timezone.utc)

        with patch("engine.market_state.datetime") as mock_dt:
            mock_dt.now.return_value = ts1
            mock_dt.timezone = timezone
            ms.on_tick(make_tick("BTC", 50000.0, ts=ts1))

            mock_dt.now.return_value = ts2
            closed = ms.on_tick(make_tick("BTC", 51000.0, ts=ts2))

        assert closed is not None
        assert closed.symbol == "BTC"
        assert closed.open == 50000.0
        assert closed.high == 50000.0
        assert closed.low == 50000.0
        assert closed.close == 50000.0

        new_candle = ms.open_candle("BTC")
        assert new_candle is not None
        assert new_candle["open"] == 51000.0

    def test_rollover_emits_exactly_once(self):
        ms = MarketState()
        ts1 = datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 10, 16, 0, tzinfo=timezone.utc)
        ts3 = datetime(2024, 1, 15, 10, 16, 30, tzinfo=timezone.utc)

        with patch("engine.market_state.datetime") as mock_dt:
            mock_dt.now.return_value = ts1
            mock_dt.timezone = timezone
            ms.on_tick(make_tick("BTC", 50000.0, ts=ts1))

            mock_dt.now.return_value = ts2
            closed1 = ms.on_tick(make_tick("BTC", 51000.0, ts=ts2))

            mock_dt.now.return_value = ts3
            closed2 = ms.on_tick(make_tick("BTC", 52000.0, ts=ts3))

        assert closed1 is not None
        assert closed2 is None


class TestCandleDrain:
    def test_drain_returns_closed_candles(self):
        ms = MarketState()
        ts1 = datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 10, 16, 30, tzinfo=timezone.utc)

        with patch("engine.market_state.datetime") as mock_dt:
            mock_dt.now.return_value = ts1
            mock_dt.timezone = timezone
            ms.on_tick(make_tick("BTC", 50000.0, ts=ts1))

            mock_dt.now.return_value = ts2
            ms.on_tick(make_tick("BTC", 51000.0, ts=ts2))

        drained = ms.drain_closed_candles()
        assert len(drained) == 1
        assert drained[0].open == 50000.0
        assert drained[0].close == 50000.0

    def test_drain_clears_queue(self):
        ms = MarketState()
        ts1 = datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 10, 16, 30, tzinfo=timezone.utc)

        with patch("engine.market_state.datetime") as mock_dt:
            mock_dt.now.return_value = ts1
            mock_dt.timezone = timezone
            ms.on_tick(make_tick("BTC", 50000.0, ts=ts1))

            mock_dt.now.return_value = ts2
            ms.on_tick(make_tick("BTC", 51000.0, ts=ts2))

        drained1 = ms.drain_closed_candles()
        assert len(drained1) == 1

        drained2 = ms.drain_closed_candles()
        assert len(drained2) == 0

    def test_close_all_candles_forces_close(self):
        ms = MarketState()
        ts = datetime(2024, 1, 15, 10, 15, 30, tzinfo=timezone.utc)
        ms.on_tick(make_tick("BTC", 50000.0, ts=ts))

        closed = ms.close_all_candles()
        assert len(closed) == 1
        assert closed[0].symbol == "BTC"
        assert ms.open_candle("BTC") is None
