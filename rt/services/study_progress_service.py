"""Stato di studio nel database, indipendente dai documenti della lezione."""
from datetime import timezone
from typing import Literal

from sqlalchemy import select

from rt.db.engine import get_database
from rt.db.models import StudyUnit, utcnow
from rt.db.session import read_scope, session_scope
from rt.services.errors import NotFound

StudyStatus = Literal["da-imparare", "in-apprendimento", "appreso"]
STATUSES = ("da-imparare", "in-apprendimento", "appreso")


def _at(value):
    return value.replace(tzinfo=timezone.utc) if value is not None else None


def _row(row: StudyUnit) -> dict:
    return {"unit_id": row.unit_id, "status": row.status,
            "status_at": _at(row.status_at), "last_read_at": _at(row.last_read_at)}


def list_units(lesson_id: int) -> list[dict]:
    with read_scope(get_database()) as session:
        return [_row(row) for row in session.scalars(select(StudyUnit).where(
            StudyUnit.lesson_id == lesson_id).order_by(StudyUnit.unit_id))]


def current_unit_ids(lesson_dir: str) -> set[str]:
    """La scaletta attuale, anche quando la rielaborazione non è ancora pronta."""
    from rt.pipeline.outline import load_outline
    try:
        outline = load_outline(lesson_dir)
    except (OSError, ValueError):
        return set()
    return {unit.id for macro in outline.macro_sections for unit in macro.units}


def _touch(lesson_id: int, lesson_dir: str, unit_id: str, values: dict) -> dict:
    if unit_id not in current_unit_ids(lesson_dir):
        raise NotFound("study_unit_not_found", "Unità non trovata nella scaletta.")
    db = get_database()
    # L'upsert aggiorna solo i campi richiesti: una lettura concorrente non annulla lo stato.
    if db.engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    with session_scope(db) as session:
        statement = insert(StudyUnit).values(lesson_id=lesson_id, unit_id=unit_id, **values)
        session.execute(statement.on_conflict_do_update(
            index_elements=[StudyUnit.lesson_id, StudyUnit.unit_id], set_=values))
        return _row(session.get(StudyUnit, (lesson_id, unit_id)))


def set_status(lesson_id: int, lesson_dir: str, unit_id: str, status: StudyStatus) -> dict:
    if status not in STATUSES:
        raise ValueError("Stato di studio non valido.")
    return _touch(lesson_id, lesson_dir, unit_id, {"status": status, "status_at": utcnow()})


def mark_read(lesson_id: int, lesson_dir: str, unit_id: str) -> None:
    _touch(lesson_id, lesson_dir, unit_id, {"last_read_at": utcnow()})


def summaries(lessons: dict[int, str]) -> dict[int, dict]:
    """Una sola query per tutte le lezioni; ignora le unità tolte dalla scaletta."""
    result = {lid: {"study_learned": 0, "study_learning": 0, "study_last_at": None} for lid in lessons}
    if not lessons:
        return result
    current = {lid: current_unit_ids(path) for lid, path in lessons.items()}
    with read_scope(get_database()) as session:
        for row in session.scalars(select(StudyUnit).where(StudyUnit.lesson_id.in_(lessons))):
            if row.unit_id not in current[row.lesson_id]:
                continue
            summary = result[row.lesson_id]
            if row.status == "appreso":
                summary["study_learned"] += 1
            elif row.status == "in-apprendimento":
                summary["study_learning"] += 1
            dates = [date for date in (summary["study_last_at"], _at(row.status_at), _at(row.last_read_at)) if date]
            summary["study_last_at"] = max(dates) if dates else None
    return result
