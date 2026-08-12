import logging
import queue
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger("engine.events")

# Bounded queue to thread events safely from background APScheduler threads
# and engine writers to FastAPI's async websocket connections.
EVENT_BUS: queue.Queue = queue.Queue(maxsize=5000)

def emit(topic: str, event_type: str, data: Dict[str, Any]) -> None:
    """Emits an event into the thread-safe global event bus.

    If the queue is full, the oldest message is dropped to prevent memory leaks
    or blocking background trading threads.
    """
    event = {
        "topic": topic,
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data
    }
    try:
        EVENT_BUS.put_nowait(event)
    except queue.Full:
        try:
            # Discard oldest to preserve bounded queue invariants
            _ = EVENT_BUS.get_nowait()
            EVENT_BUS.put_nowait(event)
            logger.warning("Event bus overflow. Dropped oldest message to make space.")
        except Exception as e:
            # Prevent race conditions under concurrency if another thread drains it
            logger.debug("Event bus race during overflow handling: %s", e)
