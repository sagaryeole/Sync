"""Pure-Python technical indicators.

All functions operate on plain lists of floats and return floats or tuples
of floats.  They raise no exceptions on short input — they simply return
``None`` (or ``(None, None, None)`` for multi-value indicators) when there
is not enough data to compute the requested window.

Formulas
--------
- **SMA**  — arithmetic mean over the window.
- **EMA**  — exponential moving average with Wilder-style smoothing
            (alpha = 1 / span).
- **RSI**  — Wilder's RSI (default 14 period).  Uses the same EMA
            smoothing for avg gain / avg loss.
- **ATR**  — Average True Range (SMA of TR, default 14 period).
- **MACD** — fast EMA − slow EMA; signal = EMA(9) of MACD line;
             histogram = MACD − signal.
- **BBANDS** — Bollinger bands: SMA ± N × sample std-dev.
- **DONCHIAN** — Donchian channel: (lower, middle, upper) where lower =
                 min(low) over window, upper = max(high) over window,
                 middle = (lower + upper) / 2.
"""
import math
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(prices: List[float], min_len: int) -> Optional[float]:
    """Return the last price when the list is long enough, else ``None``."""
    if len(prices) < min_len or min_len <= 0:
        return None
    return prices[-1]


def _sma(values: List[float], window: int) -> Optional[float]:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema(values: List[float], span: int) -> Optional[float]:
    """Wilder-style EMA (alpha = 1 / span)."""
    if span <= 0 or len(values) < span:
        return None
    alpha = 1.0 / span
    # Seed with SMA of first `span` values
    prev = sum(values[:span]) / span
    for price in values[span:]:
        prev = alpha * price + (1.0 - alpha) * prev
    return prev


def _sample_stddev(values: List[float]) -> float:
    """Sample standard deviation (ddof=1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sma(prices: List[float], window: int) -> Optional[float]:
    """Simple moving average over ``window`` periods.

    Returns ``None`` when ``len(prices) < window``.
    """
    return _sma(prices, window)


def ema(prices: List[float], span: int) -> Optional[float]:
    """Exponential moving average with Wilder smoothing (alpha = 1/span).

    Returns ``None`` when ``len(prices) < span``.
    """
    return _ema(prices, span)


def rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Wilder's Relative Strength Index.

    Returns ``None`` when ``len(prices) < period + 1``.
    """
    if period <= 0 or len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    # Seed averages with simple mean of first `period` deltas
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    alpha = 1.0 / period
    for i in range(period, len(deltas)):
        avg_gain = alpha * gains[i] + (1.0 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1.0 - alpha) * avg_loss

    if avg_loss < 1e-12:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> Optional[float]:
    """Average True Range (SMA of True Range).

    Returns ``None`` when ``len(closes) < period + 1``.
    """
    if period <= 0 or len(closes) < period + 1:
        return None
    if len(highs) != len(lows) or len(lows) != len(closes):
        raise ValueError("highs, lows, and closes must have the same length")

    tr_values: List[float] = []
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_c = closes[i - 1]
        tr = max(high - low, abs(high - prev_c), abs(low - prev_c))
        tr_values.append(tr)

    return _sma(tr_values, period)


def macd(prices: List[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> Optional[Tuple[float, float, float]]:
    """MACD line, signal line, and histogram.

    Returns ``(macd_line, signal_line, histogram)`` or ``None`` when
    ``len(prices) < slow + signal - 1``.
    """
    if fast <= 0 or slow <= 0 or signal <= 0 or fast >= slow:
        raise ValueError("Require 0 < fast < slow")
    min_len = slow + signal - 1
    if len(prices) < min_len:
        return None

    fast_ema = _ema(prices, fast)
    slow_ema = _ema(prices, slow)
    if fast_ema is None or slow_ema is None:
        return None

    macd_line = fast_ema - slow_ema

    # Build the full MACD-line series to compute the signal EMA
    macd_series: List[float] = []
    for i in range(slow - 1, len(prices)):
        sub = prices[: i + 1]
        f = _ema(sub, fast)
        s = _ema(sub, slow)
        if f is None or s is None:
            macd_series.append(macd_line)
        else:
            macd_series.append(f - s)

    signal_line = _ema(macd_series, signal)
    if signal_line is None:
        return None

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bbands(prices: List[float], window: int = 20,
           num_std: float = 2.0) -> Optional[Tuple[float, float, float]]:
    """Bollinger bands: (lower, middle, upper).

    - middle = SMA(window)
    - lower  = middle − num_std × sample std-dev
    - upper  = middle + num_std × sample std-dev

    When ``window == 1`` the bands collapse to the single price (stddev = 0).

    Returns ``None`` when ``len(prices) < window``.
    """
    if window <= 0 or len(prices) < window:
        return None

    middle = _sma(prices, window)
    if middle is None:
        return None

    if window == 1:
        return middle, middle, middle

    std = _sample_stddev(prices[-window:])
    lower = middle - num_std * std
    upper = middle + num_std * std
    return lower, middle, upper


def donchian(highs: List[float], lows: List[float],
             window: int = 20) -> Optional[Tuple[float, float, float]]:
    """Donchian channel: (lower, middle, upper).

    - lower = min(lows[-window:])
    - upper = max(highs[-window:])
    - middle = (lower + upper) / 2

    Returns ``None`` when ``len(highs) < window``.
    """
    if window <= 0 or len(highs) < window:
        return None
    if len(highs) != len(lows):
        raise ValueError("highs and lows must have the same length")

    lower = min(lows[-window:])
    upper = max(highs[-window:])
    middle = (lower + upper) / 2.0
    return lower, middle, upper


# ---------------------------------------------------------------------------
# Series primitives (for multi-lookback / volatility-scaled signals)
#
# These return whole series rather than a single trailing value. A signal that
# has to be normalised by its *own* historical dispersion (see
# strategies/trend_ensemble.py) needs the history, and recomputing a trailing
# indicator once per bar is O(n^2). Everything below is single-pass O(n).
# ---------------------------------------------------------------------------

def ema_series(prices: List[float], span: int) -> List[float]:
    """Full EMA series using the *standard* smoothing alpha = 2/(span+1).

    Note this deliberately differs from ``ema()`` above, which uses Wilder
    smoothing (alpha = 1/span). Wilder smoothing is the correct convention
    for RSI/ATR and is kept there for exactly that reason; trend/momentum
    signals conventionally use the standard EMA, which reacts about twice as
    fast for the same nominal span. Mixing the two silently would make a
    "60-bar" trend behave like a 120-bar one.

    Returns a list the same length as ``prices`` (seeded with prices[0]).
    Returns ``[]`` for empty input or ``span <= 0``.
    """
    if span <= 0 or not prices:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [prices[0]]
    prev = prices[0]
    for p in prices[1:]:
        prev = alpha * p + (1.0 - alpha) * prev
        out.append(prev)
    return out


def rolling_stdev_series(values: List[float], window: int) -> List[Optional[float]]:
    """Rolling sample std-dev (ddof=1), single pass via running sums.

    Element ``i`` is the std-dev of ``values[i-window+1 : i+1]``, or ``None``
    where there is not yet a full window. Uses the sum/sum-of-squares form,
    with a negative-variance clamp for float cancellation.
    """
    n = len(values)
    if window < 2 or n == 0:
        return [None] * n

    out: List[Optional[float]] = [None] * n
    s = 0.0
    s2 = 0.0
    for i, v in enumerate(values):
        s += v
        s2 += v * v
        if i >= window:
            old = values[i - window]
            s -= old
            s2 -= old * old
        if i >= window - 1:
            mean = s / window
            var = (s2 - window * mean * mean) / (window - 1)
            out[i] = math.sqrt(var) if var > 0.0 else 0.0
    return out


def log_returns(prices: List[float]) -> List[float]:
    """Bar-over-bar log returns. Non-positive prices yield a 0.0 return
    rather than raising — a bad tick must never poison the series (H1).
    """
    out: List[float] = []
    for i in range(1, len(prices)):
        prev, cur = prices[i - 1], prices[i]
        if prev <= 0 or cur <= 0:
            out.append(0.0)
        else:
            out.append(math.log(cur / prev))
    return out


def realized_vol(prices: List[float], window: int,
                 bars_per_year: int = 525_600) -> Optional[float]:
    """Annualised realised volatility from log returns over ``window`` bars.

    ``bars_per_year`` defaults to the 1-minute bar count (365*24*60). Returns
    ``None`` when there is insufficient history, and never returns 0.0 —
    a zero would make any vol-scaled position size infinite, so a flat
    window returns ``None`` instead (H10: guard every division).
    """
    if window < 2 or len(prices) < window + 1:
        return None
    rets = log_returns(prices[-(window + 1):])
    if len(rets) < 2:
        return None
    sd = _sample_stddev(rets)
    if sd <= 1e-12:
        return None
    return sd * math.sqrt(bars_per_year)
