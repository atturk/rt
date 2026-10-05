"""
rt.services.highlights_service
Gestione delle evidenziazioni di studio (web-highlighter) salvate sul database.
"""
from typing import Any, Optional

from sqlalchemy import delete, select

from rt.db.engine import get_database
from rt.db.models import Lesson, StudyHighlight
from rt.db.session import session_scope
from rt.services.errors import NotFound, Unavailable


def list_highlights(lesson_id: int, unit_id: Optional[str] = None, db=None) -> list[dict[str, Any]]:
    db = db or get_database()
    if db is None:
        raise Unavailable("database_unavailable", "Database non disponibile.")
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise NotFound("lesson_not_found", "Lezione non trovata.")
        stmt = select(StudyHighlight).where(StudyHighlight.lesson_id == lesson_id)
        if unit_id:
            stmt = stmt.where(StudyHighlight.unit_id == unit_id)
        stmt = stmt.order_by(StudyHighlight.id)
        rows = session.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "lesson_id": r.lesson_id,
                "unit_id": r.unit_id,
                "color": r.color,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


def create_highlight(lesson_id: int, unit_id: str, color: int, source: dict[str, Any], db=None) -> dict[str, Any]:
    db = db or get_database()
    if db is None:
        raise Unavailable("database_unavailable", "Database non disponibile.")
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise NotFound("lesson_not_found", "Lezione non trovata.")
        highlight = StudyHighlight(
            lesson_id=lesson_id,
            unit_id=unit_id,
            color=color,
            source=source,
        )
        session.add(highlight)
        session.flush()
        return {
            "id": highlight.id,
            "lesson_id": highlight.lesson_id,
            "unit_id": highlight.unit_id,
            "color": highlight.color,
            "source": highlight.source,
            "created_at": highlight.created_at.isoformat(),
        }


def delete_highlight(lesson_id: int, highlight_id: int, db=None) -> None:
    db = db or get_database()
    if db is None:
        raise Unavailable("database_unavailable", "Database non disponibile.")
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise NotFound("lesson_not_found", "Lezione non trovata.")
        highlight = session.scalar(
            select(StudyHighlight).where(
                StudyHighlight.id == highlight_id,
                StudyHighlight.lesson_id == lesson_id,
            )
        )
        if highlight is None:
            raise NotFound("highlight_not_found", "Evidenziazione non trovata.")
        session.delete(highlight)


def delete_unit_highlights(lesson_id: int, unit_id: str, db=None) -> int:
    db = db or get_database()
    if db is None:
        raise Unavailable("database_unavailable", "Database non disponibile.")
    with session_scope(db) as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson is None:
            raise NotFound("lesson_not_found", "Lezione non trovata.")
        res = session.execute(
            delete(StudyHighlight).where(
                StudyHighlight.lesson_id == lesson_id,
                StudyHighlight.unit_id == unit_id,
            )
        )
        return res.rowcount
