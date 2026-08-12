"""WebSocket envelope protocol (step 39).

Every message sent to a client is wrapped in a versioned envelope:

    {"v":1,"type":...,"topic":...,"ts":"ISO8601Z","seq":<int>,"data":{...}}

`seq` is a per-connection monotonic counter so the client can detect gaps
(caused by coalescing/eviction on the server side).

Coalescable message types (ticks, candles, equity) carry an extra
`coalesce: true` flag so the hub knows they are safe to evict on queue
overflow. Order, fill, and halt messages are NEVER dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

# Message types that are safe to coalesce/evict on backpressure.
# These are high-frequency state snapshots where only the latest value matters.
COALESCEABLE_TYPES: Set[str] = {"tick", "candle", "equity"}

# Message types that must NEVER be dropped — they represent discrete events
# the client must not miss (order fills, halts, errors).
NON_DROPPABLE_TYPES: Set[str] = {"order", "fill", "halt", "error"}

PROTOCOL_VERSION = 1


def is_coalesceable(msg_type: str) -> bool:
    """Return True if a message type can be safely evicted on queue overflow."""
    return msg_type in COALESCEABLE_TYPES


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO8601 string with 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Envelope:
    """A single outbound WebSocket message envelope.

    Attributes:
        type: Message type (tick, candle, order, fill, position, equity,
              signal, feed, heartbeat, error).
        topic: Topic string the client subscribed to (e.g. "ticks",
               "candles:BTC:1m", "positions:sma_crossover").
        data: Payload dict.
        coalesce: If True, this message can be evicted on backpressure.
        ts: ISO8601 timestamp (set at envelope creation).
        seq: Per-connection monotonic sequence number (assigned by the
             Connection's _writer, not here).
    """

    type: str
    topic: str
    data: Dict[str, Any]
    coalesce: bool = False
    ts: str = field(default_factory=utc_now_iso)
    seq: int = 0

    def __post_init__(self) -> None:
        if self.coalesce is False and self.type in COALESCEABLE_TYPES:
            self.coalesce = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire format (dict ready for json.dumps)."""
        return {
            "v": PROTOCOL_VERSION,
            "type": self.type,
            "topic": self.topic,
            "ts": self.ts,
            "seq": self.seq,
            "data": self.data,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string for sending over the wire."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


def make_envelope(
    msg_type: str,
    topic: str,
    data: Dict[str, Any],
    coalesce: Optional[bool] = None,
) -> Envelope:
    """Create an Envelope, auto-detecting coalesce from the type if not given."""
    if coalesce is None:
        coalesce = is_coalesceable(msg_type)
    return Envelope(type=msg_type, topic=topic, data=data, coalesce=coalesce)


# --- Inbound client message parsing -----------------------------------------

VALID_OPS = {"subscribe", "unsubscribe", "ping", "sync"}


def parse_client_message(raw: str) -> Dict[str, Any]:
    """Parse an inbound client JSON message.

    Returns a dict with keys:
        - "op": the operation (subscribe/unsubscribe/ping) or None if invalid
        - "topics": list of topic strings (for subscribe/unsubscribe)
        - "error": error message string if parsing failed

    Client message format:
        {"op":"subscribe","topics":["ticks","fills"]}
        {"op":"unsubscribe","topics":["ticks"]}
        {"op":"ping"}
    """
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"op": None, "topics": [], "error": "Invalid JSON"}

    if not isinstance(msg, dict):
        return {"op": None, "topics": [], "error": "Message must be a JSON object"}

    op = msg.get("op")
    if op not in VALID_OPS:
        return {
            "op": None,
            "topics": [],
            "error": f"Unknown op '{op}'. Valid ops: {sorted(VALID_OPS)}",
        }

    topics = msg.get("topics", [])
    if op in ("subscribe", "unsubscribe"):
        if not isinstance(topics, list):
            return {"op": None, "topics": [], "error": "topics must be a list"}
        if not all(isinstance(t, str) for t in topics):
            return {"op": None, "topics": [], "error": "topics must be strings"}
        if len(topics) == 0:
            return {"op": None, "topics": [], "error": "topics list is empty"}

    return {"op": op, "topics": topics, "error": None}


# --- Topic validation -------------------------------------------------------

# Valid topic prefixes and their parameter patterns:
#   ticks              — no params
#   candles:{SYM}:{INT} — symbol + interval
#   orders             — no params
#   fills[:{key}]      — optional strategy key
#   positions:{key}    — strategy key required
#   equity             — no params
#   signals            — no params
#   feed               — no params
#   system             — no params (heartbeat, error)

VALID_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}


def validate_topic(topic: str, known_symbols: Optional[Set[str]] = None) -> bool:
    """Validate a topic string against the known topic grammar.

    Args:
        topic: The topic string to validate.
        known_symbols: Optional set of valid symbol names. If provided,
            candle topics are checked against this set.

    Returns:
        True if the topic is valid, False otherwise.
    """
    if not topic:
        return False

    # Simple topics with no parameters
    if topic in ("ticks", "orders", "equity", "signals", "feed", "system"):
        return True

    # fills or fills:{key}
    if topic == "fills":
        return True
    if topic.startswith("fills:"):
        key = topic[len("fills:"):]
        return len(key) > 0 and len(key) <= 64

    # positions:{key}
    if topic.startswith("positions:"):
        key = topic[len("positions:"):]
        return len(key) > 0 and len(key) <= 64

    # candles:{SYM}:{INT}
    if topic.startswith("candles:"):
        parts = topic.split(":")
        if len(parts) != 3:
            return False
        _, symbol, interval = parts
        if not symbol or len(symbol) > 10:
            return False
        if interval not in VALID_INTERVALS:
            return False
        if known_symbols is not None and symbol not in known_symbols:
            return False
        return True

    return False


def topic_type(topic: str) -> str:
    """Extract the base topic type (e.g. 'candles:BTC:1m' -> 'candles')."""
    return topic.split(":")[0]
