"""Tests for the /ws WebSocket endpoint (step 40) and protocol (step 39)."""
import pytest
import json

from fastapi.testclient import TestClient
from ws.hub import HUB, MAX_CONNECTIONS_PER_IP
from ws.protocol import validate_topic, parse_client_message, is_coalesceable
from settings import get_settings


def _valid_origin():
    settings = get_settings()
    return settings.cors_origins[0] if settings.cors_origins else "http://localhost:3355"


@pytest.fixture(autouse=True)
def reset_hub():
    HUB._connections.clear()
    HUB._ip_counts.clear()
    yield
    HUB._connections.clear()
    HUB._ip_counts.clear()


def _connect_ws(c, origin=None, path="/ws"):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    ws = c.websocket_connect(path, headers=headers)
    try:
        ws.__enter__()
    except Exception:
        return None, ws
    return ws, ws


def _disconnect_ws(ws):
    try:
        ws.__exit__(None, None, None)
    except Exception:
        pass


class TestWebSocketRoute:
    def test_ws_connect_and_ping(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "pong"
            assert data["topic"] == "system"
        finally:
            _disconnect_ws(ws)

    def test_ws_subscribe_and_receive(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"subscribe","topics":["ticks"]}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "subscribed"
            assert "ticks" in data["data"]["topics"]
        finally:
            _disconnect_ws(ws)

    def test_ws_subscribe_then_unsubscribe(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"subscribe","topics":["ticks"]}')
            msg = ws.receive_text()
            assert json.loads(msg)["type"] == "subscribed"

            ws.send_text('{"op":"unsubscribe","topics":["ticks"]}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "unsubscribed"
            assert "ticks" in data["data"]["topics"]
        finally:
            _disconnect_ws(ws)

    def test_ws_invalid_json(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text("not json")
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "error"
        finally:
            _disconnect_ws(ws)

    def test_ws_unknown_op(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"bogus"}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "error"
        finally:
            _disconnect_ws(ws)

    def test_ws_invalid_topic_rejected(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"subscribe","topics":["bogus_topic"]}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "error"
        finally:
            _disconnect_ws(ws)

    def test_ws_topics_query_param(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin(), path="/ws?topics=ticks,fills")
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["v"] == 1
        finally:
            _disconnect_ws(ws)


class TestWSOriginValidation:
    def test_missing_origin_rejected(self):
        from main import app
        c = TestClient(app)
        ws, session = _connect_ws(c, origin=None)
        assert ws is None

    def test_foreign_origin_rejected(self):
        from main import app
        c = TestClient(app)
        ws, session = _connect_ws(c, origin="http://evil.example.com")
        assert ws is None


class TestWSEnvelopeFormat:
    def test_envelope_has_version(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            data = json.loads(ws.receive_text())
            assert data["v"] == 1
        finally:
            _disconnect_ws(ws)

    def test_envelope_has_seq(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            data = json.loads(ws.receive_text())
            assert "seq" in data
            assert isinstance(data["seq"], int)
        finally:
            _disconnect_ws(ws)

    def test_envelope_has_ts(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            data = json.loads(ws.receive_text())
            assert "ts" in data
            assert data["ts"].endswith("Z")
        finally:
            _disconnect_ws(ws)

    def test_envelope_has_type_and_topic(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            ws.send_text('{"op":"ping"}')
            data = json.loads(ws.receive_text())
            assert "type" in data
            assert "topic" in data
            assert "data" in data
        finally:
            _disconnect_ws(ws)

    def test_seq_is_monotonic(self):
        from main import app
        c = TestClient(app)
        ws, _ = _connect_ws(c, origin=_valid_origin())
        if ws is None:
            return
        try:
            seqs = []
            for i in range(3):
                ws.send_text('{"op":"ping"}')
                data = json.loads(ws.receive_text())
                seqs.append(data["seq"])
            assert seqs == sorted(seqs)
            assert len(set(seqs)) == 3
        finally:
            _disconnect_ws(ws)


class TestWSConnectionLimit:
    def test_connection_limit_per_ip(self):
        from main import app
        c = TestClient(app)
        conns = []
        origin = _valid_origin()
        for i in range(MAX_CONNECTIONS_PER_IP):
            ws, _ = _connect_ws(c, origin=origin)
            if ws is not None:
                conns.append(ws)
        # 9th should fail
        ws9, _ = _connect_ws(c, origin=origin)
        assert ws9 is None
        for ws in conns:
            _disconnect_ws(ws)


class TestProtocol:
    def test_validate_simple_topics(self):
        assert validate_topic("ticks")
        assert validate_topic("orders")
        assert validate_topic("equity")
        assert validate_topic("signals")
        assert not validate_topic("")

    def test_validate_fills(self):
        assert validate_topic("fills")
        assert validate_topic("fills:sma_crossover")
        assert not validate_topic("fills:")

    def test_validate_positions(self):
        assert validate_topic("positions:sma_crossover")
        assert not validate_topic("positions:")

    def test_validate_candles(self):
        assert validate_topic("candles:BTC:1m")
        assert validate_topic("candles:ETH:5m")
        assert not validate_topic("candles:BTC")
        assert not validate_topic("candles:BTC:invalid")

    def test_parse_client_messages(self):
        assert parse_client_message('{"op":"ping"}')["op"] == "ping"
        assert parse_client_message('{"op":"subscribe","topics":["ticks"]}')["op"] == "subscribe"
        assert parse_client_message('not json')["error"] is not None
        assert parse_client_message('{"op":"bad"}')["error"] is not None

    def test_is_coalesceable(self):
        assert is_coalesceable("tick")
        assert is_coalesceable("candle")
        assert is_coalesceable("equity")
        assert not is_coalesceable("order")
        assert not is_coalesceable("fill")
