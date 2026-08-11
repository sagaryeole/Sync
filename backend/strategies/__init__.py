from strategies.indicators import sma, ema, rsi, atr, macd, bbands, donchian

# Import for registration side effects only — each module calls
# strategies.registry.register() on its own class at import time.
import strategies.sma_crossover  # noqa: F401
import strategies.rsi_reversion  # noqa: F401
import strategies.momentum_breakout  # noqa: F401
