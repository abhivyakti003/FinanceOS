"""Audit log of security events (logins, password changes, exports, admin actions).

Writing an audit entry never breaks the action being audited.
"""

import logging

from sqlalchemy import select

from app.database.db import use_session
from app.database.models import AuditLog

log = logging.getLogger("financeos.audit")


def record(
    event: str, user_id: int | None = None, email: str | None = None, detail: str | None = None, session=None
) -> None:
    try:
        with use_session(session) as s:
            s.add(AuditLog(user_id=user_id, email=email, event=event, detail=(detail or "")[:500] or None))
        log.info("%s user=%s email=%s %s", event, user_id, email, detail or "")
    except Exception:  # auditing must never take the app down
        log.exception("Couldn't write audit entry for %s", event)


def recent(limit: int = 200, event: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if event:
        query = query.where(AuditLog.event == event)
    with use_session() as s:
        return list(s.scalars(query))


def for_user(user_id: int, limit: int = 50) -> list[AuditLog]:
    with use_session() as s:
        return list(
            s.scalars(
                select(AuditLog)
                .where(AuditLog.user_id == user_id)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
            )
        )
