"""Tests for strategies/indicators — deterministic 20-bar arrays."""
import math

import pytest

from strategies.indicators import sma, ema, rsi, atr, macd, bbands


def _sample_stddev(values):
    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# Fixed 20-bar OHLCV-like data
# ---------------------------------------------------------------------------
# Monotonic close series for easy hand-calculation.
CLOSES = [
    100.0, 102.0, 104.0, 106.0, 108.0,
    110.0, 112.0, 114.0, 116.0, 118.0,
    120.0, 122.0, 124.0, 126.0, 128.0,
    130.0, 132.0, 134.0, 136.0, 138.0,
]

HIGHS = [c + 1.0 for c in CLOSES]
LOWS = [c - 1.0 for c in CLOSES]


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------

class TestSMA:
    def test_short_list_returns_none(self):
        assert sma([], 5) is None
        assert sma([1.0, 2.0], 5) is None

    def test_exact_window(self):
        assert sma([1.0, 2.0, 3.0], 3) == pytest.approx(2.0)

    def test_longer_window_uses_last_n(self):
        assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == pytest.approx(4.0)

    def test_monotonic_20_bar(self):
        # Last 5 closes: 130, 132, 134, 136, 138 → avg = 134
        assert sma(CLOSES, 5) == pytest.approx(134.0)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_short_list_returns_none(self):
        assert ema([], 5) is None
        assert ema([1.0, 2.0], 5) is None

    def test_exact_span(self):
        # span=3 on [1,2,3] → seed SMA = 2.0, no further values
        assert ema([1.0, 2.0, 3.0], 3) == pytest.approx(2.0)

    def test_monotonic_20_bar_span5(self):
        # On a strictly rising series, EMA < last price but > SMA
        val = ema(CLOSES, 5)
        assert val is not None
        assert 130.0 < val < 138.0


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    def test_short_list_returns_none(self):
        assert rsi([], 14) is None
        assert rsi([1.0, 2.0], 14) is None

    def test_strictly_increasing_is_100(self):
        # Every delta is positive → RSI = 100
        assert rsi(CLOSES, 14) == pytest.approx(100.0)

    def test_strictly_decreasing_is_0(self):
        desc = list(reversed(CLOSES))
        val = rsi(desc, 14)
        assert val is not None
        assert val == pytest.approx(0.0)

    def test_alternating_bounds(self):
        # Alternate up/down by 1 → RSI near 50
        alt = [100.0 + (i % 2) for i in range(30)]
        val = rsi(alt, 14)
        assert val is not None
        assert 45.0 < val < 55.0


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_short_list_returns_none(self):
        assert atr([], [], [], 14) is None
        assert atr(HIGHS[:2], LOWS[:2], CLOSES[:2], 14) is None

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            atr([1.0, 2.0], [1.0], [1.0, 2.0], 1)

    def test_monotonic_20_bar(self):
        # TR = max(h-l, |h-pc|, |l-pc|) = max(2, 1, 3) = 3 for every bar
        val = atr(HIGHS, LOWS, CLOSES, 14)
        assert val == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

class TestMACD:
    def test_short_list_returns_none(self):
        assert macd([], 12, 26, 9) is None
        assert macd(CLOSES[:20], 12, 26, 9) is None  # need 26+9-1=34

    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            macd(CLOSES, fast=26, slow=12, signal=9)

    def test_monotonic_positive_histogram(self):
        # Need at least slow + signal - 1 = 26 + 9 - 1 = 34 bars
        long_prices = [100.0 + i for i in range(40)]
        val = macd(long_prices, 12, 26, 9)
        assert val is not None
        macd_line, signal_line, histogram = val
        assert macd_line > 0
        assert signal_line > 0
        assert histogram > 0


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBBands:
    def test_short_list_returns_none(self):
        assert bbands([], 20, 2.0) is None
        assert bbands(CLOSES[:5], 20, 2.0) is None

    def test_window_1_returns_flat_bands(self):
        lower, middle, upper = bbands([100.0, 101.0], 1, 2.0)
        assert lower == pytest.approx(101.0)
        assert middle == pytest.approx(101.0)
        assert upper == pytest.approx(101.0)

    def test_monotonic_20_bar(self):
        lower, middle, upper = bbands(CLOSES, 5, 2.0)
        assert middle == pytest.approx(134.0)
        std = _sample_stddev(CLOSES[-5:])
        assert lower == pytest.approx(134.0 - 2.0 * std)
        assert upper == pytest.approx(134.0 + 2.0 * std)
