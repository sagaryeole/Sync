"""Performance metrics computed from fills and equity snapshots.

All metrics are computed from the append-only fills log (H5 source of truth)
and equity snapshots. No state is stored here — these are pure functions
over lists of fills and snapshots.

Labels:
  - "intraday Sharpe" is explicitly labelled as such — 30s sampling is noisy
    and not comparable to a daily Sharpe ratio.
  - All percentages are returned as fractions (0.05 = 5%), not whole numbers.

H10: every division is guarded — returns 0.0 or a defined value, never inf/NaN.
"""
import math
from typing import Dict, List, Optional, Tuple

_EPS = 1e-9


def _is_finite(value: float) -> bool:
    """H1/H10: guard against NaN/Inf."""
    return value is not None and math.isfinite(value)


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """H10: safe division that never produces inf/NaN."""
    if not _is_finite(numerator) or not _is_finite(denominator):
        return default
    if abs(denominator) < _EPS:
        return default
    result = numerator / denominator
    if not _is_finite(result):
        return default
    return result


def _pair_trades(
    fills: List[Dict],
) -> List[Tuple[Dict, Dict, float]]:
    """Pair BUY fills with their corresponding SELL fills (FIFO matching).

    Returns a list of (buy_fill, sell_fill, realized_pnl) tuples.
    A single BUY may be partially closed by multiple SELLs and vice versa.
    """
    # Build open lots per symbol: list of (buy_fill, price, remaining_qty)
    open_lots: Dict[str, List[Tuple[Dict, float, float]]] = {}
    closed_trades: List[Tuple[Dict, Dict, float]] = []

    for fill in fills:
        symbol = fill.get("symbol", "")
        side = fill.get("side", "").upper()
        qty = fill.get("quantity", 0.0)
        price = fill.get("price", 0.0)
        fee = fill.get("fee", 0.0)

        if side == "BUY":
            lots = open_lots.setdefault(symbol, [])
            lots.append((fill, price, qty))
        elif side == "SELL":
            lots = open_lots.get(symbol, [])
            remaining = qty
            while remaining > _EPS and lots:
                buy_fill, buy_price, buy_qty = lots[0]
                matched = min(buy_qty, remaining)
                # Realized P&L for this partial close
                realized = matched * (price - buy_price)
                # Pro-rate the sell fee
                sell_fee_portion = fee * (matched / qty) if qty > _EPS else 0.0
                realized -= sell_fee_portion
                closed_trades.append((buy_fill, fill, realized))

                remaining -= matched
                buy_qty -= matched
                if buy_qty <= _EPS:
                    lots.pop(0)
                else:
                    lots[0] = (buy_fill, buy_price, buy_qty)

    return closed_trades


def total_return_pct(
    starting_equity: float, ending_equity: float
) -> float:
    """Total return as a fraction. H10: guarded against starting_equity == 0."""
    return _safe_div(ending_equity - starting_equity, starting_equity)


def win_rate(closed_trades: List[Tuple]) -> float:
    """Fraction of closed trades that were profitable. Returns 0.0 if no trades."""
    if not closed_trades:
        return 0.0
    wins = sum(1 for _, _, pnl in closed_trades if pnl > _EPS)
    return _safe_div(wins, len(closed_trades))


def avg_win(closed_trades: List[Tuple]) -> float:
    """Average profit per winning trade. Returns 0.0 if no winners."""
    winners = [pnl for _, _, pnl in closed_trades if pnl > _EPS]
    if not winners:
        return 0.0
    return sum(winners) / len(winners)


def avg_loss(closed_trades: List[Tuple]) -> float:
    """Average loss per losing trade. Returns 0.0 if no losers."""
    losers = [pnl for _, _, pnl in closed_trades if pnl < -_EPS]
    if not losers:
        return 0.0
    return sum(losers) / len(losers)


def profit_factor(closed_trades: List[Tuple]) -> float:
    """Gross profit / gross loss. Returns inf if no losses (use _safe_div).

    Convention: returns 0.0 if no winning trades, float('inf') if wins but no losses.
    """
    gross_profit = sum(pnl for _, _, pnl in closed_trades if pnl > 0)
    gross_loss = abs(sum(pnl for _, _, pnl in closed_trades if pnl < 0))

    if gross_loss < _EPS:
        if gross_profit > _EPS:
            return float("inf")
        return 0.0
    return _safe_div(gross_profit, gross_loss)


def max_drawdown_pct(equity_snapshots: List[Dict]) -> float:
    """Maximum drawdown from peak equity as a fraction.

    Expects equity_snapshots as a list of dicts with 'equity' key,
    ordered by timestamp ascending.
    Returns 0.0 if fewer than 2 snapshots.
    """
    if len(equity_snapshots) < 2:
        return 0.0

    peak = equity_snapshots[0].get("equity", 0.0)
    if not _is_finite(peak) or peak <= 0:
        peak = 0.0
    max_dd = 0.0

    for snap in equity_snapshots:
        eq = snap.get("equity", 0.0)
        if not _is_finite(eq) or eq <= 0:
            continue
        if eq > peak:
            peak = eq
        if peak > _EPS:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd


def intraday_sharpe(equity_snapshots: List[Dict]) -> float:
    """Intraday Sharpe ratio from equity snapshots.

    ⚠️  Labelled 'intraday' — 30s sampling is noisy and NOT comparable to a
    daily Sharpe. This is a rough risk-adjusted return proxy.

    Computes the mean and std of per-period returns, then mean/std.
    Annualization is NOT applied — this is a raw intraday figure.

    Returns 0.0 if fewer than 2 snapshots or if std is 0.
    """
    if len(equity_snapshots) < 2:
        return 0.0

    returns: List[float] = []
    prev_eq = equity_snapshots[0].get("equity", 0.0)
    if not _is_finite(prev_eq) or prev_eq <= 0:
        return 0.0

    for snap in equity_snapshots[1:]:
        eq = snap.get("equity", 0.0)
        if not _is_finite(eq) or eq <= 0:
            continue
        r = _safe_div(eq - prev_eq, prev_eq)
        returns.append(r)
        prev_eq = eq

    if len(returns) < 2:
        return 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)

    return _safe_div(mean, std)


def trade_count(closed_trades: List[Tuple]) -> int:
    """Number of closed trades."""
    return len(closed_trades)


def avg_hold_time_seconds(closed_trades: List[Tuple]) -> float:
    """Average hold time in seconds.

    Expects closed_trades as (buy_fill, sell_fill, pnl) where fills have 'ts'.
    If buy_fill is None (unpaired), uses sell_fill ts only — returns 0.
    Returns 0.0 if no trades with valid timestamps.
    """
    if not closed_trades:
        return 0.0

    total_seconds = 0.0
    count = 0
    for buy_fill, sell_fill, _ in closed_trades:
        if buy_fill is None or sell_fill is None:
            continue
        buy_ts = buy_fill.get("ts")
        sell_ts = sell_fill.get("ts")
        if buy_ts is None or sell_ts is None:
            continue
        try:
            delta = (sell_ts - buy_ts).total_seconds()
            if delta >= 0:
                total_seconds += delta
                count += 1
        except (AttributeError, TypeError):
            continue

    if count == 0:
        return 0.0
    return total_seconds / count


def compute_metrics(
    fills: List[Dict],
    equity_snapshots: List[Dict],
    starting_equity: float,
    ending_equity: float,
) -> Dict:
    """Compute all performance metrics from fills and equity snapshots.

    Args:
        fills: List of fill dicts with keys: symbol, side, quantity, price, fee, ts.
               Must be ordered by timestamp ascending.
        equity_snapshots: List of dicts with 'equity' key, ordered by ts ascending.
        starting_equity: Equity at the start of the period.
        ending_equity: Equity at the end of the period.

    Returns:
        Dict with all metrics. All percentages are fractions (0.05 = 5%).
    """
    closed = _pair_trades(fills)

    return {
        "total_return_pct": total_return_pct(starting_equity, ending_equity),
        "win_rate": win_rate(closed),
        "avg_win": avg_win(closed),
        "avg_loss": avg_loss(closed),
        "profit_factor": profit_factor(closed),
        "max_drawdown_pct": max_drawdown_pct(equity_snapshots),
        "intraday_sharpe": intraday_sharpe(equity_snapshots),
        "trade_count": trade_count(closed),
        "avg_hold_time_seconds": avg_hold_time_seconds(closed),
    }
