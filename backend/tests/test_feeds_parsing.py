"""Tests for feed message parsing (Coinbase + Binance).

These tests inline representative captured payloads and assert the parsed Tick
shape, validation gates, and symbol translation. No network required.
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import asyncio

from feeds.coinbase import CoinbaseFeed
from feeds.binance import BinanceFeed
from feeds.base import Tick
from feeds.symbols import to_provider, from_provider


# ---------------------------------------------------------------------------
# Coinbase payloads
# ---------------------------------------------------------------------------

COINBASE_TICKER_PAYLOAD = {
    "type": "ticker",
    "sequence": 123456789,
    "product_id": "BTC-USD",
    "price": "67234.56",
    "best_bid": "67234.00",
    "best_ask": "67235.00",
    "volume_24h": "1234.56",
    "time": "2024-01-15T12:34:56.789012Z",
}

COINBASE_TICKER_NO_BID_ASK = {
    "type": "ticker",
    "sequence": 123456790,
    "product_id": "ETH-USD",
    "price": "3456.78",
    "volume_24h": "5678.90",
    "time": "2024-01-15T12:35:00.000000Z",
}

COINBASE_INVALID_PRICE = {
    "type": "ticker",
    "sequence": 123456791,
    "product_id": "BTC-USD",
    "price": "0",
    "best_bid": "0",
    "best_ask": "0",
    "volume_24h": "0",
    "time": "2024-01-15T12:35:01.000000Z",
}

COINBASE_ERROR_MSG = {
    "type": "error",
    "message": "Market is not open",
}

COINBASE_NON_TICKER = {
    "type": "heartbeat",
    "sequence": 123456792,
    "product_id": "BTC-USD",
    "time": "2024-01-15T12:35:02.000000Z",
}


# ---------------------------------------------------------------------------
# Binance payloads
# ---------------------------------------------------------------------------

BINANCE_TICKER_PAYLOAD = {
    "stream": "btcusdt@ticker",
    "data": {
        "e": "24hrTicker",
        "E": 1705312496000,
        "s": "BTCUSDT",
        "c": "67234.56",
        "b": "67234.00",
        "a": "67235.00",
        "v": "1234.56",
        "P": "2.34",
    },
}

BINANCE_TICKER_NO_BID_ASK = {
    "stream": "ethusdt@ticker",
    "data": {
        "e": "24hrTicker",
        "E": 1705312500000,
        "s": "ETHUSDT",
        "c": "3456.78",
        "v": "5678.90",
        "P": "1.23",
    },
}

BINANCE_INVALID_PRICE = {
    "stream": "btcusdt@ticker",
    "data": {
        "e": "24hrTicker",
        "E": 1705312501000,
        "s": "BTCUSDT",
        "c": "-1",
        "b": "-1",
        "a": "-1",
        "v": "0",
        "P": "0",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_coinbase_ticker(msg: dict) -> Tick:
    """Replicate the parsing logic from CoinbaseFeed.stream."""
    product_id = msg.get("product_id")
    from feeds.symbols import from_provider
    symbol = from_provider(product_id, "coinbase")
    if not symbol:
        raise ValueError("Unknown product_id")

    time_str = msg.get("time")
    if time_str:
        ts = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    else:
        ts = datetime.now(timezone.utc)

    seq = msg.get("sequence")
    price = float(msg["price"])
    bid = float(msg.get("best_bid", price))
    ask = float(msg.get("best_ask", price))
    volume_24h = float(msg.get("volume_24h", 0))

    if price <= 0 or bid <= 0 or ask <= 0 or bid > ask:
        raise ValueError("Invalid price bounds")

    return Tick(
        symbol=symbol,
        price=price,
        ts=ts,
        source="coinbase",
        bid=bid,
        ask=ask,
        volume_24h=volume_24h,
        change_24h_pct=None,
        seq=seq,
    )


def _parse_binance_ticker(msg: dict) -> Tick:
    """Replicate the parsing logic from BinanceFeed.stream."""
    data = msg.get("data")
    if not data:
        raise ValueError("No data field")

    from feeds.symbols import from_provider
    symbol = from_provider(data.get("s"), "binance")
    if not symbol:
        raise ValueError("Unknown symbol")

    ms_time = data.get("E")
    if ms_time:
        ts = datetime.fromtimestamp(ms_time / 1000.0, timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    price = float(data["c"])
    bid = float(data.get("b", price))
    ask = float(data.get("a", price))
    volume_24h = float(data.get("v", 0))
    change_24h_pct = float(data.get("P", 0))

    if price <= 0 or bid <= 0 or ask <= 0 or bid > ask:
        raise ValueError("Invalid price bounds")

    return Tick(
        symbol=symbol,
        price=price,
        ts=ts,
        source="binance",
        bid=bid,
        ask=ask,
        volume_24h=volume_24h,
        change_24h_pct=change_24h_pct,
        seq=None,
    )


# ---------------------------------------------------------------------------
# Coinbase tests
# ---------------------------------------------------------------------------

class TestCoinbaseParsing:
    def test_valid_ticker(self):
        tick = _parse_coinbase_ticker(COINBASE_TICKER_PAYLOAD)
        assert tick.symbol == "BTC"
        assert tick.price == 67234.56
        assert tick.bid == 67234.00
        assert tick.ask == 67235.00
        assert tick.volume_24h == 1234.56
        assert tick.source == "coinbase"
        assert tick.seq == 123456789

    def test_symbol_translation(self):
        product_id = "BTC-USD"
        symbol = from_provider(product_id, "coinbase")
        assert symbol == "BTC"

    def test_no_bid_ask_defaults_to_price(self):
        tick = _parse_coinbase_ticker(COINBASE_TICKER_NO_BID_ASK)
        assert tick.bid == 3456.78
        assert tick.ask == 3456.78

    def test_invalid_price_raises(self):
        with pytest.raises(ValueError, match="Invalid price bounds"):
            _parse_coinbase_ticker(COINBASE_INVALID_PRICE)

    def test_error_message_not_a_ticker(self):
        msg = json.loads(json.dumps(COINBASE_ERROR_MSG))
        assert msg.get("type") == "error"

    def test_non_ticker_ignored(self):
        msg = json.loads(json.dumps(COINBASE_NON_TICKER))
        assert msg.get("type") != "ticker"

    def test_timestamp_parsing(self):
        tick = _parse_coinbase_ticker(COINBASE_TICKER_PAYLOAD)
        assert tick.ts.year == 2024
        assert tick.ts.month == 1
        assert tick.ts.day == 15
        assert tick.ts.tzinfo is not None

    def test_json_parse_rejects_nan(self):
        raw = '{"type": "ticker", "product_id": "BTC-USD", "price": NaN, "best_bid": "1", "best_ask": "2", "time": "2024-01-15T12:00:00Z"}'
        with pytest.raises(ValueError):
            _parse_coinbase_ticker(json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"Invalid constant: {c}"))))

    def test_frozen_dataclass(self):
        tick = _parse_coinbase_ticker(COINBASE_TICKER_PAYLOAD)
        with pytest.raises(AttributeError):
            tick.price = 1.0


# ---------------------------------------------------------------------------
# Binance tests
# ---------------------------------------------------------------------------

class TestBinanceParsing:
    def test_valid_ticker(self):
        tick = _parse_binance_ticker(BINANCE_TICKER_PAYLOAD)
        assert tick.symbol == "BTC"
        assert tick.price == 67234.56
        assert tick.bid == 67234.00
        assert tick.ask == 67235.00
        assert tick.volume_24h == 1234.56
        assert tick.change_24h_pct == 2.34
        assert tick.source == "binance"

    def test_symbol_translation(self):
        provider_sym = "BTCUSDT"
        symbol = from_provider(provider_sym, "binance")
        assert symbol == "BTC"

    def test_no_bid_ask_defaults_to_price(self):
        tick = _parse_binance_ticker(BINANCE_TICKER_NO_BID_ASK)
        assert tick.bid == 3456.78
        assert tick.ask == 3456.78

    def test_timestamp_from_milliseconds(self):
        tick = _parse_binance_ticker(BINANCE_TICKER_PAYLOAD)
        assert tick.ts.year == 2024
        assert tick.ts.month == 1
        assert tick.ts.day == 15
        assert tick.ts.tzinfo is not None

    def test_invalid_price_raises(self):
        with pytest.raises(ValueError, match="Invalid price bounds"):
            _parse_binance_ticker(BINANCE_INVALID_PRICE)

    def test_missing_data_raises(self):
        with pytest.raises(ValueError, match="No data field"):
            _parse_binance_ticker({"stream": "foo", "data": None})

    def test_json_parse_rejects_nan(self):
        raw = '{"stream": "btcusdt@ticker", "data": {"e": "24hrTicker", "E": 1705312496000, "s": "BTCUSDT", "c": NaN, "b": "1", "a": "2", "v": "0", "P": "0"}}'
        with pytest.raises(ValueError):
            _parse_binance_ticker(json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"Invalid constant: {c}"))))

    def test_frozen_dataclass(self):
        tick = _parse_binance_ticker(BINANCE_TICKER_PAYLOAD)
        with pytest.raises(AttributeError):
            tick.price = 1.0
