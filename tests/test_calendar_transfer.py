"""Anno e scambio atomico dell'orario."""
import datetime

import pytest
from sqlalchemy import event, select

from rt.services import calendar_service as calendar, calendar_models as schemas
from rt.services.calendar_transfer import export_schedule, import_schedule, paste_week
from rt.services.errors import Invalid
from rt.db.models import CalendarEntryState, CalendarOverride, CalendarTemplateEntry, Lesson
from rt.db.session import session_scope


def template(rt_db, **kwargs):
    return calendar.create_template_entry(schemas.CalendarTemplateEntryCreate(day_of_week=0, start_time='09:00',
        end_time='11:00', materia='Biologia', docente='Rossi', valid_from='2026-09-01', **kwargs), db=rt_db)


def schedule(rt_db):
    return export_schedule(rt_db).model_dump(mode='json')


def test_year_matches_week_with_one_read_of_calendar_tables(rt_db):
    template(rt_db)
    calendar.create_override(schemas.CalendarOverrideCreate(date='2026-10-12', action='added', start_time='12:00', end_time='13:00', materia='Chimica'), db=rt_db)
    queries = []
    def capture(conn, cursor, statement, *args):
        queries.append(statement)
    event.listen(rt_db.engine, 'before_cursor_execute', capture)
    try:
        year = calendar.get_year_view('2026-08-31', db=rt_db)
    finally:
        event.remove(rt_db.engine, 'before_cursor_execute', capture)
    assert len(year) in (52, 53)
    for table in ('calendar_template_entries', 'calendar_overrides', 'calendar_day_states', 'calendar_entry_states'):
        assert sum(f'FROM {table}' in query for query in queries) == 1
    monday = '2026-10-12'
    week = calendar.get_week_view(monday, db=rt_db)
    compact = next(row for row in year if row.start_date == monday)
    for short, full in zip(compact.days, week.days):
        assert short.date == full.date
        assert [e.model_dump() for e in short.events] == [e.model_dump(include={'start_hour', 'end_hour', 'materia', 'status', 'is_recorded'}) for e in full.events]


def test_paste_preserves_recorded_and_nondefault_hours_and_replaces_others(rt_db):
    future = (datetime.date.today() + datetime.timedelta(days=14))
    monday = (future - datetime.timedelta(days=future.weekday())).isoformat()
    entry = template(rt_db)
    day = calendar.parse_date(monday) + datetime.timedelta(days=1)
    extra = calendar.create_override(schemas.CalendarOverrideCreate(date=day.isoformat(), action='added', start_time='10:00', end_time='11:00', materia='Vecchia'), db=rt_db)
    protected = calendar.create_override(schemas.CalendarOverrideCreate(date=monday, action='added', start_time='12:00', end_time='13:00', materia='Protetta'), db=rt_db)
    calendar.set_entry_state(schemas.CalendarEntryStateSet(date=monday, entry_key=f'ovr_{protected.id}', status='saltare'), db=rt_db)
    with session_scope(rt_db) as s:
        lesson = Lesson(path='/recorded', folder_name='recorded', materia='Registrata')
        s.add(lesson); s.flush()
        recorded = CalendarOverride(date=monday, action='added', start_time='14:00', end_time='15:00', materia='Registrata')
        s.add(recorded); s.flush()
        s.add(CalendarEntryState(date=monday, entry_key=f'ovr_{recorded.id}', override_id=recorded.id, lesson_id=lesson.id, manual_link=True))
    paste_week(schemas.CalendarPasteRequest(weeks=[monday], entries=[schemas.CalendarPasteEntry(day_of_week=0, start_time='08:00', end_time='09:00', materia='Nuova')]), db=rt_db)
    week = calendar.get_week_view(monday, db=rt_db)
    assert [e.materia for e in week.days[0].events] == ['Nuova', 'Protetta', 'Registrata']
    assert not week.days[1].events
    assert week.days[0].events[-1].is_recorded


def test_paste_is_atomic_on_database_error(rt_db, monkeypatch):
    import rt.services.calendar_transfer as transfer
    future = datetime.date.today() + datetime.timedelta(days=14)
    monday = (future - datetime.timedelta(days=future.weekday())).isoformat()
    template(rt_db)
    before = schedule(rt_db)
    def fail(*args):
        raise RuntimeError('scrittura fallita')
    monkeypatch.setattr(transfer, 'register_teacher', fail)
    with pytest.raises(RuntimeError):
        paste_week(schemas.CalendarPasteRequest(weeks=[monday], entries=[schemas.CalendarPasteEntry(day_of_week=0, start_time='08:00', end_time='09:00', materia='Nuova')]), db=rt_db)
    after = schedule(rt_db)
    assert before['template'] == after['template'] and before['overrides'] == after['overrides']


def test_export_import_roundtrip_and_preserves_links_notes(rt_db):
    entry = template(rt_db)
    calendar.create_override(schemas.CalendarOverrideCreate(date='2026-10-12', action='modified', template_entry_id=entry.id, start_time='10:00', end_time='12:00', materia='Biologia'), db=rt_db)
    with session_scope(rt_db) as s:
        lesson = Lesson(path='/linked', folder_name='linked')
        s.add(lesson); s.flush()
        lid = lesson.id
    calendar.link_lesson(schemas.CalendarLinkLessonRequest(date='2026-10-12', entry_key=f'tpl_{entry.id}', template_entry_id=entry.id, lesson_id=lid), db=rt_db)
    calendar.set_entry_state(schemas.CalendarEntryStateSet(date='2026-10-12', entry_key=f'tpl_{entry.id}', note='Nota privata'), db=rt_db)
    data = schedule(rt_db)
    assert 'Nota privata' not in str(data) and '/linked' not in str(data)
    import_schedule(schemas.CalendarImportRequest(data=data), db=rt_db)
    after = schedule(rt_db)
    assert after['template'] == data['template'] and after['overrides'] == data['overrides']
    hour = calendar.get_day_view('2026-10-12', db=rt_db).events[0]
    assert hour.lesson.id == lid and hour.note == 'Nota privata'
    assert after['subjects'][0]['teachers'] == ['Rossi']


def test_import_period_is_inclusive_and_dry_run_has_no_writes(rt_db):
    template(rt_db)
    data = schedule(rt_db)
    data['template'][0]['materia'] = 'Nuova'
    request = schemas.CalendarImportRequest(data=data, **{'from': '2026-10-12', 'to': '2026-10-19'}, dry_run=True)
    result = import_schedule(request, db=rt_db)
    assert result.conflicts == 2
    assert calendar.get_day_view('2026-10-12', db=rt_db).events[0].materia == 'Biologia'
    request.dry_run = False
    import_schedule(request, db=rt_db)
    for date, expected in [('2026-10-05', 'Biologia'), ('2026-10-12', 'Nuova'), ('2026-10-19', 'Nuova'), ('2026-10-26', 'Biologia')]:
        assert calendar.get_day_view(date, db=rt_db).events[0].materia == expected


@pytest.mark.parametrize('change', [lambda d: d.update(format='wrong'), lambda d: d.update(version=2),
    lambda d: d['template'][0].update(start_time='25:00'), lambda d: d['template'][0].update(end_time='08:00'),
    lambda d: d.update(template=d['template'] * 2001), lambda d: d.update(exported_at='x' * 1048576)])
def test_invalid_import_rejected(rt_db, change):
    template(rt_db)
    data = schedule(rt_db)
    change(data)
    with pytest.raises(Invalid):
        import_schedule(schemas.CalendarImportRequest(data=data), db=rt_db)
    assert len(calendar.list_template_entries(rt_db)) == 1


def test_calendar_transfer_api_returns_validation_errors(api_client, rt_db):
    template(rt_db)
    exported = api_client.get('/api/v1/calendar/export')
    assert exported.status_code == 200
    assert 'rt-orario-' in exported.headers['content-disposition']
    assert api_client.get('/api/v1/calendar/year?start=2026-08-31').status_code == 200
    assert api_client.post('/api/v1/calendar/import', json={'data': {'format': 'wrong'}, 'dry_run': True}).status_code == 422
    assert api_client.post('/api/v1/calendar/paste', json={'weeks': ['2026-10-13'], 'entries': []}).status_code == 422
    assert api_client.post('/api/v1/calendar/import', json={'data': exported.json(), 'dry_run': True}).json()['conflicts'] == 1
