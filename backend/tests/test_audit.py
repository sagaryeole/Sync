"""Tests for engine/audit.py — H16 audit-log infrastructure."""
import json

from database import get_session
from engine.audit import audit_log
from models import AuditLog


def test_audit_log_inserts_row():
    audit_log(actor="test", action="update", target="max_position_pct",
              before="0.20", after="0.50")
    session = get_session()
    row = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert row.actor == "test"
    assert row.action == "update"
    assert row.target == "max_position_pct"
    assert row.before == "0.20"
    assert row.after == "0.50"
    session.close()


def test_audit_log_serializes_dicts():
    before = {"max_position_pct": 0.2, "stop_loss_pct": 0.02}
    after = {"max_position_pct": 0.5, "stop_loss_pct": 0.02}
    audit_log(
        actor="test", action="update", target="risk",
        before=before, after=after,
    )
    session = get_session()
    row = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert json.loads(row.before) == before
    assert json.loads(row.after) == after
    session.close()


def test_audit_log_nulls():
    audit_log(actor="test", action="reset", target="risk")
    session = get_session()
    row = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert row.before is None
    assert row.after is None
    session.close()
