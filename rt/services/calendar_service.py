"""Servizio del calendario di RT (4.2.5 CA1).

Gestisce la settimana tipo (template), le modifiche puntuali (overrides),
lo stato del giorno intero, lo stato delle ore e il collegamento lezione <-> ora.
"""
from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from rt.services import calendar_models as schemas
from rt.core.lesson_paths import lesson_path
from rt.core.state import read_info_yaml
from rt.db.engine import get_database
from rt.db.models import (
    CalendarDayState,
    CalendarEntryState,
    CalendarOverride,
    CalendarTemplateEntry,
    Lesson,
    StudyUnit,
)
from rt.db.session import read_scope, session_scope
from rt.services.errors import Invalid, NotFound
from rt.services.study_progress_service import current_unit_ids
from rt.storage import fs

MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
DAYS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
DAYL = [
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
]


def normalize_time(t: str) -> str:
    """Normalizza un orario in stringa HH:MM (es. '9:30' -> '09:30', '9.5' -> '09:30')."""
    t = str(t or "").strip()
    if not t:
        return ""
    if ":" in t:
        parts = t.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return f"{h:02d}:{m:02d}"
        except ValueError:
            return t
    try:
        val = float(t)
        h = int(val)
        m = int(round((val - h) * 60))
        return f"{h:02d}:{m:02d}"
    except ValueError:
        return t


def time_to_float(t: str) -> float:
    """Converte un orario HH:MM in float (es. '09:30' -> 9.5)."""
    norm = normalize_time(t)
    if not norm or ":" not in norm:
        return 0.0
    try:
        h, m = norm.split(":", 1)
        return int(h) + int(m) / 60.0
    except (ValueError, IndexError):
        return 0.0


def float_to_time(h: float) -> str:
    """Converte un float in HH:MM (es. 9.5 -> '09:30')."""
    hours = int(h)
    minutes = int(round((h - hours) * 60))
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def parse_date(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise Invalid("invalid_date", "Data non valida, attesa AAAA-MM-GG.") from None


def _template_valid_on(entry: CalendarTemplateEntry, date_str: str) -> bool:
    """L'ora vale da valid_from (inclusa) a valid_to (esclusa)."""
    return entry.valid_from <= date_str and (entry.valid_to is None or date_str < entry.valid_to)


def normalize_subject(materia: Optional[str]) -> str:
    """Normalizza la materia per il confronto (maiuscolo, senza spazi ai bordi)."""
    return str(materia or "").strip().upper()


# ---------------------------------------------------------------------------
# Template (Settimana tipo)
# ---------------------------------------------------------------------------

def list_template_entries(db=None) -> List[schemas.CalendarTemplateEntryView]:
    database = db or get_database()
    with read_scope(database) as session:
        rows = session.scalars(
            select(CalendarTemplateEntry).order_by(
                CalendarTemplateEntry.day_of_week,
                CalendarTemplateEntry.start_time,
                CalendarTemplateEntry.id,
            )
        ).all()
        return [
            schemas.CalendarTemplateEntryView(
                id=r.id,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                day_of_week=r.day_of_week,
                start_time=r.start_time,
                end_time=r.end_time,
                materia=r.materia,
                docente=r.docente,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
            for r in rows
        ]


def create_template_entry(
    data: schemas.CalendarTemplateEntryCreate, db=None
) -> schemas.CalendarTemplateEntryView:
    start_norm = normalize_time(data.start_time)
    end_norm = normalize_time(data.end_time)
    if time_to_float(start_norm) >= time_to_float(end_norm):
        raise Invalid("invalid_time_range", "L'orario di inizio deve precedere la fine.")

    valid_from = data.valid_from or "2000-01-01"
    if data.valid_to is not None and data.valid_to <= valid_from:
        raise Invalid("invalid_date_range", "La fine dell'intervallo deve seguire l'inizio.")
    database = db or get_database()
    with session_scope(database) as session:
        entry = CalendarTemplateEntry(
            valid_from=valid_from,
            valid_to=data.valid_to,
            day_of_week=data.day_of_week,
            start_time=start_norm,
            end_time=end_norm,
            materia=data.materia.strip(),
            docente=data.docente.strip() if data.docente else None,
        )
        from rt.services.subjects import register_subject, register_teacher
        register_subject(session, entry.materia)
        register_teacher(session, entry.materia, entry.docente)
        session.add(entry)
        session.flush()
        return schemas.CalendarTemplateEntryView(
            id=entry.id,
            valid_from=entry.valid_from,
            valid_to=entry.valid_to,
            day_of_week=entry.day_of_week,
            start_time=entry.start_time,
            end_time=entry.end_time,
            materia=entry.materia,
            docente=entry.docente,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
        )


def delete_template_entry(
    entry_id: int, from_date: Optional[str] = None, to_date: Optional[str] = None, db=None
) -> None:
    """Toglie un'ora da una data in poi, oppure solo nell'intervallo [from_date, to_date).

    La continuazione conserva note, stati, lezioni collegate e modifiche future.
    Senza date si cancella l'ora, come prima.
    """
    if from_date is not None:
        from_date = parse_date(from_date).isoformat()
    if to_date is not None:
        to_date = parse_date(to_date).isoformat()
        if from_date is None or to_date <= from_date:
            raise Invalid("invalid_date_range", "La fine dell'intervallo deve seguire l'inizio.")
    database = db or get_database()
    with session_scope(database) as session:
        _delete_template_range(session, entry_id, from_date, to_date)


def _delete_template_range(session, entry_id, from_date=None, to_date=None):
    """Stessa operazione nella transazione di importazione dell'orario."""
    entry = session.get(CalendarTemplateEntry, entry_id)
    if entry is None:
        raise NotFound("template_entry_not_found", f"Slot {entry_id} non trovato.")
    if to_date is not None:
        # Un intervallo disgiunto non deve creare doppioni o parti vuote.
        if entry.valid_from >= to_date or (entry.valid_to is not None and entry.valid_to <= from_date):
            return
        if entry.valid_to is None or entry.valid_to > to_date:
            continuation = CalendarTemplateEntry(
                valid_from=max(to_date, entry.valid_from), valid_to=entry.valid_to,
                day_of_week=entry.day_of_week, start_time=entry.start_time,
                end_time=entry.end_time, materia=entry.materia, docente=entry.docente,
            )
            session.add(continuation)
            session.flush()
            for override in session.scalars(select(CalendarOverride).where(
                CalendarOverride.template_entry_id == entry.id, CalendarOverride.date >= to_date,
            )):
                override.template_entry_id = continuation.id
            for state in session.scalars(select(CalendarEntryState).where(
                or_(CalendarEntryState.template_entry_id == entry.id,
                    CalendarEntryState.entry_key == f"tpl_{entry.id}"),
                CalendarEntryState.date >= to_date,
            )):
                state.template_entry_id = continuation.id
                if state.entry_key == f"tpl_{entry.id}":
                    state.entry_key = f"tpl_{continuation.id}"
            # Salva i riferimenti prima di un eventuale DELETE con CASCADE.
            session.flush()
    if from_date is not None and entry.valid_from < from_date:
        if entry.valid_to is None or entry.valid_to > from_date:
            entry.valid_to = from_date
        return
    session.delete(entry)


# ---------------------------------------------------------------------------
# Overrides (Modifiche della settimana precisa)
# ---------------------------------------------------------------------------

def create_override(
    data: schemas.CalendarOverrideCreate, db=None
) -> schemas.CalendarOverrideView:
    database = db or get_database()
    with session_scope(database) as session:
        if data.action in ("added", "modified"):
            if not data.start_time or not data.end_time or not data.materia:
                raise Invalid("missing_fields", "Inizio, fine e materia sono obbligatori.")
            start_norm = normalize_time(data.start_time)
            end_norm = normalize_time(data.end_time)
            if time_to_float(start_norm) >= time_to_float(end_norm):
                raise Invalid("invalid_time_range", "L'orario di inizio deve precedere la fine.")
        else:
            start_norm = None
            end_norm = None

        override = CalendarOverride(
            date=data.date,
            template_entry_id=data.template_entry_id,
            action=data.action,
            start_time=start_norm,
            end_time=end_norm,
            materia=data.materia.strip() if data.materia else None,
            docente=data.docente.strip() if data.docente else None,
        )
        from rt.services.subjects import register_subject, register_teacher
        register_subject(session, override.materia)
        register_teacher(session, override.materia, override.docente)
        session.add(override)
        session.flush()
        return schemas.CalendarOverrideView(
            id=override.id,
            date=override.date,
            action=override.action,
            template_entry_id=override.template_entry_id,
            start_time=override.start_time,
            end_time=override.end_time,
            materia=override.materia,
            docente=override.docente,
            created_at=override.created_at.isoformat() if override.created_at else None,
        )


def delete_override(override_id: int, db=None) -> None:
    database = db or get_database()
    with session_scope(database) as session:
        row = session.get(CalendarOverride, override_id)
        if row is None:
            raise NotFound("override_not_found", f"Modifica {override_id} non trovata.")
        session.delete(row)


# ---------------------------------------------------------------------------
# Stati del giorno e delle ore
# ---------------------------------------------------------------------------

def set_day_state(
    data: schemas.CalendarDayStateSet, db=None
) -> schemas.CalendarDayStateView:
    database = db or get_database()
    with session_scope(database) as session:
        row = session.scalars(
            select(CalendarDayState).where(CalendarDayState.date == data.date)
        ).first()
        status_val = (data.status or "").strip()
        if row is None:
            row = CalendarDayState(
                date=data.date,
                status=status_val,
                note=data.note,
            )
            session.add(row)
        else:
            row.status = status_val
            if data.note is not None:
                row.note = data.note
        session.flush()
        return schemas.CalendarDayStateView(
            date=row.date,
            status=row.status,
            note=row.note,
        )


def get_day_state(date: str, db=None) -> Optional[schemas.CalendarDayStateView]:
    database = db or get_database()
    with read_scope(database) as session:
        row = session.scalars(
            select(CalendarDayState).where(CalendarDayState.date == date)
        ).first()
        if row is None:
            return None
        return schemas.CalendarDayStateView(
            date=row.date,
            status=row.status,
            note=row.note,
        )


def set_entry_state(
    data: schemas.CalendarEntryStateSet, db=None
) -> schemas.CalendarEntryStateView:
    database = db or get_database()
    with session_scope(database) as session:
        row = session.scalars(
            select(CalendarEntryState).where(
                CalendarEntryState.date == data.date,
                CalendarEntryState.entry_key == data.entry_key,
            )
        ).first()
        if row is None:
            row = CalendarEntryState(
                date=data.date,
                entry_key=data.entry_key,
                template_entry_id=data.template_entry_id,
                override_id=data.override_id,
                status=data.status,
                note=data.note,
            )
            session.add(row)
        else:
            if data.status is not None:
                row.status = data.status
            if data.note is not None:
                row.note = data.note
            if data.template_entry_id is not None:
                row.template_entry_id = data.template_entry_id
            if data.override_id is not None:
                row.override_id = data.override_id
        session.flush()
        return schemas.CalendarEntryStateView(
            id=row.id,
            date=row.date,
            entry_key=row.entry_key,
            template_entry_id=row.template_entry_id,
            override_id=row.override_id,
            status=row.status,
            note=row.note,
            lesson_id=row.lesson_id,
            manual_link=row.manual_link,
        )


def require_linkable_event(date: str, entry_key: str, session: Session) -> schemas.CalendarEventView:
    """Controllo condiviso fra import e collegamento, anche nella transazione di link."""
    day = parse_date(date)
    events, _ = _resolve_dates(session, [day], datetime.datetime.now())[date]
    event = next((event for event in events if event.key == entry_key), None)
    if event is None:
        raise Invalid("calendar_entry_not_found", "Ora del calendario non trovata per questa data.")
    if event.status == "annullata":
        raise Invalid("calendar_entry_cancelled", "Ora annullata: non è possibile collegare una lezione.")
    return event


def link_lesson(
    data: schemas.CalendarLinkLessonRequest, db=None
) -> schemas.CalendarEntryStateView:
    database = db or get_database()
    with session_scope(database) as session:
        if data.lesson_id is not None and session.get(Lesson, data.lesson_id) is None:
            raise NotFound("lesson_not_found", f"Lezione {data.lesson_id} non trovata.")
        if data.lesson_id is not None:
            require_linkable_event(data.date, data.entry_key, session)
        row = session.scalars(
            select(CalendarEntryState).where(
                CalendarEntryState.date == data.date,
                CalendarEntryState.entry_key == data.entry_key,
            )
        ).first()
        if row is None:
            row = CalendarEntryState(
                date=data.date,
                entry_key=data.entry_key,
                template_entry_id=data.template_entry_id,
                override_id=data.override_id,
                lesson_id=data.lesson_id,
                manual_link=True,
                status="seguita" if data.lesson_id is not None else None,
            )
            session.add(row)
        else:
            row.lesson_id = data.lesson_id
            row.manual_link = True
            if data.lesson_id is not None:
                row.status = "seguita"
            elif row.status == "seguita":
                row.status = None
        session.flush()
        return schemas.CalendarEntryStateView(
            id=row.id,
            date=row.date,
            entry_key=row.entry_key,
            template_entry_id=row.template_entry_id,
            override_id=row.override_id,
            status=row.status,
            note=row.note,
            lesson_id=row.lesson_id,
            manual_link=row.manual_link,
        )



# ---------------------------------------------------------------------------
# Risoluzione Lezione e Avanzamento Studio
# ---------------------------------------------------------------------------

def _get_lesson_metadata(lesson: Lesson) -> Dict[str, str]:
    """Legge i metadati di una lezione (info.yaml o colonne del DB)."""
    data = {"ora": "", "titolo": lesson.titolo or "", "materia": lesson.materia or "", "data": lesson.data or ""}
    try:
        info_file = lesson_path(lesson.path, "info.yaml")
        if fs.exists(info_file):
            info = read_info_yaml(info_file)
            data["ora"] = str(info.get("ora") or "")
            if not data["titolo"] and info.get("titolo"):
                data["titolo"] = str(info.get("titolo"))
            if not data["materia"] and info.get("materia"):
                data["materia"] = str(info.get("materia"))
            if not data["data"] and info.get("data"):
                data["data"] = str(info.get("data"))
    except Exception:
        pass
    return data


def _build_lesson_summary(
    session: Session, lesson: Lesson
) -> schemas.CalendarLessonSummary:
    meta = _get_lesson_metadata(lesson)
    title = lesson.titolo or meta.get("titolo") or lesson.argomenti or lesson.folder_name

    # Unità apprese sulla scaletta attuale (come il riepilogo dello Studio)
    unit_ids = current_unit_ids(lesson.path)
    units_learned = sum(
        1
        for u in session.scalars(select(StudyUnit).where(StudyUnit.lesson_id == lesson.id))
        if u.status == "appreso" and u.unit_id in unit_ids
    )
    units_total = len(unit_ids)

    state_str = lesson.workflow_state or ""
    is_proc = state_str not in ("completato", "fallito", "")

    return schemas.CalendarLessonSummary(
        id=lesson.id,
        path=lesson.path,
        titolo=title,
        materia=lesson.materia or meta.get("materia", ""),
        data=lesson.data or meta.get("data", ""),
        ora=meta.get("ora", ""),
        workflow_state=state_str,
        units_learned=units_learned,
        units_total=units_total,
        is_processing=is_proc,
    )


def _find_lesson_for_event(
    session: Session,
    date_str: str,
    start_time: str,
    materia: str,
    entry_state: Optional[CalendarEntryState],
) -> Tuple[Optional[schemas.CalendarLessonSummary], bool]:
    """Trova la lezione associata a un'ora: manuale vince, altrimenti calcolata."""
    # Collegamento manuale
    if entry_state and entry_state.manual_link:
        if entry_state.lesson_id is not None:
            lesson = session.get(Lesson, entry_state.lesson_id)
            if lesson is not None:
                return _build_lesson_summary(session, lesson), True
        return None, True

    # Collegamento automatico: stessa data, materia e ora di inizio
    norm_event_subject = normalize_subject(materia)
    norm_event_time = normalize_time(start_time)

    candidate_lessons = session.scalars(
        select(Lesson).where(Lesson.data == date_str)
    ).all()

    for cand in candidate_lessons:
        cand_meta = _get_lesson_metadata(cand)
        cand_subject = normalize_subject(cand.materia or cand_meta.get("materia"))
        cand_time = normalize_time(cand_meta.get("ora", ""))
        if cand_subject == norm_event_subject and cand_time == norm_event_time:
            return _build_lesson_summary(session, cand), False

    return None, False


# ---------------------------------------------------------------------------
# Costruzione della Vista Calendario
# ---------------------------------------------------------------------------

def _resolve_day_events(
    session: Session,
    target_date: datetime.date,
    template_entries: List[CalendarTemplateEntry],
    day_overrides: List[CalendarOverride],
    day_state: Optional[CalendarDayState],
    entry_states_by_key: Dict[str, CalendarEntryState],
    now: datetime.datetime,
) -> List[schemas.CalendarEventView]:
    date_str = target_date.isoformat()
    day_of_week = target_date.weekday()

    # Slot del template per questo giorno
    slots: List[Dict[str, Any]] = []
    removed_template_ids = {
        ov.template_entry_id for ov in day_overrides if ov.action == "removed" and ov.template_entry_id
    }
    modified_by_tpl_id = {
        ov.template_entry_id: ov for ov in day_overrides if ov.action == "modified" and ov.template_entry_id
    }

    for tpl in template_entries:
        if tpl.day_of_week != day_of_week or not _template_valid_on(tpl, date_str):
            continue
        if tpl.id in removed_template_ids:
            continue
        if tpl.id in modified_by_tpl_id:
            ov = modified_by_tpl_id[tpl.id]
            slots.append({
                "key": f"tpl_{tpl.id}",
                "template_entry_id": tpl.id,
                "override_id": ov.id,
                "is_modified": True,
                "start_time": ov.start_time or tpl.start_time,
                "end_time": ov.end_time or tpl.end_time,
                "materia": ov.materia or tpl.materia,
                "docente": ov.docente or tpl.docente,
            })
        else:
            slots.append({
                "key": f"tpl_{tpl.id}",
                "template_entry_id": tpl.id,
                "override_id": None,
                "is_modified": False,
                "start_time": tpl.start_time,
                "end_time": tpl.end_time,
                "materia": tpl.materia,
                "docente": tpl.docente,
            })

    # Aggiunte puntuali per questa data
    for ov in day_overrides:
        if ov.action == "added":
            slots.append({
                "key": f"ovr_{ov.id}",
                "template_entry_id": None,
                "override_id": ov.id,
                "is_modified": True,
                "start_time": ov.start_time or "09:00",
                "end_time": ov.end_time or "11:00",
                "materia": ov.materia or "",
                "docente": ov.docente,
            })

    # Ordina per orario di inizio
    slots.sort(key=lambda s: time_to_float(s["start_time"]))

    events: List[schemas.CalendarEventView] = []
    day_status = (day_state.status if day_state else "") or ""

    for s in slots:
        key = s["key"]
        es = entry_states_by_key.get(key)
        start_f = time_to_float(s["start_time"])
        end_f = time_to_float(s["end_time"])

        lesson_summary, _is_manual = _find_lesson_for_event(
            session, date_str, s["start_time"], s["materia"], es
        )

        # Risoluzione stato
        if day_status == "annullata" or (es and es.status == "annullata"):
            effective_status = "annullata"
        elif lesson_summary is not None:
            effective_status = "seguita"
        elif es and es.status:
            effective_status = es.status
        elif day_status:
            effective_status = day_status
        else:
            # Calcolo passato / futuro
            slot_end_dt = datetime.datetime.combine(
                target_date,
                datetime.time(int(end_f), int(round((end_f - int(end_f)) * 60))),
            )
            is_past = slot_end_dt < now
            effective_status = "nonseguita" if is_past else "seguire"

        events.append(
            schemas.CalendarEventView(
                key=key,
                date=date_str,
                day_of_week=day_of_week,
                start_time=normalize_time(s["start_time"]),
                end_time=normalize_time(s["end_time"]),
                start_hour=start_f,
                end_hour=end_f,
                materia=s["materia"],
                docente=s["docente"],
                status=effective_status,
                note=es.note if es else None,
                is_modified=s["is_modified"],
                is_recorded=lesson_summary is not None,
                template_entry_id=s["template_entry_id"],
                override_id=s["override_id"],
                lesson=lesson_summary,
            )
        )

    return events


def _resolve_dates(
    session: Session, dates: List[datetime.date], now: datetime.datetime
) -> Dict[str, Tuple[List[schemas.CalendarEventView], Optional[CalendarDayState]]]:
    """Ore e stato del giorno per ogni data, con poche query per tutto l'intervallo."""
    date_strs = [d.isoformat() for d in dates]
    templates = session.scalars(
        select(CalendarTemplateEntry).order_by(
            CalendarTemplateEntry.day_of_week,
            CalendarTemplateEntry.start_time,
        )
    ).all()

    overrides_by_date: Dict[str, List[CalendarOverride]] = {}
    for ov in session.scalars(
        select(CalendarOverride).where(CalendarOverride.date.in_(date_strs))
    ):
        overrides_by_date.setdefault(ov.date, []).append(ov)

    day_states_by_date = {
        ds.date: ds
        for ds in session.scalars(
            select(CalendarDayState).where(CalendarDayState.date.in_(date_strs))
        )
    }

    entry_states_by_date_key: Dict[str, Dict[str, CalendarEntryState]] = {}
    for es in session.scalars(
        select(CalendarEntryState).where(CalendarEntryState.date.in_(date_strs))
    ):
        entry_states_by_date_key.setdefault(es.date, {})[es.entry_key] = es

    resolved = {}
    for d in dates:
        d_str = d.isoformat()
        events = _resolve_day_events(
            session=session,
            target_date=d,
            template_entries=templates,
            day_overrides=overrides_by_date.get(d_str, []),
            day_state=day_states_by_date.get(d_str),
            entry_states_by_key=entry_states_by_date_key.get(d_str, {}),
            now=now,
        )
        resolved[d_str] = (events, day_states_by_date.get(d_str))
    return resolved


def _day_view(
    d: datetime.date,
    events: List[schemas.CalendarEventView],
    day_state: Optional[CalendarDayState],
    today: datetime.date,
) -> schemas.CalendarDayView:
    return schemas.CalendarDayView(
        date=d.isoformat(),
        day_of_week=d.weekday(),
        day_name=DAYS[d.weekday()],
        day_number=d.day,
        month_name=MESI[d.month - 1],
        status=day_state.status if day_state else "",
        note=day_state.note if day_state else None,
        is_today=(d == today),
        events=events,
        hours=events,
    )


def _event_end(ev: schemas.CalendarEventView) -> datetime.datetime:
    return datetime.datetime.combine(
        datetime.date.fromisoformat(ev.date),
        datetime.time(int(ev.end_hour), int(round((ev.end_hour - int(ev.end_hour)) * 60))),
    )


def get_week_view(target_date_str: str, db=None) -> schemas.CalendarWeekView:
    target = parse_date(target_date_str)
    monday = target - datetime.timedelta(days=target.weekday())
    friday = monday + datetime.timedelta(days=4)
    week_dates = [monday + datetime.timedelta(days=i) for i in range(5)]
    # "Da recuperare" guarda anche la settimana precedente, come nel riepilogo ⓘ.
    previous_dates = [d - datetime.timedelta(days=7) for d in week_dates]

    now = datetime.datetime.now()
    today = now.date()

    database = db or get_database()
    with read_scope(database) as session:
        resolved = _resolve_dates(session, previous_dates + week_dates, now)

        days = [_day_view(d, *resolved[d.isoformat()], today) for d in week_dates]
        all_week_events = [ev for day in days for ev in day.events]

        # Calcolo riassunto settimana (ⓘ)
        hours_total = sum(
            (e.end_hour - e.start_hour) for e in all_week_events if e.status != "annullata"
        )
        recorded_count = sum(1 for e in all_week_events if e.lesson is not None)
        skip_count = sum(1 for e in all_week_events if e.status == "saltare")
        modified_count = sum(1 for e in all_week_events if e.is_modified)

        # "Da recuperare": ore passate non seguite e senza lezione, in questa settimana e nella precedente
        to_recover: List[schemas.CalendarToRecoverItem] = []
        for d in previous_dates + week_dates:
            for ev in resolved[d.isoformat()][0]:
                if ev.status == "nonseguita" and ev.lesson is None and _event_end(ev) < now:
                    to_recover.append(
                        schemas.CalendarToRecoverItem(
                            key=ev.key,
                            date=ev.date,
                            day_of_week=ev.day_of_week,
                            day_name=DAYS[ev.day_of_week],
                            day_number=d.day,
                            month_number=d.month,
                            materia=ev.materia,
                            start_time=ev.start_time,
                            end_time=ev.end_time,
                        )
                    )

        # Costruzione label settimana (es. "12–16 ottobre" oppure "28 settembre – 2 ottobre")
        if monday.month == friday.month:
            label = f"{monday.day}–{friday.day} {MESI[monday.month - 1]}"
        else:
            label = f"{monday.day} {MESI[monday.month - 1]} – {friday.day} {MESI[friday.month - 1]}"

        summary = schemas.CalendarWeekSummary(
            hours_total=round(hours_total, 1),
            recorded_count=recorded_count,
            skip_count=skip_count,
            modified_hours_count=modified_count,
            to_recover=to_recover,
        )

        return schemas.CalendarWeekView(
            week_number=f"{monday.isocalendar()[1]:02d}",
            start_date=monday.isoformat(),
            end_date=friday.isoformat(),
            label=label,
            days=days,
            summary=summary,
        )


def get_day_view(target_date_str: str, db=None) -> schemas.CalendarDayView:
    target = parse_date(target_date_str)
    now = datetime.datetime.now()

    database = db or get_database()
    with read_scope(database) as session:
        events, day_state = _resolve_dates(session, [target], now)[target.isoformat()]
        return _day_view(target, events, day_state, now.date())


def get_day_import_view(target_date_str: str, db=None) -> schemas.CalendarDayImportView:
    """Restituisce le ore del giorno per l'import (CA1e)."""
    day_view = get_day_view(target_date_str, db=db)
    hours: List[schemas.CalendarDayImportHour] = []
    for ev in day_view.events:
        hours.append(
            schemas.CalendarDayImportHour(
                start_time=ev.start_time,
                end_time=ev.end_time,
                materia=ev.materia,
                docente=ev.docente,
                status=ev.status,
                is_recorded=(ev.lesson is not None),
                lesson_id=ev.lesson.id if ev.lesson else None,
                lesson_title=ev.lesson.titolo if ev.lesson else None,
            )
        )
    return schemas.CalendarDayImportView(
        date=day_view.date,
        hours=hours,
    )



def get_year_view(start: str, db=None) -> List[schemas.CalendarYearWeek]:
    monday = parse_date(start)
    if monday.weekday() != 0 or (monday + datetime.timedelta(days=3)).month != 9 or monday.day not in (1, 2, 3, 4, 29, 30, 31):
        raise Invalid('invalid_year_start', "Indica il lunedì della prima settimana di settembre.")
    september = datetime.date((monday + datetime.timedelta(days=3)).year + 1, 9, 4)
    end = september - datetime.timedelta(days=september.weekday())
    dates = [monday + datetime.timedelta(days=i) for i in range((end - monday).days) if i % 7 < 5]
    with read_scope(db or get_database()) as session:
        resolved = _resolve_dates(session, dates, datetime.datetime.now())
        weeks = []
        for offset in range(0, len(dates), 5):
            days = []
            for day in dates[offset:offset + 5]:
                events, state = resolved[day.isoformat()]
                days.append(schemas.CalendarYearDay(date=day.isoformat(), status=state.status if state else '', events=[
                    schemas.CalendarYearEvent(**event.model_dump(include={'start_hour', 'end_hour', 'materia', 'status', 'is_recorded'}))
                    for event in events]))
            weeks.append(schemas.CalendarYearWeek(start_date=dates[offset].isoformat(),
                         week_number=dates[offset].isocalendar()[1], days=days))
        return weeks
