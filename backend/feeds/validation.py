"""Tick validation gate — every Tick must pass through validate_tick() before reaching MarketState.

Implements hardening items:
  H1 — reject NaN/Infinity, non-positive prices, bad bid/ask, stale timestamps
  H4 — reject ticks that move more than max_tick_move_pct from the last accepted price
       unless K=2 consecutive ticks confirm the move (then it's real, adopt it)

This module is the single chokepoint: feeds parse JSON, but this is where the value
is trusted (or rejected) before it enters the engine.
"""
import logging
import math
from datetime import datetime, timezone
from typing import Dict, Optional

from feeds.base import Tick

logger = logging.getLogger("feed.validation")

# --- Config (module-level so tests can monkeypatch) ---

#: Maximum age of a tick's timestamp relative to server clock (seconds).
MAX_TICK_AGE_SECONDS = 60

#: Maximum future drift allowed (seconds) — exchange clocks may be slightly ahead.
MAX_TICK_FUTURE_SECONDS = 60

#: Maximum single-tick move as a fraction of the last accepted price (0.10 = 10%).
MAX_TICK_MOVE_PCT = 0.10

#: Number of consecutive confirming ticks required to adopt a large move.
CONFIRM_TICKS = 2


class TickValidationError(Exception):
    """Raised when a tick fails validation. Never reaches MarketState."""
    pass


def _is_finite(value: Optional[float]) -> bool:
    """True if value is not None and not NaN/Infinity."""
    if value is None:
        return False
    return math.isfinite(value)


def validate_tick(
    tick: Tick,
    last_accepted_prices: Dict[str, float],
    pending_confirmations: Dict[str, int],
    now: Optional[datetime] = None,
) -> Tick:
    """Validate a tick before it enters MarketState.

    Args:
        tick: The candidate Tick.
        last_accepted_prices: {symbol: price} of the last accepted tick per symbol.
        pending_confirmations: {symbol: count} of consecutive large-move ticks awaiting confirmation.
        now: Override for testability; defaults to datetime.now(timezone.utc).

    Returns:
        The tick if it passes validation.

    Raises:
        TickValidationError: If the tick fails any check.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # --- H1: NaN / Infinity rejection ---
    if not _is_finite(tick.price):
        raise TickValidationError(
            f"{tick.symbol}: rejected non-finite price={tick.price} from {tick.source}"
        )

    if tick.price <= 0:
        raise TickValidationError(
            f"{tick.symbol}: rejected non-positive price={tick.price} from {tick.source}"
        )

    if tick.bid is not None and not _is_finite(tick.bid):
        raise TickValidationError(
            f"{tick.symbol}: rejected non-finite bid={tick.bid} from {tick.source}"
        )

    if tick.ask is not None and not _is_finite(tick.ask):
        raise TickValidationError(
            f"{tick.symbol}: rejected non-finite ask={tick.ask} from {tick.source}"
        )

    # bid <= ask when both present
    if tick.bid is not None and tick.ask is not None and tick.bid > tick.ask:
        raise TickValidationError(
            f"{tick.symbol}: rejected bid={tick.bid} > ask={tick.ask} from {tick.source}"
        )

    # --- H1: timestamp sanity ---
    if tick.ts is None:
        raise TickValidationError(f"{tick.symbol}: rejected None timestamp from {tick.source}")

    age = (now - tick.ts).total_seconds()
    if age > MAX_TICK_AGE_SECONDS:
        raise TickValidationError(
            f"{tick.symbol}: rejected stale tick (age={age:.1f}s > {MAX_TICK_AGE_SECONDS}s) from {tick.source}"
        )
    if age < -MAX_TICK_FUTURE_SECONDS:
        raise TickValidationError(
            f"{tick.symbol}: rejected future tick (age={age:.1f}s < -{MAX_TICK_FUTURE_SECONDS}s) from {tick.source}"
        )

    # --- H4: tick sanity band ---
    last_price = last_accepted_prices.get(tick.symbol)
    if last_price is not None and last_price > 0:
        move_pct = abs(tick.price - last_price) / last_price

        if move_pct > MAX_TICK_MOVE_PCT:
            # Large move — needs CONFIRM_TICKS consecutive confirmations
            count = pending_confirmations.get(tick.symbol, 0) + 1
            pending_confirmations[tick.symbol] = count

            if count < CONFIRM_TICKS:
                raise TickValidationError(
                    f"{tick.symbol}: rejected large move {move_pct:.2%} "
                    f"(price={tick.price} vs last={last_price}) "
                    f"confirmation {count}/{CONFIRM_TICKS} from {tick.source}"
                )
            else:
                # Confirmed — adopt it, reset counter
                pending_confirmations[tick.symbol] = 0
                logger.info(
                    "%s: large move %.2f%% confirmed after %d ticks — adopting",
                    tick.symbol, move_pct, CONFIRM_TICKS,
                )
        else:
            # Normal move — reset any pending confirmation counter
            if tick.symbol in pending_confirmations:
                pending_confirmations[tick.symbol] = 0

    return tick
