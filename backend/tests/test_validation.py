"""Tests for feeds/validation.py — H1 (NaN rejection) and H4 (tick sanity band)."""
import math
from datetime import datetime, timezone, timedelta

import pytest
from feeds.base import Tick
from feeds.validation import (
    validate_tick,
    TickValidationError,
    MAX_TICK_MOVE_PCT,
    CONFIRM_TICKS,
)


def _tick(price=100.0, symbol="BTC", source="coinbase", ts=None, bid=None, ask=None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return Tick(symbol=symbol, price=price, ts=ts, source=source, bid=bid, ask=ask)


class TestH1NaNRejection:
    """H1: NaN/Infinity from the feed must never reach MarketState."""

    def test_nan_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite"):
            validate_tick(_tick(price=float("nan")), {}, {})

    def test_inf_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite"):
            validate_tick(_tick(price=float("inf")), {}, {})

    def test_negative_inf_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite"):
            validate_tick(_tick(price=float("-inf")), {}, {})

    def test_zero_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-positive"):
            validate_tick(_tick(price=0.0), {}, {})

    def test_negative_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-positive"):
            validate_tick(_tick(price=-1.0), {}, {})

    def test_nan_bid_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite bid"):
            validate_tick(_tick(price=100.0, bid=float("nan")), {}, {})

    def test_nan_ask_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite ask"):
            validate_tick(_tick(price=100.0, ask=float("inf")), {}, {})

    def test_bid_greater_than_ask_rejected(self):
        with pytest.raises(TickValidationError, match="bid.*>.*ask"):
            validate_tick(_tick(price=100.0, bid=101.0, ask=100.0), {}, {})

    def test_valid_bid_ask_accepted(self):
        tick = _tick(price=100.0, bid=99.5, ask=100.5)
        result = validate_tick(tick, {}, {})
        assert result is tick

    def test_bid_only_accepted(self):
        tick = _tick(price=100.0, bid=99.5, ask=None)
        result = validate_tick(tick, {}, {})
        assert result is tick


class TestH1TimestampSanity:
    """H1: stale or future timestamps must be rejected."""

    def test_stale_tick_rejected(self):
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=120)
        with pytest.raises(TickValidationError, match="stale"):
            validate_tick(_tick(ts=old_ts), {}, {})

    def test_future_tick_rejected(self):
        future_ts = datetime.now(timezone.utc) + timedelta(seconds=120)
        with pytest.raises(TickValidationError, match="future"):
            validate_tick(_tick(ts=future_ts), {}, {})

    def test_recent_tick_accepted(self):
        ts = datetime.now(timezone.utc) - timedelta(seconds=5)
        result = validate_tick(_tick(ts=ts), {}, {})
        assert result is not None


class TestH4TickSanityBand:
    """H4: a single large move is rejected unless confirmed by consecutive ticks."""

    def test_normal_move_accepted(self):
        last = {"BTC": 100.0}
        tick = _tick(price=105.0)  # 5% move, under 10% threshold
        result = validate_tick(tick, last, {})
        assert result is tick

    def test_large_move_rejected_first_time(self):
        last = {"BTC": 100.0}
        tick = _tick(price=120.0)  # 20% move, over 10% threshold
        with pytest.raises(TickValidationError, match="large move"):
            validate_tick(tick, last, {})

    def test_large_move_confirmed_after_k_ticks(self):
        last = {"BTC": 100.0}
        pending = {}

        # First large tick — rejected, pending count goes to 1
        tick1 = _tick(price=120.0)
        with pytest.raises(TickValidationError):
            validate_tick(tick1, last, pending)
        assert pending["BTC"] == 1

        # Second large tick — confirmed (count reaches CONFIRM_TICKS=2), adopted
        tick2 = _tick(price=121.0)
        result = validate_tick(tick2, last, pending)
        assert result is tick2
        assert pending["BTC"] == 0  # counter reset after adoption

    def test_normal_move_resets_confirmation_counter(self):
        last = {"BTC": 100.0}
        pending = {"BTC": 1}  # one large tick seen

        # A normal tick should reset the counter
        tick = _tick(price=105.0)  # 5% move
        validate_tick(tick, last, pending)
        assert pending["BTC"] == 0

    def test_first_tick_always_accepted(self):
        """No last price → no sanity band check."""
        tick = _tick(price=65000.0)
        result = validate_tick(tick, {}, {})
        assert result is tick
