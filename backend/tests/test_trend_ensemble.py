"""Tests for the volatility-scaled trend ensemble and its supporting pieces.

The behavioural tests below assert the *mechanisms* (hysteresis band, cost
gate, long-only, conviction sizing), not a P&L number. A profitability
assertion on a fixed candle fixture would only be asserting that the fixture
was picked to pass.
"""
import math
import random

import pytest

from strategies.base import Action, Candle, Position, StrategyContext
from strategies.indicators import (
    ema_series,
    log_returns,
    realized_vol,
    rolling_stdev_series,
)
from strategies.trend_ensemble import TrendEnsembleStrategy, _pair_signal
from strategies.schemas import validate_params


# ---------------------------------------------------------------------------
# Series primitives
# ---------------------------------------------------------------------------

class TestEmaSeries:
    def test_length_matches_input(self):
        assert len(ema_series([1.0] * 50, 10)) == 50

    def test_constant_series_is_constant(self):
        out = ema_series([5.0] * 30, 10)
        assert all(abs(v - 5.0) < 1e-9 for v in out)

    def test_seeded_with_first_value(self):
        assert ema_series([3.0, 4.0, 5.0], 5)[0] == 3.0

    def test_uses_standard_alpha_not_wilder(self):
        """alpha = 2/(span+1), so a step from 0 to 1 with span=1 jumps fully."""
        out = ema_series([0.0, 1.0], 1)
        assert out[1] == pytest.approx(1.0)

    def test_tracks_a_ramp_upward(self):
        out = ema_series([float(i) for i in range(50)], 10)
        assert out[-1] > out[-10] > out[0]

    def test_empty_and_bad_span(self):
        assert ema_series([], 10) == []
        assert ema_series([1.0, 2.0], 0) == []


class TestRollingStdevSeries:
    def test_none_before_full_window(self):
        out = rolling_stdev_series([1.0, 2.0, 3.0, 4.0], 3)
        assert out[0] is None and out[1] is None
        assert out[2] is not None

    def test_matches_sample_stdev(self):
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        got = rolling_stdev_series(vals, len(vals))[-1]
        n = len(vals)
        mean = sum(vals) / n
        want = math.sqrt(sum((x - mean) ** 2 for x in vals) / (n - 1))
        assert got == pytest.approx(want)

    def test_constant_window_is_zero_not_negative(self):
        """Float cancellation must not produce a negative variance."""
        out = rolling_stdev_series([1e6] * 40, 20)
        assert out[-1] == 0.0

    def test_degenerate_window(self):
        assert rolling_stdev_series([1.0, 2.0], 1) == [None, None]


class TestLogReturnsAndRealizedVol:
    def test_log_returns_length(self):
        assert len(log_returns([1.0, 2.0, 3.0])) == 2

    def test_non_positive_price_yields_zero_not_raise(self):
        """H1: a bad tick must not poison the series with NaN/-inf."""
        out = log_returns([1.0, 0.0, -5.0, 2.0])
        assert all(math.isfinite(r) for r in out)
        assert out[0] == 0.0

    def test_realized_vol_positive_for_noisy_series(self):
        prices = [100.0 * (1.0 + 0.01 * (-1) ** i) for i in range(80)]
        rv = realized_vol(prices, 60)
        assert rv is not None and rv > 0

    def test_realized_vol_none_on_flat_series(self):
        """A zero vol would make a vol-scaled size infinite — must be None."""
        assert realized_vol([100.0] * 80, 60) is None

    def test_realized_vol_none_on_short_series(self):
        assert realized_vol([100.0, 101.0], 60) is None


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def _candles(closes):
    return [
        Candle(symbol="BTC", open_time=i, open=c, high=c * 1.001,
               low=c * 0.999, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


def _walk(n=400, drift=0.0008, vol=0.0015, start=100.0, seed=42):
    """Seeded geometric random walk — deterministic, but with genuine noise.

    A perfectly linear ramp is *not* usable as a fixture here: with constant
    drift the normalised signal has near-zero dispersion of its own, which
    sends the z-score to infinity and the concave response function
    ``z*exp(-z^2/4)`` correctly to zero. That is the intended
    over-extension guard, not a bug, but it makes a clean ramp a degenerate
    input. Real series carry noise, so the fixtures do too.
    """
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1.0 + drift + rng.gauss(0.0, vol)))
    return prices


def _regime(n=500, period=80, amp=0.0020, final_drift=0.0030,
            final_bars=40, vol=0.0015, start=100.0, seed=42):
    """Oscillating drift (alternating regimes) then a clean trend at the end.

    The oscillation is what makes this a usable fixture. The normalised signal
    is divided by its *own* rolling dispersion, so a series whose drift never
    changes sign gives it almost no dispersion, pins the z-score at the clamp,
    and flattens conviction to ~0.085 regardless of how strong the trend is.
    Real series alternate between ranging and trending — the live candle
    history in this repo produces a signal with stdev ~0.52 across the full
    [-1, 1] range — so the fixture alternates too, with the decisive trend
    placed at the end where ``evaluate`` reads it.
    """
    rng = random.Random(seed)
    prices = [start]
    for i in range(n - 1):
        d = amp * math.sin(2.0 * math.pi * i / period)
        if i >= n - 1 - final_bars:
            d = final_drift
        prices.append(prices[-1] * (1.0 + d + rng.gauss(0.0, vol)))
    return prices


def _uptrend(**kw):
    return _regime(final_drift=0.0030, **kw)


def _downtrend(**kw):
    return _regime(final_drift=-0.0030, **kw)


class TestPairSignal:
    def test_none_without_enough_history(self):
        assert _pair_signal([100.0] * 50, 15, 45, 60, 100) is None

    def test_positive_in_uptrend(self):
        assert _pair_signal(_uptrend(), 15, 45, 60, 100) > 0

    def test_negative_in_downtrend(self):
        assert _pair_signal(_downtrend(), 15, 45, 60, 100) < 0

    def test_bounded_to_unit_interval(self):
        for closes in (_uptrend(), _downtrend()):
            s = _pair_signal(closes, 15, 45, 60, 100)
            assert -1.0 <= s <= 1.0

    def test_flat_series_returns_none(self):
        """Zero price dispersion -> no signal, not a divide-by-zero."""
        assert _pair_signal([100.0] * 400, 15, 45, 60, 100) is None

    def test_persistent_trend_does_not_collapse_to_zero(self):
        """Regression: a single-regime trend must not underflow to exactly 0.

        Without the z clamp, a drift that never reverses leaves the normalised
        signal with near-zero dispersion of its own, so z reaches the tens or
        hundreds and exp(-z^2/4) underflows to 0.0 — the strategy would go
        blind during the strongest possible trend. Conviction should be small
        (it is genuinely over-extended) but strictly non-zero and correctly
        signed.
        """
        up = _walk(n=400, drift=0.0008, seed=3)
        down = _walk(n=400, drift=-0.0008, seed=3)
        s_up = _pair_signal(up, 15, 45, 60, 100)
        s_down = _pair_signal(down, 15, 45, 60, 100)
        assert s_up is not None and s_down is not None
        assert s_up > 0.0, "persistent uptrend collapsed to zero conviction"
        assert s_down < 0.0, "persistent downtrend collapsed to zero conviction"


# ---------------------------------------------------------------------------
# Strategy behaviour
# ---------------------------------------------------------------------------

def _ctx(closes, position=None, params=None):
    strat = TrendEnsembleStrategy()
    return StrategyContext(
        symbol="BTC",
        candles=_candles(closes),
        last_price=closes[-1],
        position=position,
        cash=100_000.0,
        equity=100_000.0,
        params=params or strat.default_params,
    )


class TestTrendEnsemble:
    def setup_method(self):
        self.s = TrendEnsembleStrategy()

    def test_insufficient_data_holds(self):
        d = self.s.evaluate(_ctx([100.0] * 60))
        assert d.action == Action.HOLD
        assert d.reason == "insufficient_data"

    def test_registered_under_its_key(self):
        from strategies.registry import get_strategy
        assert get_strategy("trend_ensemble") is not None

    def test_declares_strength_sizing(self):
        assert self.s.uses_strength_sizing is True

    def test_no_short_on_downtrend(self):
        """Long-only: a negative signal while flat is HOLD, never SELL."""
        d = self.s.evaluate(_ctx(_downtrend()))
        assert d.action == Action.HOLD
        assert d.reason == "no_uptrend"

    def test_strength_within_unit_interval(self):
        d = self.s.evaluate(_ctx(_uptrend()))
        assert 0.0 <= d.strength <= 1.0

    def test_exposes_signal_in_indicators(self):
        d = self.s.evaluate(_ctx(_uptrend()))
        assert "signal" in d.indicators
        assert -1.0 <= d.indicators["signal"] <= 1.0

    # --- the two mechanisms that make it viable ---------------------------

    def test_cost_gate_blocks_when_edge_below_cost(self):
        """An absurd fee makes every entry uneconomic, whatever the signal."""
        params = dict(self.s.default_params)
        params["taker_fee_bps"] = 5000.0
        d = self.s.evaluate(_ctx(_uptrend(), params=params))
        assert d.action == Action.HOLD
        assert d.reason == "edge_below_cost"

    def test_cost_gate_permits_when_fees_are_negligible(self):
        params = dict(self.s.default_params)
        params.update(taker_fee_bps=0.0, slippage_bps=0.0, min_edge_multiple=0.0)
        d = self.s.evaluate(_ctx(_uptrend(), params=params))
        assert d.action == Action.BUY
        assert d.reason == "trend_entry"

    def test_hysteresis_holds_between_thresholds(self):
        """A position is retained while the signal sits in the no-trade band —
        this gap is what collapses turnover, so it is asserted directly."""
        params = dict(self.s.default_params)
        closes = _uptrend()
        sig = self.s.evaluate(_ctx(closes, params=params)).indicators["signal"]
        # Put the band around the current signal: below entry, above exit.
        params["entry_threshold"] = sig + 0.2
        params["exit_threshold"] = sig - 0.2
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=100.0)
        d = self.s.evaluate(_ctx(closes, position=pos, params=params))
        assert d.action == Action.HOLD
        assert d.reason == "trend_intact"

    def test_exits_once_signal_falls_below_exit_threshold(self):
        params = dict(self.s.default_params)
        closes = _uptrend()
        sig = self.s.evaluate(_ctx(closes, params=params)).indicators["signal"]
        params["exit_threshold"] = sig + 0.1  # signal is now below it
        pos = Position(symbol="BTC", quantity=1.0, avg_entry_price=100.0)
        d = self.s.evaluate(_ctx(closes, position=pos, params=params))
        assert d.action == Action.SELL
        assert d.reason == "trend_decayed"

    def test_flat_entry_requires_exceeding_entry_threshold(self):
        params = dict(self.s.default_params)
        params["entry_threshold"] = 0.999
        d = self.s.evaluate(_ctx(_uptrend(), params=params))
        assert d.action == Action.HOLD
        assert d.reason == "below_entry_threshold"

    def test_higher_vol_gives_smaller_conviction(self):
        """Volatility targeting: same drift and seed, more vol -> smaller size.

        Both walks share a seed so the trend shape is comparable and only the
        noise scale differs.
        """
        params = dict(self.s.default_params)
        params.update(taker_fee_bps=0.0, slippage_bps=0.0, min_edge_multiple=0.0)
        calm = self.s.evaluate(_ctx(_regime(vol=0.0010, seed=7), params=params))
        rough = self.s.evaluate(_ctx(_regime(vol=0.0060, seed=7), params=params))
        assert calm.action == Action.BUY
        if rough.action == Action.BUY:
            assert rough.strength <= calm.strength


# ---------------------------------------------------------------------------
# Param validation (H9)
# ---------------------------------------------------------------------------

class TestTrendEnsembleParams:
    def test_defaults_validate(self):
        out = validate_params("trend_ensemble", {})
        assert out["entry_threshold"] > out["exit_threshold"]

    def test_rejects_exit_at_or_above_entry(self):
        """Collapsing the hysteresis band reintroduces the turnover problem."""
        with pytest.raises(Exception):
            validate_params("trend_ensemble",
                            {"entry_threshold": 0.2, "exit_threshold": 0.4})

    def test_rejects_inverted_pair(self):
        with pytest.raises(Exception):
            validate_params("trend_ensemble", {"pairs": [[90, 30]]})

    def test_rejects_absurd_span(self):
        with pytest.raises(Exception):
            validate_params("trend_ensemble", {"pairs": [[1, 10 ** 9]]})

    def test_rejects_malformed_pair(self):
        with pytest.raises(Exception):
            validate_params("trend_ensemble", {"pairs": [[15, 45, 90]]})

    def test_rejects_empty_pairs(self):
        with pytest.raises(Exception):
            validate_params("trend_ensemble", {"pairs": []})

    def test_rejects_negative_target_vol(self):
        with pytest.raises(Exception):
            validate_params("trend_ensemble", {"target_vol": -1.0})


# ---------------------------------------------------------------------------
# Conviction -> position size wiring
# ---------------------------------------------------------------------------

class TestSizeScale:
    """`size_scale` is what makes the volatility targeting real rather than
    cosmetic — without it the risk manager would ignore Decision.strength.
    """

    def _account(self):
        from engine.portfolio import PortfolioAccount
        return PortfolioAccount(strategy_id=1, strategy_key="t",
                                starting_cash=100_000.0)

    def _rm(self):
        from engine.risk import RiskConfig, RiskManager
        return RiskManager(RiskConfig())

    def test_default_scale_is_unchanged(self):
        """Existing callers must be byte-for-byte unaffected."""
        rm, acct = self._rm(), self._account()
        marks = {"BTC": 100.0}
        base, _, _, err = rm.size_order(acct, "BTC", 100.0, marks)
        scaled, _, _, err2 = rm.size_order(acct, "BTC", 100.0, marks,
                                           size_scale=1.0)
        assert err is None and err2 is None
        assert base == scaled

    def test_half_conviction_halves_size(self):
        rm, acct = self._rm(), self._account()
        marks = {"BTC": 100.0}
        full, _, _, _ = rm.size_order(acct, "BTC", 100.0, marks, size_scale=1.0)
        half, _, _, _ = rm.size_order(acct, "BTC", 100.0, marks, size_scale=0.5)
        assert half == pytest.approx(full * 0.5, rel=1e-6)

    def test_scale_above_one_is_clamped_not_amplified(self):
        """A bad strength must never inflate a position past the risk budget."""
        rm, acct = self._rm(), self._account()
        marks = {"BTC": 100.0}
        full, _, _, _ = rm.size_order(acct, "BTC", 100.0, marks, size_scale=1.0)
        over, _, _, _ = rm.size_order(acct, "BTC", 100.0, marks, size_scale=99.0)
        assert over == pytest.approx(full, rel=1e-6)

    def test_non_finite_scale_rejected(self):
        rm, acct = self._rm(), self._account()
        marks = {"BTC": 100.0}
        for bad in (float("nan"), float("inf"), 0.0, -1.0):
            qty, _, _, err = rm.size_order(acct, "BTC", 100.0, marks,
                                           size_scale=bad)
            assert qty is None
            assert err == "INVALID_SIZE_SCALE"
