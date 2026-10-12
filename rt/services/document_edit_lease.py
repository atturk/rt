"""Explicit editing locks shared between browser tabs and API workers."""

import secrets
from datetime import datetime, timedelta, timezone

from rt.db.engine import get_database
from rt.db.models import Job, Lesson, Setting
from rt.db.session import session_scope
from rt.services.errors import Conflict, NotFound


class DocumentBeingEdited(Conflict):
    """Il documento della lezione è aperto nell'editor da un'altra sessione: né un'altra
    scheda né un job possono modificarlo finché il lease non è rilasciato o scaduto."""

    def __init__(self, message: str = "Il documento è in modifica in un'altra scheda."):
        super().__init__("document_edit_busy", message)


def _key(lesson_id: int) -> str:
    return f"lesson_edit_lease:{lesson_id}"


# Una scheda chiusa o un browser andato in crash non devono bloccare per sempre i job della
# lezione: l'editor rinnova il lease ogni pochi minuti, e senza rinnovo scade da solo.
LEASE_TTL = timedelta(minutes=15)


def _active(value: dict | None, now: datetime | None = None) -> bool:
    if not (value and value.get("token")):
        return False
    stamp = value.get("renewed_at") or value.get("acquired_at")
    try:
        renewed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    return (now or datetime.now(timezone.utc)) - renewed < LEASE_TTL


def acquire(lesson_id: int, token: str | None = None, recover: bool = False) -> dict:
    db = get_database()
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise NotFound("lesson_not_found", "Lezione non trovata.")
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token and not recover:
            raise DocumentBeingEdited()
        previous = dict(row.value or {}) if row and _active(row.value) else {}
        from sqlalchemy import select
        if session.scalar(select(Job.id).where(Job.lesson_path == lesson.path,
                                             Job.state.in_(["queued", "running"]),
                                             Job.type != "documents").limit(1)):
            raise Conflict("lesson_busy", "Un job sta già lavorando sulla lezione.")
        same_session = bool(previous and previous.get("token") == token)
        now = datetime.now(timezone.utc).isoformat()
        value = {
            "token": token if same_session else secrets.token_urlsafe(32),
            "lease_id": previous.get("lease_id") if same_session else secrets.token_urlsafe(8),
            "acquired_at": previous.get("acquired_at") if same_session else now,
            "renewed_at": now,
        }
        if row:
            row.value = value
        else:
            session.add(Setting(key=_key(lesson_id), value=value))
        return {**value,
                "expires": (datetime.fromisoformat(now) + LEASE_TTL).isoformat(),
                "recovered": bool(previous and not same_session and recover),
                "previous_lease_id": previous.get("lease_id") if previous and not same_session else None,
                "previous_acquired_at": previous.get("acquired_at") if previous and not same_session else None}


def is_being_edited(session, lesson_id: int) -> bool:
    """C'è un lease di modifica attivo sulla lezione (letto nella sessione DB del chiamante)."""
    row = session.get(Setting, _key(lesson_id))
    return bool(row and _active(row.value))


def assert_editable(lesson_id: int, token: str | None = None) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and _active(row.value) and row.value.get("token") != token:
            raise DocumentBeingEdited("Il documento è in modifica in un'altra scheda. Puoi recuperare la sessione.")
        if token and (not row or not _active(row.value) or row.value.get("token") != token):
            raise Conflict("document_edit_invalid", "La sessione di modifica non è più attiva: riapri l'editor.")


def release(lesson_id: int, token: str) -> None:
    db = get_database()
    with session_scope(db) as session:
        row = session.get(Setting, _key(lesson_id))
        if row and row.value.get("token") == token:
            session.delete(row)
