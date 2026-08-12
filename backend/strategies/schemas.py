"""Pydantic schemas for strategy parameters with validation bounds.

H9: every strategy parameter is validated before use so that values like
`{"period": 1000000000}` cannot hang a scheduler thread or cause an
indicator to throw.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SMACrossoverParams(BaseModel):
    fast: int = Field(default=9, ge=1, le=200)
    slow: int = Field(default=21, ge=2, le=500)

    @field_validator("slow")
    @classmethod
    def slow_greater_than_fast(cls, v, info):
        if "fast" in info.data and v <= info.data["fast"]:
            raise ValueError("slow must be greater than fast")
        return v


class RSIReversionParams(BaseModel):
    period: int = Field(default=14, ge=1, le=200)
    oversold: float = Field(default=30.0, ge=0.0, le=100.0)
    overbought: float = Field(default=70.0, ge=0.0, le=100.0)
    exit: float = Field(default=50.0, ge=0.0, le=100.0)

    @field_validator("overbought")
    @classmethod
    def overbought_greater_than_oversold(cls, v, info):
        if "oversold" in info.data and v <= info.data["oversold"]:
            raise ValueError("overbought must be greater than oversold")
        return v


class MomentumBreakoutParams(BaseModel):
    donchian_window: int = Field(default=20, ge=1, le=200)
    atr_period: int = Field(default=14, ge=1, le=200)
    atr_multiplier: float = Field(default=1.0, ge=0.0, le=10.0)
    exit_bars: int = Field(default=10, ge=1, le=500)


class TrendEnsembleParams(BaseModel):
    """H9 bounds for the vol-targeted trend ensemble.

    `pairs` is the one field that needs real structural validation — it is a
    nested list from untrusted JSON, and an unbounded span would make the
    O(n) series work unbounded too.
    """
    pairs: List[List[int]] = Field(default=[[15, 45], [30, 90], [60, 180]])
    vol_window: int = Field(default=60, ge=5, le=2000)
    norm_window: int = Field(default=100, ge=5, le=2000)
    entry_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    exit_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    target_vol: float = Field(default=0.30, gt=0.0, le=5.0)
    max_vol_scalar: float = Field(default=1.5, gt=0.0, le=10.0)
    taker_fee_bps: float = Field(default=10.0, ge=0.0, le=1000.0)
    slippage_bps: float = Field(default=1.5, ge=0.0, le=1000.0)
    min_edge_multiple: float = Field(default=2.0, ge=0.0, le=100.0)

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v):
        if not v or len(v) > 10:
            raise ValueError("pairs must contain between 1 and 10 entries")
        for pair in v:
            if len(pair) != 2:
                raise ValueError("each pair must be [fast, slow]")
            fast, slow = pair
            if not (1 <= fast < slow <= 5000):
                raise ValueError("require 1 <= fast < slow <= 5000")
        return v

    @field_validator("exit_threshold")
    @classmethod
    def exit_below_entry(cls, v, info):
        # The hysteresis gap is the whole point — an exit threshold at or
        # above the entry threshold collapses the no-trade band and puts the
        # turnover problem straight back.
        if "entry_threshold" in info.data and v >= info.data["entry_threshold"]:
            raise ValueError("exit_threshold must be below entry_threshold")
        return v


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SCHEMAS = {
    "sma_crossover": SMACrossoverParams,
    "rsi_reversion": RSIReversionParams,
    "momentum_breakout": MomentumBreakoutParams,
    "trend_ensemble": TrendEnsembleParams,
}


def get_schema(key: str):
    """Return the pydantic model for a strategy key, or None."""
    return SCHEMAS.get(key)


def validate_params(key: str, params: dict) -> dict:
    """Validate and coerce params for a strategy.

    ``dry_run`` (V4 shadow mode — evaluate and log signals, never submit an
    order; see engine/runner.py) is handled here, outside each per-strategy
    schema. It is a runner-level flag, not one of a strategy's own numeric
    knobs, and every SCHEMAS entry above is a closed pydantic model with no
    ``dry_run`` field — passing it straight to ``schema(**params)`` would hit
    pydantic's default ``extra="ignore"`` and silently vanish from the
    validated output. A dropped dry_run flag doesn't fail loudly; it just
    means the "shadow mode" strategy quietly starts trading with real
    capital, which is the one failure mode V4 exists to prevent. Stripping
    it before validation and re-attaching it after closes that gap for every
    current and future strategy schema, with no per-schema field to remember.

    Returns the validated params dict on success (with ``dry_run`` reattached
    when it was set). Raises pydantic.ValidationError on failure.
    """
    dry_run = bool(params.get("dry_run", False))
    strategy_params = {k: v for k, v in params.items() if k != "dry_run"}

    schema = get_schema(key)
    if schema is None:
        validated_params = strategy_params
    else:
        validated_params = schema(**strategy_params).model_dump()

    if dry_run:
        validated_params["dry_run"] = True
    return validated_params
