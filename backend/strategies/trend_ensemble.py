"""Volatility-scaled multi-horizon trend ensemble.

This is the strategy the engine's other three should be measured against. It is
not a new indicator — it is the standard managed-futures / CTA construction,
which is the one systematic approach with genuinely broad out-of-sample
evidence behind it. Nothing here predicts price; it sizes exposure to an
already-established trend and tries very hard not to pay away the edge in fees.

Why this shape (each piece is load-bearing, not decoration)
-----------------------------------------------------------

1. **Time-series momentum, not an oscillator.** Moskowitz, Ooi & Pedersen
   (2012) "Time Series Momentum" and Hurst, Ooi & Pedersen's "A Century of
   Evidence on Trend-Following Investing" document positive trend premia across
   dozens of markets and ~100 years. It is the most replicated systematic
   anomaly there is. Mean-reversion oscillators like RSI(14) 30/70 have no
   comparable evidence — those thresholds are conventions from Wilder's 1978
   book, not estimates of anything.

2. **An ensemble of lookbacks, not one "best" pair.** Any single (fast, slow)
   pair is a parameter someone fit. Averaging several horizons is what
   practitioners do precisely because it removes the single point of
   overfitting; the ensemble's out-of-sample decay is far smaller than the
   best in-sample pair's.

3. **Double normalisation (Baz et al. 2015).** The raw EMA spread is divided
   first by price volatility (so BTC at $65k and DOGE at $0.12 produce
   comparable numbers) and then by the *signal's own* dispersion (so the
   result is a z-score comparable across symbols and regimes). Without step
   one, position sizing is implicitly a bet on nominal price level.

4. **A concave response function.** ``z·exp(-z²/4)`` peaks near |z|=√2 and
   decays after. Conviction does not grow without bound in an extreme trend —
   very extended moves are disproportionately likely to be near exhaustion.
   This is the standard intermediate signal from Baz et al.

5. **Volatility targeting.** Position size scales with
   ``target_vol / realised_vol``. Moreira & Muir (2017) "Volatility-Managed
   Portfolios" is the reference. This matters more than the entry rule: it
   keeps risk roughly constant instead of silently taking 3× the risk when
   crypto vol triples.

6. **A hysteresis band, and this is the one that actually decides whether the
   strategy is viable at all.** Entry needs |signal| > ``entry_threshold``;
   exit only happens below the much lower ``exit_threshold``. The gap between
   them is a no-trade zone. Measured on this repo's own candle history, the
   three original strategies turned over 9–37 round-trips/symbol/day against a
   ~23bp round-trip cost, which is a structural -7% to -30% fee drag before any
   opinion about direction. A deadband is the direct fix.

7. **An explicit cost gate.** Before opening, the expected move over the
   signal's natural holding horizon must exceed the round-trip cost by
   ``min_edge_multiple``. If the edge does not clear the toll booth, the
   correct action is not to trade.

Honest limits
-------------
Long-only (the broker does not support shorts), so roughly half the trend
premium — the short side — is unavailable. Trend systems lose money in
range-bound markets by construction; they win with a low hit rate (~35-45%)
and a high win/loss size ratio, so a "win rate" figure read in isolation will
look bad and is the wrong metric. None of this makes money reliably at 1-minute
resolution, where the informed counterparty is faster than you are; the
horizons below are hours, and the 1m bars are only the sampling grid.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from strategies.base import Action, Decision, StrategyContext
from strategies.indicators import (
    ema_series,
    realized_vol,
    rolling_stdev_series,
)
from strategies.registry import register

# Peak of z*exp(-z^2/4), attained at z = sqrt(2). Dividing by it bounds the
# response function to [-1, 1] exactly.
_RESPONSE_PEAK = math.sqrt(2.0) * math.exp(-0.5)  # ~0.857764

_EPS = 1e-12

# Bound on the normalised z-score before the response function. Past the
# response peak (sqrt(2) ~ 1.41), so over-extension still reduces conviction,
# but far enough out that exp(-z^2/4) cannot underflow to exactly zero.
_Z_CLAMP = 4.0

# (fast, slow) EMA spans in 1m bars: 15m/45m, 30m/90m, 1h/3h.
_DEFAULT_PAIRS: Tuple[Tuple[int, int], ...] = ((15, 45), (30, 90), (60, 180))

_BARS_PER_YEAR_1M = 525_600


def _pair_signal(
    closes: List[float],
    fast: int,
    slow: int,
    vol_window: int,
    norm_window: int,
) -> Optional[float]:
    """Baz-style normalised trend signal for one (fast, slow) pair.

    Returns a value in [-1, 1], or None if there is not enough history.
    """
    if len(closes) < slow + vol_window + norm_window:
        return None

    fast_e = ema_series(closes, fast)
    slow_e = ema_series(closes, slow)
    if not fast_e or not slow_e:
        return None

    # 1. Raw spread.
    spread = [f - s for f, s in zip(fast_e, slow_e)]

    # 2. Normalise by price volatility -> scale-free across symbols.
    price_sd = rolling_stdev_series(closes, vol_window)
    y: List[float] = []
    for sp, sd in zip(spread, price_sd):
        if sd is None or sd <= _EPS:
            continue
        y.append(sp / sd)
    if len(y) < norm_window:
        return None

    # 3. Normalise by the signal's own dispersion -> a z-score.
    y_sd = rolling_stdev_series(y, norm_window)
    sd_last = y_sd[-1]
    if sd_last is None or sd_last <= _EPS:
        return None
    z = y[-1] / sd_last

    # Clamp before the response function. `z` is a ratio to the signal's own
    # dispersion with no mean subtraction (this is the published form), so a
    # trend that persists in one direction for the whole normalisation window
    # gives y almost no dispersion and sends z to tens or hundreds. Then
    # exp(-z^2/4) underflows to exactly 0.0 and the strategy goes blind
    # precisely during the strongest trends — the opposite of intended.
    # Real series reverse often enough that this is rare, but clamping makes
    # it impossible rather than unlikely. _Z_CLAMP is past the response peak
    # (sqrt(2)), so genuine over-extension still decays conviction; it just
    # decays to a small number instead of vanishing.
    z = max(-_Z_CLAMP, min(_Z_CLAMP, z))

    # 4. Concave response: conviction decays once a move is over-extended.
    u = z * math.exp(-(z * z) / 4.0) / _RESPONSE_PEAK
    if not math.isfinite(u):
        return None
    return max(-1.0, min(1.0, u))


class TrendEnsembleStrategy:
    key = "trend_ensemble"
    name = "Trend Ensemble (vol-targeted)"

    # The runner multiplies the risk manager's sized quantity by
    # Decision.strength for strategies that set this. Without it the
    # volatility targeting below would be cosmetic.
    uses_strength_sizing = True

    default_params: Dict[str, Any] = {
        # Signal
        "pairs": [[15, 45], [30, 90], [60, 180]],
        "vol_window": 60,
        "norm_window": 100,
        # Hysteresis band — the turnover control
        "entry_threshold": 0.35,
        "exit_threshold": 0.10,
        # Volatility targeting
        "target_vol": 0.30,      # 30% annualised
        "max_vol_scalar": 1.5,
        # Cost gate
        "taker_fee_bps": 10.0,
        "slippage_bps": 1.5,
        "min_edge_multiple": 2.0,
    }

    # longest slow (180) + vol_window (60) + norm_window (100), plus slack.
    warmup_bars = 350

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = ctx.params or self.default_params
        d = self.default_params

        raw_pairs = p.get("pairs", d["pairs"])
        pairs = [(int(a), int(b)) for a, b in raw_pairs if int(a) < int(b)]
        if not pairs:
            pairs = list(_DEFAULT_PAIRS)

        vol_window = int(p.get("vol_window", d["vol_window"]))
        norm_window = int(p.get("norm_window", d["norm_window"]))
        entry_th = float(p.get("entry_threshold", d["entry_threshold"]))
        exit_th = float(p.get("exit_threshold", d["exit_threshold"]))
        target_vol = float(p.get("target_vol", d["target_vol"]))
        max_scalar = float(p.get("max_vol_scalar", d["max_vol_scalar"]))
        taker_bps = float(p.get("taker_fee_bps", d["taker_fee_bps"]))
        slip_bps = float(p.get("slippage_bps", d["slippage_bps"]))
        min_edge_mult = float(p.get("min_edge_multiple", d["min_edge_multiple"]))

        closes = [c.close for c in ctx.candles]
        holding = bool(ctx.position and ctx.position.quantity > 0)

        # --- Signal ---------------------------------------------------------
        sigs = [
            s for s in (
                _pair_signal(closes, f, s_, vol_window, norm_window)
                for f, s_ in pairs
            )
            if s is not None
        ]
        if not sigs:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        signal = sum(sigs) / len(sigs)

        rv = realized_vol(closes, vol_window, _BARS_PER_YEAR_1M)
        indicators: Dict[str, Any] = {
            "signal": round(signal, 4),
            "components": [round(s, 4) for s in sigs],
            "realized_vol": round(rv, 4) if rv is not None else None,
        }

        # --- Exit: hysteresis, deliberately far below the entry threshold ---
        if holding:
            if signal < exit_th:
                return Decision(
                    action=Action.SELL,
                    strength=round(min(1.0, abs(signal - exit_th) + 0.5), 2),
                    reason="trend_decayed",
                    indicators=indicators,
                )
            return Decision(
                action=Action.HOLD, reason="trend_intact",
                indicators=indicators,
            )

        # --- Entry ----------------------------------------------------------
        # Long-only: a negative signal is a reason not to be long, not a short.
        if signal <= entry_th:
            return Decision(
                action=Action.HOLD,
                reason="below_entry_threshold" if signal > 0 else "no_uptrend",
                indicators=indicators,
            )

        if rv is None:
            return Decision(
                action=Action.HOLD, reason="no_vol_estimate",
                indicators=indicators,
            )

        # Volatility targeting: constant risk, not constant notional.
        vol_scalar = min(max_scalar, target_vol / rv) if rv > _EPS else 0.0
        if vol_scalar <= 0.0:
            return Decision(
                action=Action.HOLD, reason="vol_too_high",
                indicators=indicators,
            )

        # Cost gate: expected move over the signal's natural horizon must beat
        # the round trip. Horizon ~ the median slow span (signal half-life).
        horizon_bars = sorted(s_ for _, s_ in pairs)[len(pairs) // 2]
        per_bar_vol = rv / math.sqrt(_BARS_PER_YEAR_1M)
        expected_move = abs(signal) * per_bar_vol * math.sqrt(horizon_bars)
        round_trip_cost = 2.0 * (taker_bps + slip_bps) / 1e4
        indicators["expected_move"] = round(expected_move, 5)
        indicators["round_trip_cost"] = round(round_trip_cost, 5)

        if expected_move < min_edge_mult * round_trip_cost:
            return Decision(
                action=Action.HOLD,
                reason="edge_below_cost",
                indicators=indicators,
            )

        strength = max(0.0, min(1.0, abs(signal) * vol_scalar))
        indicators["vol_scalar"] = round(vol_scalar, 3)
        return Decision(
            action=Action.BUY,
            strength=round(strength, 3),
            reason="trend_entry",
            indicators=indicators,
        )


register(TrendEnsembleStrategy())
