"""SMA crossover strategy.

Buy when fast SMA crosses above slow SMA (golden cross).
Sell when fast SMA crosses below slow SMA (death cross).
Exits are the inverse signal — no separate stop/take-profit here.

A true cross requires comparing the current bar's SMA relationship to the
previous bar's — not just checking fast > slow (which would fire every bar
the condition holds, not just the crossing bar).
"""
from __future__ import annotations

from typing import Any, Dict

from strategies.base import Action, Decision, StrategyContext
from strategies.indicators import sma
from strategies.registry import register


class SMACrossoverStrategy:
    key = "sma_crossover"
    name = "SMA Crossover"
    default_params = {"fast": 9, "slow": 21}
    warmup_bars = 22  # need slow_window + 1 for cross detection

    def evaluate(self, ctx: StrategyContext) -> Decision:
        params = ctx.params or self.default_params
        fast_win = int(params.get("fast", 9))
        slow_win = int(params.get("slow", 21))

        closes = [c.close for c in ctx.candles]
        if len(closes) < slow_win + 1:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        fast = sma(closes, fast_win)
        slow = sma(closes, slow_win)
        if fast is None or slow is None:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        # Previous-bar SMAs for cross detection
        prev_closes = closes[:-1]
        fast_prev = sma(prev_closes, fast_win)
        slow_prev = sma(prev_closes, slow_win)
        if fast_prev is None or slow_prev is None:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        indicators: Dict[str, Any] = {
            "sma_fast": round(fast, 6),
            "sma_slow": round(slow, 6),
        }

        # Golden cross: fast crosses above slow
        golden = fast_prev <= slow_prev and fast > slow
        # Death cross: fast crosses below slow
        death = fast_prev >= slow_prev and fast < slow

        if golden:
            strength = min(1.0, abs(fast - slow) / (slow + 1e-9) * 10)
            return Decision(
                action=Action.BUY,
                strength=round(strength, 2),
                reason="golden_cross",
                indicators=indicators,
            )

        if death:
            strength = min(1.0, abs(slow - fast) / (slow + 1e-9) * 10)
            return Decision(
                action=Action.SELL,
                strength=round(strength, 2),
                reason="death_cross",
                indicators=indicators,
            )

        # If holding a position and no cross, check if we should exit
        # on the inverse condition (fast still below slow while long)
        if ctx.position and ctx.position.quantity > 0:
            if fast < slow:
                return Decision(
                    action=Action.SELL,
                    strength=0.5,
                    reason="fast_below_slow",
                    indicators=indicators,
                )
            return Decision(
                action=Action.HOLD, reason="no_signal",
                indicators=indicators,
            )

        return Decision(
            action=Action.HOLD, reason="no_signal",
            indicators=indicators,
        )


register(SMACrossoverStrategy())
