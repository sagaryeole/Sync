"""RSI mean-reversion strategy.

Buy when RSI drops below the oversold threshold.
Sell when RSI rises above the overbought threshold.
Exit positions when RSI crosses back toward the center line (50).
"""
from __future__ import annotations

from typing import Any, Dict

from strategies.base import Action, Decision, StrategyContext
from strategies.indicators import rsi
from strategies.registry import register


class RSIReversionStrategy:
    key = "rsi_reversion"
    name = "RSI Reversion"
    default_params = {
        "period": 14, "oversold": 30, "overbought": 70, "exit": 50,
    }
    warmup_bars = 15

    def evaluate(self, ctx: StrategyContext) -> Decision:
        params = ctx.params or self.default_params
        period = int(params.get("period", 14))
        oversold = float(params.get("oversold", 30))
        exit_level = float(params.get("exit", 50))

        closes = [c.close for c in ctx.candles]
        rsi_val = rsi(closes, period)
        if rsi_val is None:
            return Decision(action=Action.HOLD, reason="insufficient_data")

        indicators: Dict[str, Any] = {"rsi": rsi_val}

        if ctx.position and ctx.position.quantity > 0:
            if rsi_val >= exit_level:
                return Decision(
                    action=Action.SELL,
                    strength=0.5,
                    reason="rsi_exit",
                    indicators=indicators,
                )
            return Decision(
                action=Action.HOLD, reason="no_signal",
                indicators=indicators,
            )

        if rsi_val < oversold:
            strength = max(0.0, min(1.0, (oversold - rsi_val) / oversold))
            return Decision(
                action=Action.BUY,
                strength=round(strength, 2),
                reason="rsi_oversold",
                indicators=indicators,
            )

        return Decision(
            action=Action.HOLD, reason="no_signal",
            indicators=indicators,
        )


register(RSIReversionStrategy())
