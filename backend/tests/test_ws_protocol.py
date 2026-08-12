"""Tests for ws/protocol.py — envelope serialization and client message parsing."""

import json
import pytest
from ws.protocol import (
    Envelope,
    make_envelope,
    parse_client_message,
    validate_topic,
    topic_type,
    is_coalesceable,
    COALESCEABLE_TYPES,
    NON_DROPPABLE_TYPES,
    PROTOCOL_VERSION,
    VALID_INTERVALS,
    VALID_OPS,
)


class TestEnvelope:
    def test_basic_envelope(self):
        env = Envelope(type="tick", topic="ticks", data={"s": "BTC", "p": 50000.0})
        d = env.to_dict()
        assert d["v"] == PROTOCOL_VERSION
        assert d["type"] == "tick"
        assert d["topic"] == "ticks"
        assert d["data"] == {"s": "BTC", "p": 50000.0}
        assert "ts" in d
        assert d["seq"] == 0  # assigned by Connection

    def test_coalesce_auto_detected_tick(self):
        env = make_envelope("tick", "ticks", {"s": "BTC"})
        assert env.coalesce is True

    def test_coalesce_auto_detected_candle(self):
        env = make_envelope("candle", "candles:BTC:1m", {"t": 123})
        assert env.coalesce is True

    def test_coalesce_auto_detected_equity(self):
        env = make_envelope("equity", "equity", {"snapshots": []})
        assert env.coalesce is True

    def test_coalesce_false_for_order(self):
        env = make_envelope("order", "orders", {"id": 1})
        assert env.coalesce is False

    def test_coalesce_false_for_fill(self):
        env = make_envelope("fill", "fills", {"id": 1})
        assert env.coalesce is False

    def test_coalesce_false_for_halt(self):
        env = make_envelope("halt", "system", {"reason": "MAX_DD"})
        assert env.coalesce is False

    def test_coalesce_explicit_override(self):
        """Explicitly setting coalesce=True on a non-coalesceable type."""
        env = make_envelope("order", "orders", {"id": 1}, coalesce=True)
        assert env.coalesce is True

    def test_to_json_roundtrip(self):
        env = make_envelope("tick", "ticks", {"s": "BTC", "p": 50000.0})
        env.seq = 42
        raw = env.to_json()
        parsed = json.loads(raw)
        assert parsed["v"] == 1
        assert parsed["type"] == "tick"
        assert parsed["seq"] == 42
        assert parsed["data"]["s"] == "BTC"

    def test_ts_is_iso8601(self):
        env = make_envelope("tick", "ticks", {})
        assert env.ts.endswith("Z")
        # Should be parseable
        from datetime import datetime
        # Strip the Z and parse
        ts_clean = env.ts.rstrip("Z")
        datetime.fromisoformat(ts_clean)


class TestIsCoalesceable:
    def test_tick_is_coalesceable(self):
        assert is_coalesceable("tick") is True

    def test_candle_is_coalesceable(self):
        assert is_coalesceable("candle") is True

    def test_equity_is_coalesceable(self):
        assert is_coalesceable("equity") is True

    def test_order_not_coalesceable(self):
        assert is_coalesceable("order") is False

    def test_fill_not_coalesceable(self):
        assert is_coalesceable("fill") is False

    def test_unknown_type_not_coalesceable(self):
        assert is_coalesceable("unknown") is False


class TestParseClientMessage:
    def test_subscribe(self):
        msg = parse_client_message(json.dumps({"op": "subscribe", "topics": ["ticks", "fills"]}))
        assert msg["op"] == "subscribe"
        assert msg["topics"] == ["ticks", "fills"]
        assert msg["error"] is None

    def test_unsubscribe(self):
        msg = parse_client_message(json.dumps({"op": "unsubscribe", "topics": ["ticks"]}))
        assert msg["op"] == "unsubscribe"
        assert msg["topics"] == ["ticks"]
        assert msg["error"] is None

    def test_ping(self):
        msg = parse_client_message(json.dumps({"op": "ping"}))
        assert msg["op"] == "ping"
        assert msg["error"] is None

    def test_invalid_json(self):
        msg = parse_client_message("not json at all")
        assert msg["op"] is None
        assert "Invalid JSON" in msg["error"]

    def test_non_object(self):
        msg = parse_client_message(json.dumps([1, 2, 3]))
        assert msg["op"] is None
        assert "object" in msg["error"]

    def test_unknown_op(self):
        msg = parse_client_message(json.dumps({"op": "bogus", "topics": []}))
        assert msg["op"] is None
        assert "Unknown op" in msg["error"]

    def test_subscribe_empty_topics(self):
        msg = parse_client_message(json.dumps({"op": "subscribe", "topics": []}))
        assert msg["op"] is None
        assert "empty" in msg["error"]

    def test_subscribe_topics_not_list(self):
        msg = parse_client_message(json.dumps({"op": "subscribe", "topics": "ticks"}))
        assert msg["op"] is None
        assert "list" in msg["error"]

    def test_subscribe_non_string_topics(self):
        msg = parse_client_message(json.dumps({"op": "subscribe", "topics": [1, 2]}))
        assert msg["op"] is None
        assert "strings" in msg["error"]

    def test_ping_ignores_topics(self):
        msg = parse_client_message(json.dumps({"op": "ping", "topics": ["ticks"]}))
        assert msg["op"] == "ping"
        assert msg["error"] is None


class TestValidateTopic:
    def test_ticks(self):
        assert validate_topic("ticks") is True

    def test_orders(self):
        assert validate_topic("orders") is True

    def test_equity(self):
        assert validate_topic("equity") is True

    def test_signals(self):
        assert validate_topic("signals") is True

    def test_feed(self):
        assert validate_topic("feed") is True

    def test_system(self):
        assert validate_topic("system") is True

    def test_fills_no_key(self):
        assert validate_topic("fills") is True

    def test_fills_with_key(self):
        assert validate_topic("fills:sma_crossover") is True

    def test_candles_btc_1m(self):
        assert validate_topic("candles:BTC:1m") is True

    def test_candles_eth_5m(self):
        assert validate_topic("candles:ETH:5m") is True

    def test_positions_with_key(self):
        assert validate_topic("positions:sma_crossover") is True

    def test_empty_topic(self):
        assert validate_topic("") is False

    def test_unknown_topic(self):
        assert validate_topic("bogus") is False

    def test_candles_missing_interval(self):
        assert validate_topic("candles:BTC") is False

    def test_candles_invalid_interval(self):
        assert validate_topic("candles:BTC:2m") is False

    def test_candles_invalid_symbol_too_long(self):
        assert validate_topic("candles:VERYLONGSYMBOL:1m") is False

    def test_candles_validated_against_known_symbols(self):
        symbols = {"BTC", "ETH", "SOL"}
        assert validate_topic("candles:BTC:1m", known_symbols=symbols) is True
        assert validate_topic("candles:DOGE:1m", known_symbols=symbols) is False

    def test_positions_missing_key(self):
        assert validate_topic("positions") is False

    def test_fills_key_too_long(self):
        long_key = "x" * 65
        assert validate_topic(f"fills:{long_key}") is False


class TestTopicType:
    def test_ticks(self):
        assert topic_type("ticks") == "ticks"

    def test_candles(self):
        assert topic_type("candles:BTC:1m") == "candles"

    def test_fills(self):
        assert topic_type("fills") == "fills"

    def test_fills_with_key(self):
        assert topic_type("fills:sma_crossover") == "fills"

    def test_positions(self):
        assert topic_type("positions:sma_crossover") == "positions"


class TestConstants:
    def test_protocol_version(self):
        assert PROTOCOL_VERSION == 1

    def test_valid_intervals_includes_1m(self):
        assert "1m" in VALID_INTERVALS

    def test_valid_ops(self):
        assert "subscribe" in VALID_OPS
        assert "unsubscribe" in VALID_OPS
        assert "ping" in VALID_OPS

    def test_coalesceable_and_non_droppable_disjoint(self):
        assert COALESCEABLE_TYPES.isdisjoint(NON_DROPPABLE_TYPES)
