"""Momentum breakout strategy.

Enter on a Donchian(20) breakout:
  - BUY when close breaks above the upper band
  - SELL when close breaks below the lower band

ATR(14) filter: only take signals when the breakout is at least 0.5× ATR
past the band, to reduce noise.

Exit conditions:
  - Trailing stop: 1× ATR below the highest high since entry
  - Or a 10-bar low breakout to the downside
"""
from __future__ import annotations

from typing import Any, Dict

from strategies.base import Action, Decision, StrategyContext
from strategies.indicators import atr, donchian
from strategies.registry import register


class MomentumBreakoutStrategy:
    key = "momentum_breakout"
    name = "Momentum Breakout"
    default_params = {
        "donchian_window": 20,
        "atr_period": 14,
        "atr_multiplier": 1.0,
        "exit_bars": 10,
    }
    warmup_bars = 20

    def evaluate(self, ctx: StrategyContext) -> Decision:
        params = ctx.params or self.default_params
        don_win = int(params.get("donchian_window", 20))
        atr_period = int(params.get("atr_period", 14))
        atr_mult = float(params.get("atr_multiplier", 1.0))
        exit_bars = int(params.get("exit_bars", 10))

        highs = [c.high for c in ctx.candles]
        lows = [c.low for c in ctx.candles]
        closes = [c.close for c in ctx.candles]

        dc = donchian(highs, lows, don_win)
        atr_val = atr(highs, lows, closes, atr_period)

        if dc is None or atr_val is None or atr_val <= 0:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        # Use the previous window (exclude current bar) for breakout detection
        prev_highs = highs[-(don_win + 1):-1]
        prev_lows = lows[-(don_win + 1):-1]
        if len(prev_highs) < don_win:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        prev_upper = max(prev_highs)
        prev_lower = min(prev_lows)

        lower, middle, upper = dc
        last = closes[-1]
        indicators: Dict[str, Any] = {
            "donchian_lower": lower,
            "donchian_middle": middle,
            "donchian_upper": upper,
            "atr": atr_val,
        }

        if ctx.position and ctx.position.quantity > 0:
            highest_high = max(c.high for c in ctx.candles[-exit_bars:])
            trail_stop = highest_high - atr_mult * atr_val
            if last <= trail_stop:
                return Decision(
                    action=Action.SELL,
                    strength=0.6,
                    reason="trail_stop",
                    indicators=indicators,
                )
            if len(closes) >= exit_bars and last <= min(lows[-exit_bars:]):
                return Decision(
                    action=Action.SELL,
                    strength=0.7,
                    reason="exit_low",
                    indicators=indicators,
                )
            return Decision(
                action=Action.HOLD, reason="no_signal",
                indicators=indicators,
            )

        if last >= prev_upper + atr_mult * atr_val:
            strength = min(1.0, (last - prev_upper) / (atr_val + 1e-9))
            return Decision(
                action=Action.BUY,
                strength=round(strength, 2),
                reason="breakout_upper",
                indicators=indicators,
            )

        if last <= prev_lower - atr_mult * atr_val:
            # Short not supported — hold
            return Decision(
                action=Action.HOLD,
                reason="breakout_lower_no_short",
                indicators=indicators,
            )

        return Decision(
            action=Action.HOLD, reason="no_signal",
            indicators=indicators,
        )


register(MomentumBreakoutStrategy())
