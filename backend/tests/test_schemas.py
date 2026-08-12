"""Tests for strategies/schemas.py — H9 param validation."""
import pytest

from strategies.schemas import (
    SMACrossoverParams,
    RSIReversionParams,
    MomentumBreakoutParams,
    validate_params,
    SCHEMAS,
)


class TestSMACrossoverParams:
    def test_defaults(self):
        p = SMACrossoverParams()
        assert p.fast == 9
        assert p.slow == 21

    def test_valid(self):
        p = SMACrossoverParams(fast=5, slow=20)
        assert p.fast == 5
        assert p.slow == 20

    def test_rejects_negative(self):
        with pytest.raises(Exception):
            SMACrossoverParams(fast=-1, slow=21)

    def test_rejects_slow_le_fast(self):
        with pytest.raises(Exception):
            SMACrossoverParams(fast=21, slow=9)


class TestRSIReversionParams:
    def test_defaults(self):
        p = RSIReversionParams()
        assert p.period == 14
        assert p.oversold == 30.0
        assert p.overbought == 70.0
        assert p.exit == 50.0

    def test_rejects_oversold_ge_overbought(self):
        with pytest.raises(Exception):
            RSIReversionParams(oversold=70, overbought=30)


class TestMomentumBreakoutParams:
    def test_defaults(self):
        p = MomentumBreakoutParams()
        assert p.donchian_window == 20
        assert p.atr_period == 14
        assert p.atr_multiplier == 1.0
        assert p.exit_bars == 10


class TestValidateParams:
    def test_validates_known_strategy(self):
        result = validate_params("sma_crossover", {"fast": 5, "slow": 20})
        assert result == {"fast": 5, "slow": 20}

    def test_rejects_invalid_for_strategy(self):
        with pytest.raises(Exception):
            validate_params("sma_crossover", {"fast": 21, "slow": 9})

    def test_passes_through_unknown_strategy(self):
        result = validate_params("unknown", {"anything": "goes"})
        assert result == {"anything": "goes"}

    def test_rejects_out_of_range(self):
        with pytest.raises(Exception):
            validate_params("sma_crossover", {"fast": 1000, "slow": 20})
