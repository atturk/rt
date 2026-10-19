"""Appunti e scambio dell'orario: scritture atomiche, senza esportare dati personali delle lezioni."""
import datetime
import json

from pydantic import ValidationError
from sqlalchemy import delete, select

from rt.db.engine import get_database
from rt.db.models import CalendarEntryState, CalendarOverride, CalendarTemplateEntry
from rt.db.session import read_scope, session_scope
from rt.services import calendar_models as schemas
from rt.services import calendar_service as calendar
from rt.services.errors import Invalid
from rt.services.subjects import _view, register_subject, register_teacher


def _check_entry(entry):
    if not entry.materia or not entry.materia.strip() or not entry.start_time or not entry.end_time or entry.start_time >= entry.end_time:
        raise Invalid('invalid_calendar_file', 'Indica materia e orari validi.')


def paste_week(data: schemas.CalendarPasteRequest, db=None):
    weeks = list(dict.fromkeys(data.weeks))
    for week in weeks:
        if calendar.parse_date(week).weekday() != 0:
            raise Invalid('invalid_week', 'Le settimane devono iniziare di lunedì.')
    for entry in data.entries:
        _check_entry(entry)
    with session_scope(db or get_database()) as session:
        dates = [calendar.parse_date(week) + datetime.timedelta(days=i) for week in weeks for i in range(7)]
        resolved = calendar._resolve_dates(session, dates, datetime.datetime.now())
        for date, (events, _) in resolved.items():
            for event in events:
                # Le ore già seguite, registrate, saltate o annullate restano al loro posto.
                if event.is_recorded or event.status != 'seguire':
                    continue
                if event.override_id:
                    override = session.get(CalendarOverride, event.override_id)
                    if override is not None:
                        session.delete(override)
                if event.template_entry_id:
                    session.add(CalendarOverride(date=date, action='removed', template_entry_id=event.template_entry_id))
        session.flush()
        for week in weeks:
            for entry in data.entries:
                session.add(CalendarOverride(date=(calendar.parse_date(week) + datetime.timedelta(days=entry.day_of_week)).isoformat(),
                                            action='added', **entry.model_dump(exclude={'day_of_week'})))
                register_teacher(session, entry.materia, entry.docente)
                register_subject(session, entry.materia)
        session.flush()
    return schemas.CalendarPasteResult(weeks=weeks)


def export_schedule(db=None):
    with read_scope(db or get_database()) as session:
        templates = list(session.scalars(select(CalendarTemplateEntry).order_by(CalendarTemplateEntry.id)))
        indices = {entry.id: i for i, entry in enumerate(templates)}
        return schemas.CalendarSchedule(format='rt-calendar', version=1,
            exported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            subjects=[schemas.CalendarScheduleSubject(name=row['nome'], teachers=row['docenti']) for row in _view(session)],
            template=[schemas.CalendarTemplateEntryCreate(**{key: getattr(entry, key) for key in
                      ('day_of_week', 'start_time', 'end_time', 'materia', 'docente', 'valid_from', 'valid_to')}) for entry in templates],
            overrides=[schemas.CalendarScheduleOverride(date=entry.date, action=entry.action,
                       start_time=entry.start_time, end_time=entry.end_time, materia=entry.materia, docente=entry.docente,
                       template_index=indices.get(entry.template_entry_id))
                       for entry in session.scalars(select(CalendarOverride).order_by(CalendarOverride.id))])


def _validate(data):
    try:
        if len(json.dumps(data, ensure_ascii=False).encode('utf-8')) > 1024 * 1024:
            raise ValueError()
        schedule = schemas.CalendarSchedule.model_validate(data)
        if len(schedule.template) + len(schedule.overrides) > 2000:
            raise ValueError()
        for entry in schedule.template:
            _check_entry(entry)
            if entry.valid_to and entry.valid_to <= (entry.valid_from or '2000-01-01'):
                raise ValueError()
        for entry in schedule.overrides:
            if entry.action in ('added', 'modified'):
                _check_entry(entry)
            if entry.action != 'added' and entry.template_index is None:
                raise ValueError()
            if entry.template_index is not None and entry.template_index >= len(schedule.template):
                raise ValueError()
        if any(not subject.name.strip() or any(not name.strip() or len(name) > 256 for name in subject.teachers)
               for subject in schedule.subjects):
            raise ValueError()
        return schedule
    except (ValueError, TypeError, ValidationError):
        raise Invalid('invalid_calendar_file', 'Il file non contiene un orario valido (massimo 1 MB e 2000 voci).') from None


def _conflicts(session, start, end):
    templates = list(session.scalars(select(CalendarTemplateEntry)))
    overrides = list(session.scalars(select(CalendarOverride)))
    if start is None:
        return len(templates) + sum(entry.action == 'added' for entry in overrides)
    count = 0
    for entry in templates:
        first = calendar.parse_date(max(start, entry.valid_from))
        last = calendar.parse_date(min(end, entry.valid_to or end))
        first += datetime.timedelta(days=(entry.day_of_week - first.weekday()) % 7)
        if first < last:
            count += 1 + ((last - first).days - 1) // 7
    removed = set()
    for entry in overrides:
        if start <= entry.date < end:
            if entry.action == 'added':
                count += 1
            elif entry.action == 'removed' and (entry.date, entry.template_entry_id) not in removed:
                template = next((t for t in templates if t.id == entry.template_entry_id), None)
                if template and calendar._template_valid_on(template, entry.date) and calendar.parse_date(entry.date).weekday() == template.day_of_week:
                    count -= 1
                    removed.add((entry.date, entry.template_entry_id))
    return count


def _signature(date, event):
    return date, event.start_time, event.end_time, event.materia.strip().casefold()


def import_schedule(request: schemas.CalendarImportRequest, db=None):
    schedule = _validate(request.data)
    start, to = request.from_date, request.to_date
    if bool(start) != bool(to) or (start and to < start):
        raise Invalid('invalid_date_range', 'Indica un periodo valido con entrambe le date.')
    # Dal/Al includono entrambi i giorni; valid_to dei modelli rimane esclusiva.
    end = (calendar.parse_date(to) + datetime.timedelta(days=1)).isoformat() if to else None
    database = db or get_database()
    with session_scope(database) as session:
        result = schemas.CalendarImportResult(subjects=len(schedule.subjects),
                  entries=len(schedule.template) + len(schedule.overrides), conflicts=_conflicts(session, start, end))
        if request.dry_run:
            return result
        states = list(session.scalars(select(CalendarEntryState)))
        states = [state for state in states if start is None or start <= state.date < end]
        state_dates = sorted({calendar.parse_date(state.date) for state in states})
        resolved = calendar._resolve_dates(session, state_dates, datetime.datetime.now()) if states else {}
        saved = []
        for state in states:
            event = next((event for event in resolved[state.date][0] if event.key == state.entry_key), None)
            if event:
                saved.append((_signature(state.date, event), {key: getattr(state, key)
                              for key in ('status', 'note', 'lesson_id', 'manual_link')}))
            session.delete(state)
        session.flush()
        for entry in list(session.scalars(select(CalendarTemplateEntry))):
            calendar._delete_template_range(session, entry.id, start, end)
        for override in list(session.scalars(select(CalendarOverride))):
            if start is None or start <= override.date < end:
                session.delete(override)
        session.flush()
        templates = {}
        for index, entry in enumerate(schedule.template):
            data = entry.model_dump()
            data['valid_from'] = max(start or '0001-01-01', entry.valid_from or '2000-01-01')
            ends = [value for value in (end, entry.valid_to) if value]
            data['valid_to'] = min(ends) if ends else None
            if data['valid_to'] and data['valid_to'] <= data['valid_from']:
                continue
            template = CalendarTemplateEntry(**data)
            session.add(template)
            session.flush()
            templates[index] = template.id
            register_subject(session, entry.materia)
            register_teacher(session, entry.materia, entry.docente)
        for entry in schedule.overrides:
            if start is not None and not (start <= entry.date < end):
                continue
            if entry.template_index is not None and entry.template_index not in templates:
                continue
            data = entry.model_dump(exclude={'template_index'})
            session.add(CalendarOverride(**data, template_entry_id=templates.get(entry.template_index)))
            register_subject(session, entry.materia)
            register_teacher(session, entry.materia, entry.docente)
        for subject in schedule.subjects:
            register_subject(session, subject.name)
            for name in subject.teachers:
                register_teacher(session, subject.name, name)
        session.flush()
        restored = calendar._resolve_dates(session, state_dates, datetime.datetime.now()) if states else {}
        for signature, data in saved:
            matches = [event for event in restored[signature[0]][0] if _signature(signature[0], event) == signature]
            if len(matches) == 1:
                event = matches[0]
                session.add(CalendarEntryState(date=signature[0], entry_key=event.key,
                    template_entry_id=event.template_entry_id, override_id=event.override_id, **data))
        return result
