"""Tests for feeds/recorder.py — V2 feed recorder and replay."""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

import pytest
from feeds.base import Tick
from feeds.recorder import FeedRecorder, ReplayFeed


def _tick(price=100.0, symbol="BTC", source="coinbase"):
    return Tick(symbol=symbol, price=price, ts=datetime.now(timezone.utc), source=source)


class TestFeedRecorder:
    def test_record_and_close(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        os.unlink(path)  # remove so recorder creates fresh

        try:
            recorder = FeedRecorder(path)
            recorder.open()
            assert recorder.count == 0

            recorder.record(_tick(price=100.0))
            recorder.record(_tick(price=101.0, symbol="ETH"))
            recorder.record(_tick(price=102.0, symbol="SOL"))
            assert recorder.count == 3

            recorder.close()

            # Verify file contents
            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 3

            first = json.loads(lines[0])
            assert first["symbol"] == "BTC"
            assert first["price"] == 100.0
            assert first["source"] == "coinbase"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_record_before_open_is_silent(self):
        recorder = FeedRecorder("/tmp/nonexistent_path/test.jsonl")
        recorder.record(_tick())  # should not raise
        assert recorder.count == 0


class TestReplayFeed:
    @pytest.mark.asyncio
    async def test_replay_reads_recorded_ticks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            # Write some ticks
            recorder = FeedRecorder(path)
            recorder.open()
            recorder.record(_tick(price=100.0, symbol="BTC"))
            recorder.record(_tick(price=101.0, symbol="BTC"))
            recorder.record(_tick(price=50.0, symbol="ETH"))
            recorder.close()

            # Replay BTC only
            feed = ReplayFeed(path, speed=0)  # instant playback
            ticks = []
            async for tick in feed.stream(["BTC"]):
                ticks.append(tick)

            assert len(ticks) == 2
            assert all(t.symbol == "BTC" for t in ticks)
            assert ticks[0].price == 100.0
            assert ticks[1].price == 101.0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_replay_missing_file_returns_empty(self):
        feed = ReplayFeed("/tmp/nonexistent_file_12345.jsonl")
        ticks = []
        async for tick in feed.stream(["BTC"]):
            ticks.append(tick)
        assert len(ticks) == 0

    @pytest.mark.asyncio
    async def test_replay_healthy(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            feed = ReplayFeed(path)
            assert await feed.healthy() is True
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_replay_not_healthy_missing(self):
        feed = ReplayFeed("/tmp/nonexistent_file_12345.jsonl")
        assert await feed.healthy() is False
