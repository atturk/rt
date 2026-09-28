"""Explicit editing locks shared between browser tabs and API workers."""

import secrets
from datetime import datetime, timezone

from rt.db.engine import get_database
from rt.db.models import Job, Lesson, Setting
from rt.db.session import session_scope
from rt.api.errors import ApiError

def _key(lesson_id: int) -> str:
    return f"lesson_edit_lease:{lesson_id}"


def _active(value: dict | None) -> bool:
    return bool(value and value.get("token"))


def acquire(lesson_id: int, token: str | None = None, recover: bool = False) -> dict:
    db = get_database()
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise ApiError(404, "lesson_not_found", "Lezione non trovata.")
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token and not recover:
            raise ApiError(409, "document_edit_busy", "Il documento è in modifica in un'altra scheda.")
        previous = dict(row.value or {}) if row and _active(row.value) else {}
        from sqlalchemy import select
        if session.scalar(select(Job.id).where(Job.lesson_path == lesson.path,
                                             Job.state.in_(["queued", "running"])).limit(1)):
            raise ApiError(409, "lesson_busy", "Un job sta già lavorando sulla lezione.")
        same_session = bool(previous and previous.get("token") == token)
        value = {
            "token": token if same_session else secrets.token_urlsafe(32),
            "lease_id": previous.get("lease_id") if same_session else secrets.token_urlsafe(8),
            "acquired_at": previous.get("acquired_at") if same_session else datetime.now(timezone.utc).isoformat(),
        }
        if row:
            row.value = value
        else:
            session.add(Setting(key=_key(lesson_id), value=value))
        return {**value,
                "recovered": bool(previous and not same_session and recover),
                "previous_lease_id": previous.get("lease_id") if previous and not same_session else None,
                "previous_acquired_at": previous.get("acquired_at") if previous and not same_session else None}


def assert_editable(lesson_id: int, token: str | None = None) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token:
            raise ApiError(409, "document_edit_busy", "Il documento è in modifica in un'altra scheda. Puoi recuperare la sessione.")
        if token and (not row or not _active(row.value) or row.value.get("token") != token):
            raise ApiError(409, "document_edit_invalid", "La sessione di modifica non è più attiva: riapri l'editor.")


def release(lesson_id: int, token: str) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and row.value.get("token") == token:
            session.delete(row)
