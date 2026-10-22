from datetime import datetime
from rt.services import calendar_models as m, calendar_service as c
from rt.services.notes_lesson_service import create_notes_lesson
from tests.api_support import isolated_workspace


def test_missing_resolves_states_overrides_and_links(rt_db, tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    assert c.get_missing_lessons(rt_db).model_dump() == {'start': None, 'subjects': []}
    c.set_period_start(m.CalendarPeriodStart(date='2026-10-14'), rt_db)
    assert c.get_week_view('2026-10-12', rt_db).summary.is_period_start
    for day in range(5):
        c.create_template_entry(m.CalendarTemplateEntryCreate(day_of_week=day, start_time='09:00', end_time='10:00', materia=' Data Mining ', valid_from='2026-10-12'), rt_db)
    create_notes_lesson('notes', date='2026-10-12', materia='DATA MINING', ora='09:00', dest_dir=root)
    c.set_day_state(m.CalendarDayStateSet(date='2026-10-13', status='annullata'), rt_db)
    c.set_day_state(m.CalendarDayStateSet(date='2026-10-14', status='saltare'), rt_db)
    thursday = c.get_day_view('2026-10-15', rt_db).events[0]
    c.create_override(m.CalendarOverrideCreate(date='2026-10-15', action='modified', materia='Data Mining', template_entry_id=thursday.template_entry_id, start_time='11:00', end_time='12:00'), rt_db)
    before = c.get_missing_lessons(rt_db, now=datetime(2026, 10, 15, 11, 30))
    assert before.subjects == []
    after = c.get_missing_lessons(rt_db, now=datetime(2026, 10, 15, 12, 1))
    assert after.start == '2026-10-12'
    assert len(after.subjects) == 1
    subject = after.subjects[0]
    assert subject.materia == 'DATA MINING'
    assert len(subject.missing) == 1
    assert subject.missing[0].date == '2026-10-15'
    assert subject.missing[0].start_time == '11:00'
    c.set_entry_state(m.CalendarEntryStateSet(date='2026-10-15', entry_key=thursday.key, status='saltare', template_entry_id=thursday.template_entry_id), rt_db)
    assert c.get_missing_lessons(rt_db, now=datetime(2026, 10, 15, 12, 1)).subjects == []


def test_period_api(api_client, rt_db):
    assert api_client.get('/api/v1/calendar/missing').json() == {'start': None, 'subjects': []}
    response = api_client.put('/api/v1/calendar/period-start', json={'date': '2026-10-14'})
    assert response.status_code == 200
    assert response.json() == {'date': '2026-10-12'}
    assert api_client.get('/api/v1/calendar/week?date=2026-10-12').json()['summary']['is_period_start']
    assert api_client.put('/api/v1/calendar/period-start', json={'date': 'invalid'}).status_code == 422
    assert api_client.put('/api/v1/calendar/period-start', json={'date': None}).status_code == 200
    assert api_client.get('/api/v1/calendar/missing').json()['start'] is None
