"""Note dello Studio (Verifica e Chiedi, 4.2.4): gestione DB."""
from typing import Any, Optional
from sqlalchemy import delete, select

from rt.db.engine import get_database
from rt.db.models import StudyNote
from rt.db.session import read_scope, session_scope
from rt.services.errors import NotFound


def _row(n: StudyNote) -> dict[str, Any]:
    return {
        "id": n.id,
        "lesson_id": n.lesson_id,
        "unit_id": n.unit_id,
        "kind": n.kind,
        "anchor": n.anchor,
        "unit_fingerprint": n.unit_fingerprint,
        "request": n.request,
        "response": n.response,
        "model": n.model,
        "cost": n.cost,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "applied_decision_id": n.applied_decision_id,
    }


def list_study_notes(lesson_id: int, unit_id: Optional[str] = None) -> list[dict[str, Any]]:
    with read_scope(get_database()) as session:
        query = select(StudyNote).where(StudyNote.lesson_id == lesson_id)
        if unit_id is not None:
            query = query.where(StudyNote.unit_id == unit_id)
        return [_row(n) for n in session.scalars(query.order_by(StudyNote.id.desc()))]


def get_study_note(lesson_id: int, note_id: int) -> dict[str, Any]:
    with read_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        return _row(row)


def add_study_note(
    lesson_id: int,
    unit_id: str,
    kind: str,
    anchor: dict[str, Any],
    unit_fingerprint: str = "",
    request: str = "",
    response: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
    cost: Optional[float] = None,
) -> dict[str, Any]:
    with session_scope(get_database()) as session:
        row = StudyNote(
            lesson_id=lesson_id,
            unit_id=unit_id,
            kind=kind,
            anchor=anchor,
            unit_fingerprint=unit_fingerprint,
            request=request,
            response=response or {},
            model=model,
            cost=cost,
        )
        session.add(row)
        session.flush()
        return _row(row)


def delete_study_note(lesson_id: int, note_id: int) -> None:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        session.delete(row)


def update_study_note_applied(lesson_id: int, note_id: int, decision_id: Optional[int]) -> dict[str, Any]:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        row.applied_decision_id = decision_id
        session.flush()
        return _row(row)


def update_study_note_unit(lesson_id: int, note_id: int, new_unit_id: str) -> None:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is not None and row.lesson_id == lesson_id:
            row.unit_id = new_unit_id
