"""Pydantic schemas for strategy parameters with validation bounds.

H9: every strategy parameter is validated before use so that values like
`{"period": 1000000000}` cannot hang a scheduler thread or cause an
indicator to throw.
"""
from typing import Optional

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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SCHEMAS = {
    "sma_crossover": SMACrossoverParams,
    "rsi_reversion": RSIReversionParams,
    "momentum_breakout": MomentumBreakoutParams,
}


def get_schema(key: str):
    """Return the pydantic model for a strategy key, or None."""
    return SCHEMAS.get(key)


def validate_params(key: str, params: dict) -> dict:
    """Validate and coerce params for a strategy.

    Returns the validated params dict on success.
    Raises pydantic.ValidationError on failure.
    """
    schema = get_schema(key)
    if schema is None:
        return params
    validated = schema(**params)
    return validated.model_dump()
