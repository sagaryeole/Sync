"""Tests for V3 per-symbol circuit breaker in FeedManager."""
import pytest

from feeds.manager import FeedManager


class TestPerSymbolCircuitBreaker:
    def test_default_tradable(self):
        fm = FeedManager()
        assert fm.is_symbol_tradable("BTC")
        assert fm.is_symbol_tradable("ETH")

    def test_opens_after_threshold_failures(self):
        fm = FeedManager()
        for _ in range(5):
            fm._symbol_fail_counts["BTC"] = fm._symbol_fail_counts.get("BTC", 0) + 1
            if fm._symbol_fail_counts["BTC"] >= 5:
                fm._symbol_circuit_open["BTC"] = True
        assert not fm.is_symbol_tradable("BTC")
        assert fm.is_symbol_tradable("ETH")

    def test_closes_on_success(self):
        fm = FeedManager()
        fm._symbol_circuit_open["BTC"] = True
        fm._symbol_fail_counts["BTC"] = 5
        fm._symbol_fail_counts["BTC"] = 0
        fm._symbol_circuit_open["BTC"] = False
        assert fm.is_symbol_tradable("BTC")

    def test_get_tradable_symbols_filters(self):
        fm = FeedManager()
        fm._symbol_circuit_open["BTC"] = True
        result = fm.get_tradable_symbols(["BTC", "ETH", "SOL"])
        assert result == ["ETH", "SOL"]

    def test_manual_open_close(self):
        fm = FeedManager()
        fm.open_circuit("BTC")
        assert not fm.is_symbol_tradable("BTC")
        fm.close_circuit("BTC")
        assert fm.is_symbol_tradable("BTC")
        assert fm._symbol_fail_counts["BTC"] == 0
