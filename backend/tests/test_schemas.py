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

    def test_dry_run_survives_validation(self):
        """V4 shadow mode: dry_run isn't a field on any per-strategy schema —
        it must not be dropped by pydantic's default extra="ignore"."""
        result = validate_params("sma_crossover", {"fast": 5, "slow": 20, "dry_run": True})
        assert result["dry_run"] is True
        assert result["fast"] == 5 and result["slow"] == 20

    def test_dry_run_absent_when_not_set(self):
        result = validate_params("sma_crossover", {"fast": 5, "slow": 20})
        assert "dry_run" not in result

    def test_dry_run_false_is_not_included(self):
        """Only an explicit True is carried through, so params_json stays
        minimal for the common (live) case."""
        result = validate_params("sma_crossover", {"fast": 5, "slow": 20, "dry_run": False})
        assert "dry_run" not in result

    def test_dry_run_survives_for_every_registered_strategy(self):
        """Same guarantee for every schema, not just the one tested above —
        this is what would have caught the original bug on any strategy."""
        from strategies.schemas import SCHEMAS
        for key in SCHEMAS:
            result = validate_params(key, {"dry_run": True})
            assert result.get("dry_run") is True, f"dry_run dropped for {key}"

    def test_dry_run_survives_passthrough_for_unknown_strategy(self):
        result = validate_params("unknown", {"anything": "goes", "dry_run": True})
        assert result["dry_run"] is True
        assert result["anything"] == "goes"

    def test_rejects_out_of_range(self):
        with pytest.raises(Exception):
            validate_params("sma_crossover", {"fast": 1000, "slow": 20})
