"""Tests for ws/hub.py — connection management, backpressure, and limits."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from ws.hub import (
    Hub,
    Connection,
    MAX_TOPICS_PER_CONN,
    MAX_CONNECTIONS_PER_IP,
    QUEUE_MAXSIZE,
    WS_CLOSE_TRY_AGAIN_LATER,
)
from ws.protocol import make_envelope, Envelope


@pytest.fixture
def hub():
    return Hub()


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    return ws


class TestConnection:
    def test_next_seq_increments(self):
        conn = Connection(id="abc", ws=None)
        assert conn.next_seq() == 1
        assert conn.next_seq() == 2
        assert conn.next_seq() == 3

    def test_is_subscribed(self):
        conn = Connection(id="abc", ws=None, topics={"ticks"})
        assert conn.is_subscribed("ticks") is True
        assert conn.is_subscribed("fills") is False

    def test_default_queue_maxsize(self):
        conn = Connection(id="abc", ws=None)
        assert conn.queue.maxsize == QUEUE_MAXSIZE

    def test_dropped_starts_zero(self):
        conn = Connection(id="abc", ws=None)
        assert conn.dropped == 0

    def test_closed_default_false(self):
        conn = Connection(id="abc", ws=None)
        assert conn.closed is False


class TestHubConnect:
    @pytest.mark.asyncio
    async def test_connect_returns_connection(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        assert conn is not None
        assert conn.id is not None
        assert conn.ip == "127.0.0.1"
        assert hub.connection_count == 1

    @pytest.mark.asyncio
    async def test_connect_with_initial_topics(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks", "fills"})
        assert conn is not None
        assert conn.topics == {"ticks", "fills"}

    @pytest.mark.asyncio
    async def test_connect_limit_per_ip(self, hub):
        """H8: max 8 connections per IP."""
        for i in range(MAX_CONNECTIONS_PER_IP):
            ws = AsyncMock()
            conn = await hub.connect(ws, ip="1.2.3.4")
            assert conn is not None
        # 9th connection should be rejected
        ws9 = AsyncMock()
        conn = await hub.connect(ws9, ip="1.2.3.4")
        assert conn is None
        assert hub.connection_count == MAX_CONNECTIONS_PER_IP

    @pytest.mark.asyncio
    async def test_connect_different_ips_independent(self, hub):
        """Each IP gets its own connection limit."""
        for i in range(MAX_CONNECTIONS_PER_IP):
            ws = AsyncMock()
            conn = await hub.connect(ws, ip="1.2.3.4")
            assert conn is not None
        ws = AsyncMock()
        conn = await hub.connect(ws, ip="5.6.7.8")
        assert conn is not None
        assert hub.connection_count == MAX_CONNECTIONS_PER_IP + 1


class TestHubDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        await hub.disconnect(conn)
        assert hub.connection_count == 0
        assert conn.closed is True

    @pytest.mark.asyncio
    async def test_disconnect_frees_ip_slot(self, hub):
        """After disconnect, the IP slot is freed."""
        ws = AsyncMock()
        conn = await hub.connect(ws, ip="1.2.3.4")
        await hub.disconnect(conn)
        # Should be able to connect again
        ws2 = AsyncMock()
        conn2 = await hub.connect(ws2, ip="1.2.3.4")
        assert conn2 is not None

    @pytest.mark.asyncio
    async def test_disconnect_already_removed_is_noop(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        await hub.disconnect(conn)
        # Second disconnect should not raise
        await hub.disconnect(conn)
        assert hub.connection_count == 0


class TestHubSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_adds_topics(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        result = await hub.subscribe(conn, {"ticks", "fills"})
        assert set(result["added"]) == {"ticks", "fills"}
        assert result["rejected"] == []
        assert conn.topics == {"ticks", "fills"}

    @pytest.mark.asyncio
    async def test_subscribe_already_subscribed(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        result = await hub.subscribe(conn, {"ticks"})
        assert result["added"] == []
        assert result["rejected"] == []

    @pytest.mark.asyncio
    async def test_subscribe_limit_exceeded(self, hub, mock_ws):
        """H8: max 64 topics per connection."""
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        # Fill up to the limit
        topics = {f"positions:strat_{i}" for i in range(MAX_TOPICS_PER_CONN)}
        result = await hub.subscribe(conn, topics)
        assert len(result["added"]) == MAX_TOPICS_PER_CONN
        # One more should be rejected
        result = await hub.subscribe(conn, {"positions:overflow"})
        assert result["added"] == []
        assert "positions:overflow" in result["rejected"]


class TestHubUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_topics(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks", "fills"})
        removed = await hub.unsubscribe(conn, {"ticks"})
        assert removed == {"ticks"}
        assert conn.topics == {"fills"}

    @pytest.mark.asyncio
    async def test_unsubscribe_not_subscribed(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        removed = await hub.unsubscribe(conn, {"fills"})
        assert removed == set()
        assert conn.topics == {"ticks"}


class TestHubPublish:
    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscribed(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        env = make_envelope("tick", "ticks", {"s": "BTC", "p": 50000.0})
        await hub.publish(env)
        assert conn.queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_publish_skips_unsubscribed(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"fills"})
        env = make_envelope("tick", "ticks", {"s": "BTC"})
        await hub.publish(env)
        assert conn.queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_publish_to_multiple_subscribers(self, hub):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        conn1 = await hub.connect(ws1, ip="1.1.1.1", initial_topics={"ticks"})
        conn2 = await hub.connect(ws2, ip="2.2.2.2", initial_topics={"ticks"})
        env = make_envelope("tick", "ticks", {"s": "BTC"})
        await hub.publish(env)
        assert conn1.queue.qsize() == 1
        assert conn2.queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_publish_skips_closed_connections(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        conn.closed = True
        env = make_envelope("tick", "ticks", {"s": "BTC"})
        await hub.publish(env)
        assert conn.queue.qsize() == 0


class TestBackpressure:
    @pytest.mark.asyncio
    async def test_queue_overflow_evicts_coalesceable(self, hub, mock_ws):
        """When the queue is full, the oldest coalesceable message is evicted."""
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks", "orders"})
        # Fill the queue with coalesceable tick messages
        for i in range(QUEUE_MAXSIZE):
            env = make_envelope("tick", "ticks", {"i": i})
            await conn.send_envelope(env)
        assert conn.queue.qsize() == QUEUE_MAXSIZE
        # Now add one more — should evict the oldest tick
        env = make_envelope("tick", "ticks", {"i": 999})
        ok = await conn.send_envelope(env)
        assert ok is True
        assert conn.dropped == 1
        assert conn.queue.qsize() == QUEUE_MAXSIZE

    @pytest.mark.asyncio
    async def test_queue_overflow_non_coalesceable_closes(self, hub, mock_ws):
        """If the queue is full of non-coalesceable messages, connection is closed."""
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"orders"})
        # Fill the queue with non-coalesceable order messages
        for i in range(QUEUE_MAXSIZE):
            env = make_envelope("order", "orders", {"id": i})
            await conn.send_envelope(env)
        assert conn.queue.qsize() == QUEUE_MAXSIZE
        # Try to add one more — should fail (no coalesceable to evict)
        env = make_envelope("order", "orders", {"id": 999})
        ok = await conn.send_envelope(env)
        assert ok is False

    @pytest.mark.asyncio
    async def test_mixed_queue_evicts_only_coalesceable(self, hub, mock_ws):
        """A mix of coalesceable and non-coalesceable: only coalesceable is evicted."""
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks", "orders"})
        # Fill with alternating tick (coalesceable) and order (non-coalesceable)
        for i in range(QUEUE_MAXSIZE // 2):
            await conn.send_envelope(make_envelope("tick", "ticks", {"i": i}))
            await conn.send_envelope(make_envelope("order", "orders", {"id": i}))
        assert conn.queue.qsize() == QUEUE_MAXSIZE
        # Add one more tick — should evict the oldest tick, not the order
        ok = await conn.send_envelope(make_envelope("tick", "ticks", {"i": 999}))
        assert ok is True
        assert conn.dropped == 1

    @pytest.mark.asyncio
    async def test_closed_connection_rejects(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        conn.closed = True
        env = make_envelope("tick", "ticks", {"s": "BTC"})
        ok = await conn.send_envelope(env)
        assert ok is False


class TestHubStats:
    @pytest.mark.asyncio
    async def test_get_stats(self, hub, mock_ws):
        await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        stats = hub.get_stats()
        assert stats["connections"] == 1
        assert stats["total_dropped"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_drops(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1", initial_topics={"ticks"})
        conn.dropped = 5
        stats = hub.get_stats()
        assert stats["total_dropped"] == 5


class TestPublishToConnection:
    @pytest.mark.asyncio
    async def test_direct_send(self, hub, mock_ws):
        conn = await hub.connect(mock_ws, ip="127.0.0.1")
        env = make_envelope("heartbeat", "system", {"server_time": "now"})
        ok = await hub.publish_to_connection(conn, env)
        assert ok is True
        assert conn.queue.qsize() == 1
