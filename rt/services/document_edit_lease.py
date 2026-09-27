"""Short, renewable editing leases shared between browser tabs and API workers."""

import secrets
from datetime import timedelta

from rt.db.engine import get_database
from rt.db.models import Job, Lesson, Setting, utcnow
from rt.db.session import session_scope
from rt.api.errors import ApiError

LEASE_SECONDS = 90


def _key(lesson_id: int) -> str:
    return f"lesson_edit_lease:{lesson_id}"


def _active(value: dict | None) -> bool:
    return bool(value and value.get("expires", "") > utcnow().isoformat())


def acquire(lesson_id: int, token: str | None = None) -> dict:
    db = get_database()
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise ApiError(404, "lesson_not_found", "Lezione non trovata.")
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token:
            raise ApiError(409, "document_edit_busy", "Il documento è in modifica in un'altra scheda.")
        from sqlalchemy import select
        if session.scalar(select(Job.id).where(Job.lesson_path == lesson.path,
                                             Job.state.in_(["queued", "running"])).limit(1)):
            raise ApiError(409, "lesson_busy", "Un job sta già lavorando sulla lezione.")
        value = {"token": token if row and _active(row.value) and row.value.get("token") == token else secrets.token_urlsafe(32),
                 "expires": (utcnow() + timedelta(seconds=LEASE_SECONDS)).isoformat()}
        if row:
            row.value = value
        else:
            session.add(Setting(key=_key(lesson_id), value=value))
        return value


def assert_editable(lesson_id: int, token: str | None = None) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token:
            raise ApiError(409, "document_edit_busy", "Il documento è in modifica: termina o attendi la scadenza.")
        if token and (not row or not _active(row.value) or row.value.get("token") != token):
            raise ApiError(409, "document_edit_expired", "La sessione di modifica è scaduta: riapri l'editor.")


def release(lesson_id: int, token: str) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and row.value.get("token") == token:
            session.delete(row)
