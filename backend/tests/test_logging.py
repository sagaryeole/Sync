"""Tests for engine/logging.py — V5 structured JSON logging."""
import json
import logging

from engine.logging import (
    JsonFormatter,
    configure_json_logging,
    get_correlation_id,
    set_correlation_id,
    _local,
)


class TestCorrelationContext:
    def test_default_is_none(self):
        assert get_correlation_id() is None

    def test_set_and_get(self):
        with set_correlation_id("abc-123") as cid:
            assert get_correlation_id() == "abc-123"
            assert cid == "abc-123"

    def test_generates_uuid_when_none(self):
        with set_correlation_id() as cid:
            assert get_correlation_id() is not None
            assert cid == get_correlation_id()

    def test_restores_after_exit(self):
        old = "old"
        _local.correlation_id = old
        with set_correlation_id("new"):
            assert get_correlation_id() == "new"
        assert get_correlation_id() == old
        _local.correlation_id = None  # cleanup

    def test_nests_correctly(self):
        with set_correlation_id("outer"):
            assert get_correlation_id() == "outer"
            with set_correlation_id("inner"):
                assert get_correlation_id() == "inner"
            assert get_correlation_id() == "outer"


class TestJsonFormatter:
    def test_basic_message(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        payload = json.loads(output)
        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test"
        assert "timestamp" in payload

    def test_correlation_id_included(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="with cid", args=(), exc_info=None,
        )
        with set_correlation_id("trace-1"):
            output = formatter.format(record)
        payload = json.loads(output)
        assert payload["correlation_id"] == "trace-1"

    def test_no_correlation_id_is_null(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="no cid", args=(), exc_info=None,
        )
        output = formatter.format(record)
        payload = json.loads(output)
        assert payload["correlation_id"] is None

    def test_exception_included(self):
        import sys
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        payload = json.loads(output)
        assert "exc_info" in payload
        assert "ValueError" in payload["exc_info"]


class TestConfigureJsonLogging:
    def test_installs_json_handler(self):
        root = logging.getLogger()
        root.handlers.clear()
        configure_json_logging(level=logging.WARNING)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.WARNING
