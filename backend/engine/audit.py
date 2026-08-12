"""Audit logging for risk-parameter and configuration changes.

H16: every change to risk parameters or strategy config must be recorded
so that "why did it suddenly size 10×" is answerable.

Usage:
    from engine.audit import audit_log

    audit_log(
        actor="api",
        action="update_risk_config",
        target="max_position_pct",
        before="0.20",
        after="0.50",
    )
"""
import json
from datetime import datetime, timezone
from typing import Optional

from database import get_session
from models import AuditLog


def audit_log(
    actor: str,
    action: str,
    target: str,
    before: Optional[str] = None,
    after: Optional[str] = None,
) -> None:
    """Append one audit-log row.

    All args are stored as strings for simplicity.  ``before``/``after``
    are JSON-serialized when they are dicts/lists.
    """
    session = get_session()
    try:
        def _serialize(value):
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, sort_keys=True)
            return str(value)

        session.add(AuditLog(
            ts=datetime.now(timezone.utc),
            actor=str(actor),
            action=str(action),
            target=str(target),
            before=_serialize(before),
            after=_serialize(after),
        ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
