"""Stato di studio nel database, indipendente dai documenti della lezione."""
from datetime import datetime, timezone
from typing import Literal, NamedTuple, Optional

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


class _Row(NamedTuple):
    lesson_id: int
    unit_id: str
    status: str
    status_at: Optional[datetime]
    last_read_at: Optional[datetime]


def summaries(lessons: dict[int, str]) -> dict[int, dict]:
    """Una sola query per tutte le lezioni; ignora le unità tolte dalla scaletta."""
    result = {lid: {"study_learned": 0, "study_learning": 0, "study_last_at": None} for lid in lessons}
    if not lessons:
        return result
    with read_scope(get_database()) as session:
        rows = [_Row(r.lesson_id, r.unit_id, r.status, r.status_at, r.last_read_at)
                for r in session.scalars(select(StudyUnit).where(StudyUnit.lesson_id.in_(lessons)))]
    # La scaletta si legge solo per le lezioni studiate: l'elenco non apre centinaia di outline.
    current = {lid: current_unit_ids(lessons[lid]) for lid in {row.lesson_id for row in rows}}
    for row in rows:
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


def restore_units(session, lesson_id: int, entries) -> None:
    """Ripristino dal manifesto ZIP: le righe malformate non bloccano l'importazione."""
    if not isinstance(entries, list):
        return

    def date(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Data non valida.")
        at = datetime.fromisoformat(value)
        return at.astimezone(timezone.utc).replace(tzinfo=None) if at.tzinfo else at

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        unit_id = entry.get("unit_id")
        status = entry.get("status")
        if not isinstance(unit_id, str) or not 1 <= len(unit_id) <= 64 or status not in STATUSES:
            continue
        try:
            status_at, last_read_at = date(entry.get("status_at")), date(entry.get("last_read_at"))
        except (ValueError, TypeError, OverflowError):
            continue
        session.merge(StudyUnit(lesson_id=lesson_id, unit_id=unit_id, status=status,
                                status_at=status_at, last_read_at=last_read_at))
