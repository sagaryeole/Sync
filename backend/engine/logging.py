"""Structured JSON logging with correlation IDs.

V5: threaded tick -> signal -> order -> fill.

Usage:
    from engine.logging import get_correlation_id, set_correlation_id

    with set_correlation_id("abc-123"):
        logger.info(
            "processing tick",
        )
"""
import json
import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Optional


# ---------------------------------------------------------------------------
# Thread-local correlation ID store
# ---------------------------------------------------------------------------

_local = threading.local()


def get_correlation_id() -> Optional[str]:
    """Return the correlation ID for the current thread, if any."""
    return getattr(_local, "correlation_id", None)


@contextmanager
def set_correlation_id(cid: Optional[str] = None):
    """Context manager that sets a correlation ID for the current thread.

    If ``cid`` is None, generates a new UUID4.
    """
    if cid is None:
        cid = str(uuid.uuid4())
    old = getattr(_local, "correlation_id", None)
    _local.correlation_id = cid
    try:
        yield cid
    finally:
        if old is None:
            _local.correlation_id = None
        else:
            _local.correlation_id = old


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        if record.exc_info and record.exc_info[0]:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info
        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def configure_json_logging(level: int = logging.INFO) -> None:
    """Replace the root handler with a single JSON handler."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper around logging.getLogger."""
    return logging.getLogger(name)
