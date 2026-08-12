"""WebSocket connection hub (step 38).

The Hub manages all active WebSocket connections. It is async-native
(FastAPI/Starlette) and provides:

  - connect/disconnect: lifecycle management
  - subscribe/unsubscribe: per-connection topic filtering
  - publish: broadcast an Envelope to all connections subscribed to its topic
  - _writer: per-connection background task that drains the queue to the WS

Backpressure strategy (H8):
  Each connection has an asyncio.Queue(maxsize=256). On overflow:
    1. Evict the oldest *coalesceable* message (ticks, candles, equity).
    2. If no coalesceable message exists, close with 1013 Try Again Later.
  Order, fill, and halt messages are NEVER dropped.

Connection limits (H8):
  - Max 64 topics per connection
  - Max 8 connections per IP
  - Inbound message max_size enforced at the WS handler level
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set
from collections import defaultdict

from ws.protocol import Envelope, make_envelope, is_coalesceable

logger = logging.getLogger("ws.hub")

# H8: Resource limits
MAX_TOPICS_PER_CONN = 64
MAX_CONNECTIONS_PER_IP = 8
QUEUE_MAXSIZE = 256
WS_CLOSE_TRY_AGAIN_LATER = 1013
WS_CLOSE_POLICY_VIOLATION = 1008


@dataclass
class Connection:
    """A single WebSocket connection with its own outbound queue.

    Attributes:
        id: Unique connection ID (UUID hex).
        ws: The Starlette WebSocket object.
        topics: Set of subscribed topic strings.
        queue: Bounded asyncio.Queue for outbound messages.
        dropped: Count of messages dropped due to backpressure.
        seq: Monotonic sequence counter for outbound envelopes.
        ip: Client IP address (for per-IP connection limiting).
        closed: Whether this connection has been closed.
    """

    id: str
    ws: Any  # starlette.websockets.WebSocket
    topics: Set[str] = field(default_factory=set)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAXSIZE))
    dropped: int = 0
    seq: int = 0
    ip: str = ""
    closed: bool = False

    def next_seq(self) -> int:
        """Get the next monotonic sequence number."""
        self.seq += 1
        return self.seq

    def is_subscribed(self, topic: str) -> bool:
        """Check if this connection is subscribed to a topic."""
        return topic in self.topics

    async def send_envelope(self, envelope: Envelope) -> bool:
        """Enqueue an envelope for sending. Returns True if enqueued,
        False if the connection should be closed (1013).

        Backpressure: on queue full, try to evict the oldest coalesceable
        message. If none exists, return False (caller closes with 1013).
        """
        if self.closed:
            return False

        try:
            self.queue.put_nowait(envelope)
            return True
        except asyncio.QueueFull:
            # Try to evict the oldest coalesceable message
            evicted = self._evict_oldest_coalesceable()
            if evicted:
                self.dropped += 1
                logger.debug(
                    "Conn %s: evicted coalesceable message (dropped=%d)",
                    self.id[:8], self.dropped,
                )
                try:
                    self.queue.put_nowait(envelope)
                    return True
                except asyncio.QueueFull:
                    # Still full after eviction — close
                    return False
            else:
                # No coalesceable message to evict — must close
                return False

    def _evict_oldest_coalesceable(self) -> bool:
        """Try to remove the oldest coalesceable message from the queue.

        Drains items one by one, removing the first coalesceable one,
        then re-enqueues the rest. Returns True if something was evicted.
        """
        items = []
        evicted = False
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not evicted and is_coalesceable(item.type):
                evicted = True
                continue
            items.append(item)

        # Re-enqueue the non-evicted items
        for item in items:
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                # Queue filled up again — drop the rest
                self.dropped += 1

        return evicted


class Hub:
    """Manages all active WebSocket connections and broadcasts messages.

    Thread-safety: the Hub is async-only. Code running in sync threads
    (engine, scheduler) must use the thread-safe EVENT_BUS (engine.events)
    which an async pump drains into hub.publish().
    """

    def __init__(self) -> None:
        self._connections: Dict[str, Connection] = {}
        self._ip_counts: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        """Total number of active connections."""
        return len(self._connections)

    async def connect(
        self,
        ws: Any,
        ip: str = "",
        initial_topics: Optional[Set[str]] = None,
    ) -> Optional[Connection]:
        """Register a new WebSocket connection.

        Returns the Connection object, or None if the connection limit
        for this IP has been reached (H8).
        """
        async with self._lock:
            if self._ip_counts[ip] >= MAX_CONNECTIONS_PER_IP:
                logger.warning(
                    "Connection limit reached for IP %s (%d/%d)",
                    ip, self._ip_counts[ip], MAX_CONNECTIONS_PER_IP,
                )
                return None

            conn_id = uuid.uuid4().hex
            conn = Connection(id=conn_id, ws=ws, ip=ip)
            if initial_topics:
                conn.topics = set(initial_topics)
            self._connections[conn_id] = conn
            self._ip_counts[ip] += 1
            logger.info(
                "WS connect %s (ip=%s, total=%d)",
                conn_id[:8], ip, len(self._connections),
            )
            return conn

    async def disconnect(self, conn: Connection) -> None:
        """Remove a connection from the hub."""
        async with self._lock:
            if conn.id in self._connections:
                del self._connections[conn.id]
                self._ip_counts[conn.ip] -= 1
                if self._ip_counts[conn.ip] <= 0:
                    del self._ip_counts[conn.ip]
                conn.closed = True
                logger.info(
                    "WS disconnect %s (total=%d, dropped=%d)",
                    conn.id[:8], len(self._connections), conn.dropped,
                )

    async def subscribe(self, conn: Connection, topics: Set[str]) -> Dict[str, Any]:
        """Subscribe a connection to topics.

        Returns a dict with:
            - "added": list of newly subscribed topics
            - "rejected": list of topics rejected (limit exceeded)
        """
        async with self._lock:
            added = []
            rejected = []
            for topic in topics:
                if topic in conn.topics:
                    continue  # Already subscribed
                if len(conn.topics) >= MAX_TOPICS_PER_CONN:
                    rejected.append(topic)
                    continue
                conn.topics.add(topic)
                added.append(topic)
            return {"added": added, "rejected": rejected}

    async def unsubscribe(self, conn: Connection, topics: Set[str]) -> Set[str]:
        """Unsubscribe a connection from topics. Returns the set of removed topics."""
        async with self._lock:
            removed = set()
            for topic in topics:
                if topic in conn.topics:
                    conn.topics.discard(topic)
                    removed.add(topic)
            return removed

    async def publish(self, envelope: Envelope) -> int:
        """Broadcast an envelope to all connections subscribed to its topic.

        Returns the number of connections the message was delivered to
        (enqueued, not necessarily sent yet).
        """
        delivered = 0
        # Snapshot connections to avoid mutation during iteration
        conns = list(self._connections.values())
        for conn in conns:
            if conn.closed:
                continue
            if not conn.is_subscribed(envelope.topic):
                continue
            ok = await conn.send_envelope(envelope)
            if not ok:
                # Connection queue is full with non-coalesceable messages.
                # Mark for closure — the _writer task will close with 1013.
                logger.warning(
                    "Conn %s: queue overflow, marking for 1013 close",
                    conn.id[:8],
                )
                conn.closed = True
        return delivered

    async def publish_to_connection(self, conn: Connection, envelope: Envelope) -> bool:
        """Send an envelope directly to a specific connection (bypasses topic filter).

        Used for system messages (heartbeat, error, subscribe confirmation).
        Returns True if enqueued, False if the connection should be closed.
        """
        return await conn.send_envelope(envelope)

    async def get_connection(self, conn_id: str) -> Optional[Connection]:
        """Get a connection by ID."""
        return self._connections.get(conn_id)

    def get_stats(self) -> Dict[str, Any]:
        """Return hub statistics for the heartbeat message."""
        return {
            "connections": len(self._connections),
            "total_dropped": sum(c.dropped for c in self._connections.values()),
        }


# Global hub instance — shared by the WS route and the event pump
HUB = Hub()
