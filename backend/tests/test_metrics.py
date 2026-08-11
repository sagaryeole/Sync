"""Tests for engine/metrics.py — performance metrics from fills and equity snapshots."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from engine.metrics import (
    avg_hold_time_seconds,
    avg_loss,
    avg_win,
    compute_metrics,
    intraday_sharpe,
    max_drawdown_pct,
    profit_factor,
    total_return_pct,
    trade_count,
    win_rate,
    _safe_div,
    _pair_trades,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_BASE_TS = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_fill(side, symbol, qty, price, fee=0.0, ts=None, order_id=1):
    """Create a fill dict as expected by metrics functions."""
    if ts is None:
        ts = _BASE_TS
    return {
        "client_order_id": f"ord-{order_id}",
        "strategy_id": 1,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price,
        "fee": fee,
        "order_type": "MARKET",
        "ts": ts,
    }


def make_snap(equity, ts=None):
    """Create an equity snapshot dict."""
    if ts is None:
        ts = _BASE_TS
    return {"equity": equity, "ts": ts}


# ─── _safe_div ────────────────────────────────────────────────────────────────

class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(10.0, 4.0) == 2.5

    def test_zero_denominator_returns_default(self):
        assert _safe_div(10.0, 0.0) == 0.0

    def test_nan_numerator_returns_default(self):
        assert _safe_div(float("nan"), 2.0) == 0.0

    def test_inf_denominator_returns_default(self):
        assert _safe_div(10.0, float("inf")) == 0.0

    def test_custom_default(self):
        assert _safe_div(10.0, 0.0, default=-1.0) == -1.0


# ─── total_return_pct ─────────────────────────────────────────────────────────

class TestTotalReturn:
    def test_positive_return(self):
        assert total_return_pct(100000, 110000) == pytest.approx(0.10)

    def test_negative_return(self):
        assert total_return_pct(100000, 90000) == pytest.approx(-0.10)

    def test_zero_return(self):
        assert total_return_pct(100000, 100000) == pytest.approx(0.0)

    def test_zero_starting_equity(self):
        """H10: starting_equity == 0 returns 0.0, not inf."""
        assert total_return_pct(0.0, 100000) == 0.0


# ─── win_rate ─────────────────────────────────────────────────────────────────

class TestWinRate:
    def test_no_trades(self):
        assert win_rate([]) == 0.0

    def test_all_winners(self):
        trades = [(None, None, 100), (None, None, 50)]
        assert win_rate(trades) == pytest.approx(1.0)

    def test_all_losers(self):
        trades = [(None, None, -100), (None, None, -50)]
        assert win_rate(trades) == pytest.approx(0.0)

    def test_mixed(self):
        trades = [(None, None, 100), (None, None, -50), (None, None, 30), (None, None, -20)]
        assert win_rate(trades) == pytest.approx(0.5)

    def test_breakeven_not_counted_as_win(self):
        trades = [(None, None, 0.0), (None, None, 100)]
        assert win_rate(trades) == pytest.approx(0.5)


# ─── avg_win / avg_loss ───────────────────────────────────────────────────────

class TestAvgWinLoss:
    def test_avg_win_no_winners(self):
        trades = [(None, None, -100), (None, None, -50)]
        assert avg_win(trades) == 0.0

    def test_avg_win_single(self):
        trades = [(None, None, 100)]
        assert avg_win(trades) == pytest.approx(100.0)

    def test_avg_win_multiple(self):
        trades = [(None, None, 100), (None, None, 200), (None, None, -50)]
        assert avg_win(trades) == pytest.approx(150.0)

    def test_avg_loss_no_losers(self):
        trades = [(None, None, 100), (None, None, 50)]
        assert avg_loss(trades) == 0.0

    def test_avg_loss_multiple(self):
        trades = [(None, None, 100), (None, None, -50), (None, None, -150)]
        assert avg_loss(trades) == pytest.approx(-100.0)


# ─── profit_factor ────────────────────────────────────────────────────────────

class TestProfitFactor:
    def test_no_trades(self):
        assert profit_factor([]) == 0.0

    def test_only_winners(self):
        trades = [(None, None, 100), (None, None, 50)]
        assert profit_factor(trades) == float("inf")

    def test_only_losers(self):
        trades = [(None, None, -100), (None, None, -50)]
        assert profit_factor(trades) == 0.0

    def test_mixed(self):
        trades = [(None, None, 100), (None, None, -50)]
        assert profit_factor(trades) == pytest.approx(2.0)

    def test_breakeven(self):
        trades = [(None, None, 100), (None, None, -100)]
        assert profit_factor(trades) == pytest.approx(1.0)


# ─── max_drawdown_pct ─────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_no_snapshots(self):
        assert max_drawdown_pct([]) == 0.0

    def test_single_snapshot(self):
        assert max_drawdown_pct([make_snap(100000)]) == 0.0

    def test_no_drawdown(self):
        snaps = [make_snap(100000), make_snap(105000), make_snap(110000)]
        assert max_drawdown_pct(snaps) == pytest.approx(0.0)

    def test_simple_drawdown(self):
        snaps = [make_snap(100000), make_snap(90000)]
        assert max_drawdown_pct(snaps) == pytest.approx(0.10)

    def test_recovery_then_new_high(self):
        snaps = [
            make_snap(100000),
            make_snap(90000),   # 10% dd
            make_snap(95000),   # recovering
            make_snap(110000),  # new high
            make_snap(100000),  # 9.09% dd from 110k
        ]
        dd = max_drawdown_pct(snaps)
        assert dd == pytest.approx(0.10, rel=0.01)

    def test_nan_equity_skipped(self):
        snaps = [make_snap(100000), make_snap(float("nan")), make_snap(90000)]
        assert max_drawdown_pct(snaps) == pytest.approx(0.10)


# ─── intraday_sharpe ──────────────────────────────────────────────────────────

class TestIntradaySharpe:
    def test_no_snapshots(self):
        assert intraday_sharpe([]) == 0.0

    def test_single_snapshot(self):
        assert intraday_sharpe([make_snap(100000)]) == 0.0

    def test_constant_equity(self):
        """No variance → std=0 → sharpe=0."""
        snaps = [make_snap(100000), make_snap(100000), make_snap(100000)]
        assert intraday_sharpe(snaps) == 0.0

    def test_positive_trend(self):
        """Monotonically increasing equity → positive sharpe."""
        snaps = [make_snap(100000), make_snap(101000), make_snap(102000), make_snap(103000)]
        sharpe = intraday_sharpe(snaps)
        assert sharpe > 0

    def test_negative_trend(self):
        snaps = [make_snap(100000), make_snap(99000), make_snap(98000), make_snap(97000)]
        sharpe = intraday_sharpe(snaps)
        assert sharpe < 0

    def test_zero_equity_returns_zero(self):
        snaps = [make_snap(0.0), make_snap(100000)]
        assert intraday_sharpe(snaps) == 0.0


# ─── trade_count ───────────────────────────────────────────────────────────────

class TestTradeCount:
    def test_empty(self):
        assert trade_count([]) == 0

    def test_multiple(self):
        trades = [(None, None, 100), (None, None, -50), (None, None, 30)]
        assert trade_count(trades) == 3


# ─── avg_hold_time_seconds ─────────────────────────────────────────────────────

class TestAvgHoldTime:
    def test_no_trades(self):
        assert avg_hold_time_seconds([]) == 0.0

    def test_no_timestamps(self):
        trades = [(None, None, 100)]
        assert avg_hold_time_seconds(trades) == 0.0

    def test_single_trade(self):
        buy_ts = _BASE_TS
        sell_ts = _BASE_TS + timedelta(seconds=60)
        buy = make_fill("BUY", "BTC", 1.0, 50000, ts=buy_ts)
        sell = make_fill("SELL", "BTC", 1.0, 51000, ts=sell_ts, order_id=2)
        trades = [(buy, sell, 100)]
        assert avg_hold_time_seconds(trades) == pytest.approx(60.0)

    def test_multiple_trades(self):
        buy1 = make_fill("BUY", "BTC", 1.0, 50000, ts=_BASE_TS)
        sell1 = make_fill("SELL", "BTC", 1.0, 51000, ts=_BASE_TS + timedelta(seconds=60), order_id=2)
        buy2 = make_fill("BUY", "ETH", 2.0, 3000, ts=_BASE_TS, order_id=3)
        sell2 = make_fill("SELL", "ETH", 2.0, 3050, ts=_BASE_TS + timedelta(seconds=120), order_id=4)
        trades = [(buy1, sell1, 100), (buy2, sell2, 100)]
        assert avg_hold_time_seconds(trades) == pytest.approx(90.0)


# ─── _pair_trades (FIFO matching) ─────────────────────────────────────────────

class TestPairTrades:
    def test_no_fills(self):
        assert _pair_trades([]) == []

    def test_only_buys(self):
        fills = [make_fill("BUY", "BTC", 1.0, 50000)]
        assert _pair_trades(fills) == []

    def test_simple_round_trip(self):
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, order_id=1),
            make_fill("SELL", "BTC", 1.0, 51000, order_id=2),
        ]
        trades = _pair_trades(fills)
        assert len(trades) == 1
        _, _, pnl = trades[0]
        assert pnl == pytest.approx(1000.0)

    def test_partial_close(self):
        """Buy 2, sell 1, sell 1 → two closed trades."""
        fills = [
            make_fill("BUY", "BTC", 2.0, 50000, order_id=1),
            make_fill("SELL", "BTC", 1.0, 51000, order_id=2),
            make_fill("SELL", "BTC", 1.0, 52000, order_id=3),
        ]
        trades = _pair_trades(fills)
        assert len(trades) == 2
        assert trades[0][2] == pytest.approx(1000.0)
        assert trades[1][2] == pytest.approx(2000.0)

    def test_fifo_matching(self):
        """Buy at 50k, buy at 52k, sell 2 → first lot matched first."""
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, order_id=1),
            make_fill("BUY", "BTC", 1.0, 52000, order_id=2),
            make_fill("SELL", "BTC", 2.0, 51000, order_id=3),
        ]
        trades = _pair_trades(fills)
        assert len(trades) == 2
        # First lot: 51000 - 50000 = 1000 profit
        assert trades[0][2] == pytest.approx(1000.0)
        # Second lot: 51000 - 52000 = -1000 loss
        assert trades[1][2] == pytest.approx(-1000.0)

    def test_fee_deducted_from_pnl(self):
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, order_id=1),
            make_fill("SELL", "BTC", 1.0, 51000, fee=50.0, order_id=2),
        ]
        trades = _pair_trades(fills)
        assert len(trades) == 1
        # 1000 profit - 50 fee = 950
        assert trades[0][2] == pytest.approx(950.0)

    def test_multi_symbol(self):
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, order_id=1),
            make_fill("BUY", "ETH", 2.0, 3000, order_id=2),
            make_fill("SELL", "BTC", 1.0, 51000, order_id=3),
            make_fill("SELL", "ETH", 2.0, 3100, order_id=4),
        ]
        trades = _pair_trades(fills)
        assert len(trades) == 2
        pnls = sorted(t[2] for t in trades)
        assert pnls[0] == pytest.approx(200.0)   # ETH: (3100-3000)*2
        assert pnls[1] == pytest.approx(1000.0)  # BTC: 51000-50000


# ─── compute_metrics (integration) ─────────────────────────────────────────────

class TestComputeMetrics:
    def test_empty(self):
        result = compute_metrics([], [], 100000, 100000)
        assert result["total_return_pct"] == 0.0
        assert result["win_rate"] == 0.0
        assert result["trade_count"] == 0
        assert result["profit_factor"] == 0.0
        assert result["max_drawdown_pct"] == 0.0
        assert result["intraday_sharpe"] == 0.0

    def test_full_scenario(self):
        """A realistic scenario with winning and losing trades."""
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, fee=5.0, ts=_BASE_TS, order_id=1),
            make_fill("SELL", "BTC", 1.0, 51000, fee=5.1, ts=_BASE_TS + timedelta(seconds=60), order_id=2),
            make_fill("BUY", "ETH", 2.0, 3000, fee=0.6, ts=_BASE_TS + timedelta(seconds=120), order_id=3),
            make_fill("SELL", "ETH", 2.0, 2950, fee=0.59, ts=_BASE_TS + timedelta(seconds=180), order_id=4),
        ]
        snaps = [
            make_snap(100000, ts=_BASE_TS),
            make_snap(101000, ts=_BASE_TS + timedelta(seconds=30)),
            make_snap(100500, ts=_BASE_TS + timedelta(seconds=60)),
            make_snap(100500, ts=_BASE_TS + timedelta(seconds=90)),
            make_snap(99500, ts=_BASE_TS + timedelta(seconds=120)),
            make_snap(99000, ts=_BASE_TS + timedelta(seconds=150)),
            make_snap(99500, ts=_BASE_TS + timedelta(seconds=180)),
        ]
        result = compute_metrics(fills, snaps, 100000, 99500)

        assert result["trade_count"] == 2
        assert result["total_return_pct"] == pytest.approx(-0.005, rel=0.01)
        assert result["win_rate"] == pytest.approx(0.5)
        assert result["avg_win"] > 0
        assert result["avg_loss"] < 0
        assert result["profit_factor"] > 0
        assert result["max_drawdown_pct"] > 0
        assert result["avg_hold_time_seconds"] == pytest.approx(60.0)

    def test_all_winners(self):
        fills = [
            make_fill("BUY", "BTC", 1.0, 50000, order_id=1),
            make_fill("SELL", "BTC", 1.0, 51000, order_id=2),
            make_fill("BUY", "ETH", 2.0, 3000, order_id=3),
            make_fill("SELL", "ETH", 2.0, 3100, order_id=4),
        ]
        result = compute_metrics(fills, [], 100000, 102200)
        assert result["win_rate"] == pytest.approx(1.0)
        assert result["profit_factor"] == float("inf")
        assert result["trade_count"] == 2
