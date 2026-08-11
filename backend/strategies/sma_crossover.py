"""SMA crossover strategy.

Buy when fast SMA crosses above slow SMA (golden cross).
Sell when fast SMA crosses below slow SMA (death cross).
Exits are the inverse signal — no separate stop/take-profit here.
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
    warmup_bars = 21

    def evaluate(self, ctx: StrategyContext) -> Decision:
        params = ctx.params or self.default_params
        fast_win = int(params.get("fast", 9))
        slow_win = int(params.get("slow", 21))

        closes = [c.close for c in ctx.candles]
        if len(closes) < slow_win:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        fast = sma(closes, fast_win)
        slow = sma(closes, slow_win)
        if fast is None or slow is None:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        indicators: Dict[str, Any] = {
            "sma_fast": fast,
            "sma_slow": slow,
        }

        if ctx.position and ctx.position.quantity > 0:
            if fast < slow:
                return Decision(
                    action=Action.SELL,
                    strength=0.6,
                    reason="death_cross",
                    indicators=indicators,
                )
            return Decision(
                action=Action.HOLD, reason="no_signal",
                indicators=indicators,
            )

        if fast > slow:
            return Decision(
                action=Action.BUY,
                strength=0.7,
                reason="golden_cross",
                indicators=indicators,
            )

        return Decision(
            action=Action.HOLD, reason="no_signal",
            indicators=indicators,
        )


register(SMACrossoverStrategy())
