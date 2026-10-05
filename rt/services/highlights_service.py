"""Evidenziazioni dello Studio (4.2.2): per lezione e unità, solo nel database."""
from sqlalchemy import delete, select

from rt.db.engine import get_database
from rt.db.models import StudyHighlight
from rt.db.session import read_scope, session_scope
from rt.services.errors import NotFound


def _row(h: StudyHighlight) -> dict:
    return {"id": h.id, "unit_id": h.unit_id, "color": h.color, "source": h.source}


def list_highlights(lesson_id: int, unit_id: str | None) -> list[dict]:
    with read_scope(get_database()) as session:
        query = select(StudyHighlight).where(StudyHighlight.lesson_id == lesson_id)
        if unit_id is not None:
            query = query.where(StudyHighlight.unit_id == unit_id)
        return [_row(h) for h in session.scalars(query.order_by(StudyHighlight.id))]


def add_highlight(lesson_id: int, unit_id: str, color: int, source: dict) -> dict:
    with session_scope(get_database()) as session:
        row = StudyHighlight(lesson_id=lesson_id, unit_id=unit_id, color=color, source=source)
        session.add(row)
        session.flush()
        return _row(row)


def delete_highlight(lesson_id: int, highlight_id: int) -> None:
    with session_scope(get_database()) as session:
        row = session.get(StudyHighlight, highlight_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("highlight_not_found", "Evidenziazione non trovata.")
        session.delete(row)


def clear_unit(lesson_id: int, unit_id: str) -> None:
    with session_scope(get_database()) as session:
        session.execute(delete(StudyHighlight).where(StudyHighlight.lesson_id == lesson_id,
                                                     StudyHighlight.unit_id == unit_id))
