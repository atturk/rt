"""Test per il calendario (4.2.5 CA1a)."""
import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from rt.api import schemas
from rt.api.app import create_app
from rt.services import calendar_service
from rt.services.errors import Invalid, NotFound

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def client(api_token, rt_db):
    app = create_app()
    c = TestClient(app, client=LOCAL)
    c.headers["Authorization"] = f"Bearer {api_token}"
    return c


def test_template_crud(rt_db):
    entry1 = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            valid_from="2026-10-01",
            day_of_week=0,  # Lunedì
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
            docente="Prof. Ferraris",
        ),
        db=rt_db,
    )
    assert entry1.id is not None
    assert entry1.materia == "Data Mining"
    assert entry1.start_time == "09:30"
    assert entry1.end_time == "11:30"

    entry2 = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            valid_from="2026-10-01",
            day_of_week=1,  # Martedì
            start_time="14:00",
            end_time="16:00",
            materia="Diritto",
        ),
        db=rt_db,
    )

    entries = calendar_service.list_template_entries(db=rt_db)
    assert len(entries) == 2
    assert entries[0].id == entry1.id
    assert entries[1].id == entry2.id

    calendar_service.delete_template_entry(entry1.id, db=rt_db)
    entries_after = calendar_service.list_template_entries(db=rt_db)
    assert len(entries_after) == 1
    assert entries_after[0].id == entry2.id

    with pytest.raises(NotFound):
        calendar_service.delete_template_entry(9999, db=rt_db)


def test_template_invalid_times(rt_db):
    with pytest.raises(Invalid):
        calendar_service.create_template_entry(
            schemas.CalendarTemplateEntryCreate(
                day_of_week=0,
                start_time="11:30",
                end_time="09:30",
                materia="Test",
            ),
            db=rt_db,
        )


def test_override_crud(rt_db):
    tpl = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
        ),
        db=rt_db,
    )

    # Aggiunta solo una settimana
    ov_add = calendar_service.create_override(
        schemas.CalendarOverrideCreate(
            date="2026-10-12",
            action="added",
            start_time="14:30",
            end_time="16:30",
            materia="Clinica",
            docente="Prof.ssa Villa",
        ),
        db=rt_db,
    )
    assert ov_add.id is not None
    assert ov_add.action == "added"
    assert ov_add.materia == "Clinica"

    # Rimozione solo quella settimana dello slot template
    ov_rem = calendar_service.create_override(
        schemas.CalendarOverrideCreate(
            date="2026-10-12",
            action="removed",
            template_entry_id=tpl.id,
        ),
        db=rt_db,
    )
    assert ov_rem.action == "removed"

    calendar_service.delete_override(ov_add.id, db=rt_db)
    with pytest.raises(NotFound):
        calendar_service.delete_override(ov_add.id, db=rt_db)


def test_day_state_and_entry_state(rt_db):
    # Stato intero giorno
    ds = calendar_service.set_day_state(
        schemas.CalendarDayStateSet(date="2026-10-14", status="saltare", note="Festa di laurea"),
        db=rt_db,
    )
    assert ds.date == "2026-10-14"
    assert ds.status == "saltare"
    assert ds.note == "Festa di laurea"

    got_ds = calendar_service.get_day_state("2026-10-14", db=rt_db)
    assert got_ds is not None
    assert got_ds.status == "saltare"

    # Stato singola ora
    es = calendar_service.set_entry_state(
        schemas.CalendarEntryStateSet(
            date="2026-10-12",
            entry_key="tpl_1",
            status="annullata",
            note="Docente assente",
        ),
        db=rt_db,
    )
    assert es.date == "2026-10-12"
    assert es.entry_key == "tpl_1"
    assert es.status == "annullata"
    assert es.note == "Docente assente"


def test_week_view_resolution(rt_db):
    # Template: Lunedì e Mercoledì
    tpl1 = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,  # Lunedì
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
        ),
        db=rt_db,
    )
    tpl2 = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=2,  # Mercoledì
            start_time="14:00",
            end_time="16:00",
            materia="Generale",
        ),
        db=rt_db,
    )

    # Modifica solo lunedì 2026-10-12: aggiunta Clinica
    calendar_service.create_override(
        schemas.CalendarOverrideCreate(
            date="2026-10-12",
            action="added",
            start_time="14:30",
            end_time="16:30",
            materia="Clinica",
        ),
        db=rt_db,
    )

    # Mercoledì 2026-10-14: tutto il giorno da saltare
    calendar_service.set_day_state(
        schemas.CalendarDayStateSet(date="2026-10-14", status="saltare"),
        db=rt_db,
    )

    week = calendar_service.get_week_view("2026-10-12", db=rt_db)
    assert week.start_date == "2026-10-12"
    assert week.end_date == "2026-10-16"
    assert week.label == "12–16 ottobre"
    assert len(week.days) == 5

    # Lunedì: 2 eventi (Data Mining da template, Clinica da override)
    monday = week.days[0]
    assert monday.date == "2026-10-12"
    assert len(monday.events) == 2
    assert monday.events[0].materia == "Data Mining"
    assert not monday.events[0].is_modified
    assert monday.events[1].materia == "Clinica"
    assert monday.events[1].is_modified

    # Mercoledì: 1 evento ereditato dal template, ma con stato "saltare" dal giorno
    wednesday = week.days[2]
    assert wednesday.date == "2026-10-14"
    assert len(wednesday.events) == 1
    assert wednesday.events[0].status == "saltare"
    assert wednesday.status == "saltare"

    # Sommario
    assert week.summary.hours_total == 6.0  # 2 + 2 + 2
    assert week.summary.skip_count == 1
    assert week.summary.modified_hours_count == 1


def test_api_calendar_endpoints(client, rt_db):
    # Template
    res = client.post(
        "/api/v1/calendar/template",
        json={
            "day_of_week": 0,
            "start_time": "09:30",
            "end_time": "11:30",
            "materia": "Elettromagnetismo",
            "docente": "Prof.ssa Bassi",
        },
    )
    assert res.status_code == 201, res.text
    tpl_id = res.json()["id"]

    res_list = client.get("/api/v1/calendar/template")
    assert res_list.status_code == 200
    assert any(t["id"] == tpl_id for t in res_list.json())

    # Override
    res_ov = client.post(
        "/api/v1/calendar/override",
        json={
            "date": "2026-10-12",
            "action": "added",
            "start_time": "14:00",
            "end_time": "16:00",
            "materia": "Diritto",
        },
    )
    assert res_ov.status_code == 201
    ov_id = res_ov.json()["id"]

    # Week view
    res_w = client.get("/api/v1/calendar/week?date=2026-10-12")
    assert res_w.status_code == 200
    w_data = res_w.json()
    assert w_data["label"] == "12–16 ottobre"
    assert len(w_data["days"]) == 5

    # Day view
    res_d = client.get("/api/v1/calendar/day?date=2026-10-12")
    assert res_d.status_code == 200
    d_data = res_d.json()
    assert d_data["date"] == "2026-10-12"
    assert len(d_data["events"]) == 2  # Elettromagnetismo + Diritto

    # Day state
    res_ds = client.post(
        "/api/v1/calendar/day-state",
        json={"date": "2026-10-12", "status": "annullata", "note": "Giorno sospeso"},
    )
    assert res_ds.status_code == 200
    assert res_ds.json()["status"] == "annullata"

    # Entry state
    res_es = client.post(
        "/api/v1/calendar/entry-state",
        json={"date": "2026-10-12", "entry_key": f"tpl_{tpl_id}", "status": "seguire", "note": "Portare appunti"},
    )
    assert res_es.status_code == 200
    assert res_es.json()["note"] == "Portare appunti"

    # Cleanup
    assert client.delete(f"/api/v1/calendar/override/{ov_id}").status_code == 204
    assert client.delete(f"/api/v1/calendar/template/{tpl_id}").status_code == 204


def test_automatic_lesson_link(tmp_path, rt_db, monkeypatch):
    """CA1b: Una lezione con stessa data, ora e materia si collega automaticamente all'ora e la segna Seguita."""
    # Scaletta attuale di 4 unità: il totale viene da qui, non dalle righe di studio.
    monkeypatch.setattr(calendar_service, "current_unit_ids", lambda _path: {"u1", "u2", "u3", "u4"})
    tpl = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,  # Lunedì
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
            docente="Prof. Ferraris",
        ),
        db=rt_db,
    )

    lesson_dir = tmp_path / "2026-10-12-data-mining"
    lesson_dir.mkdir()
    (lesson_dir / "info.yaml").write_text(
        "data: '2026-10-12'\nora: '09:30'\nmateria: 'Data Mining'\ntitolo: 'Clustering gerarchico'\n",
        encoding="utf-8",
    )

    from rt.db.session import session_scope
    from rt.db.repositories import LessonRepository
    from rt.db.models import CalendarEntryState, StudyUnit

    with session_scope(rt_db) as s:
        lesson = LessonRepository(s).get_or_create(str(lesson_dir))
        lesson.data = "2026-10-12"
        lesson.materia = "DATA MINING"
        lesson.titolo = "Clustering gerarchico"
        # Aggiunge 3 unità: 2 apprese, 1 da-imparare
        s.add(StudyUnit(lesson_id=lesson.id, unit_id="u1", status="appreso"))
        s.add(StudyUnit(lesson_id=lesson.id, unit_id="u2", status="appreso"))
        s.add(StudyUnit(lesson_id=lesson.id, unit_id="u3", status="da-imparare"))
        # Unità tolta dalla scaletta: non conta
        s.add(StudyUnit(lesson_id=lesson.id, unit_id="vecchia", status="appreso"))

    # Verifica week view
    week = calendar_service.get_week_view("2026-10-12", db=rt_db)
    monday = week.days[0]
    assert len(monday.events) == 1
    ev = monday.events[0]

    assert ev.status == "seguita"
    assert ev.is_recorded is True
    assert ev.lesson is not None
    assert ev.lesson.titolo == "Clustering gerarchico"
    assert ev.lesson.units_learned == 2
    assert ev.lesson.units_total == 4

    # Nel DB calendar_entry_states non dev'esserci alcun record scritto a mano
    with session_scope(rt_db) as s:
        row = s.scalars(select(CalendarEntryState).where(CalendarEntryState.date == "2026-10-12")).first()
        assert row is None or not row.manual_link


def test_manual_link_wins_over_automatic(tmp_path, rt_db):
    """CA1b: Il collegamento fatto a mano vince su quello calcolato."""
    tpl = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,  # Lunedì
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
        ),
        db=rt_db,
    )

    # Lezione automatica che corrisponderebbe
    auto_dir = tmp_path / "auto_lesson"
    auto_dir.mkdir()
    (auto_dir / "info.yaml").write_text("data: '2026-10-12'\nora: '09:30'\nmateria: 'Data Mining'\ntitolo: 'Auto'\n")

    # Lezione manuale diversa
    manual_dir = tmp_path / "manual_lesson"
    manual_dir.mkdir()
    (manual_dir / "info.yaml").write_text("data: '2026-10-10'\nora: '15:00'\nmateria: 'Generale'\ntitolo: 'Manuale'\n")

    from rt.db.session import session_scope
    from rt.db.repositories import LessonRepository

    with session_scope(rt_db) as s:
        l_auto = LessonRepository(s).get_or_create(str(auto_dir))
        l_auto.data = "2026-10-12"
        l_auto.materia = "DATA MINING"
        l_auto.titolo = "Auto"

        l_man = LessonRepository(s).get_or_create(str(manual_dir))
        l_man.data = "2026-10-10"
        l_man.materia = "GENERALE"
        l_man.titolo = "Manuale"
        man_id = l_man.id

    # Collega manualmente la lezione manuale
    calendar_service.link_lesson(
        schemas.CalendarLinkLessonRequest(
            date="2026-10-12",
            entry_key=f"tpl_{tpl.id}",
            lesson_id=man_id,
        ),
        db=rt_db,
    )

    week = calendar_service.get_week_view("2026-10-12", db=rt_db)
    ev = week.days[0].events[0]
    assert ev.lesson is not None
    assert ev.lesson.id == man_id
    assert ev.lesson.titolo == "Manuale"
    assert ev.status == "seguita"

    # Se l'utente scollega a mano la lezione (lesson_id=None con manual_link=True)
    calendar_service.link_lesson(
        schemas.CalendarLinkLessonRequest(
            date="2026-10-12",
            entry_key=f"tpl_{tpl.id}",
            lesson_id=None,
        ),
        db=rt_db,
    )

    week_unlinked = calendar_service.get_week_view("2026-10-12", db=rt_db)
    ev_unlinked = week_unlinked.days[0].events[0]
    # Lo scollegamento manuale vince: non deve ripescare la lezione automatica
    assert ev_unlinked.lesson is None
    assert ev_unlinked.is_recorded is False


def test_calendar_day_import_api(tmp_path, rt_db, client):
    """CA1e: GET /calendar/day?date= restituisce le ore del giorno e lo stato 'già registrata' per il popup di import."""
    from rt.db.session import session_scope
    from rt.db.repositories import LessonRepository

    # Slot 1: Data Mining 09:30-11:30 (avrà una lezione collegata -> is_recorded = True)
    calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,  # Lunedì
            start_time="09:30",
            end_time="11:30",
            materia="Data Mining",
            docente="Prof. Ferraris",
        ),
        db=rt_db,
    )

    # Slot 2: Elettromagnetismo 11:30-13:30 (non registrata -> is_recorded = False)
    calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(
            day_of_week=0,  # Lunedì
            start_time="11:30",
            end_time="13:30",
            materia="Elettromagnetismo",
            docente="Prof.ssa Bassi",
        ),
        db=rt_db,
    )

    # Crea lezione per Data Mining
    l_dir = tmp_path / "dm_import_lesson"
    l_dir.mkdir()
    (l_dir / "info.yaml").write_text("data: '2026-10-12'\nora: '09:30'\nmateria: 'Data Mining'\ntitolo: 'DM Lez 1'\n")

    with session_scope(rt_db) as s:
        l = LessonRepository(s).get_or_create(str(l_dir))
        l.data = "2026-10-12"
        l.materia = "DATA MINING"
        l.titolo = "DM Lez 1"

    res = client.get("/api/v1/calendar/day?date=2026-10-12")
    assert res.status_code == 200
    data = res.json()
    assert data["date"] == "2026-10-12"
    assert data["day_name"] == "Lun"
    assert len(data["hours"]) == 2
    assert len(data["events"]) == 2

    # Verifica slot 1: già registrata (spenta nel popup)
    dm_hour = next(h for h in data["hours"] if h["materia"] == "Data Mining")
    assert dm_hour["start_time"] == "09:30"
    assert dm_hour["end_time"] == "11:30"
    assert dm_hour["docente"] == "Prof. Ferraris"
    assert dm_hour["is_recorded"] is True
    assert dm_hour["status"] == "seguita"
    assert dm_hour["lesson"] is not None
    assert dm_hour["lesson"]["titolo"] == "DM Lez 1"

    # Verifica slot 2: non ancora registrata (attiva come scelta rapida)
    em_hour = next(h for h in data["hours"] if h["materia"] == "Elettromagnetismo")
    assert em_hour["start_time"] == "11:30"
    assert em_hour["end_time"] == "13:30"
    assert em_hour["docente"] == "Prof.ssa Bassi"
    assert em_hour["is_recorded"] is False
    assert em_hour["lesson"] is None




def test_template_validity_keeps_past_weeks(rt_db):
    """Togliere un'ora dalla settimana tipo "da questa settimana in poi" non tocca le settimane prima."""
    from rt.db.models import CalendarEntryState
    from rt.db.session import session_scope

    old = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(day_of_week=0, start_time="09:00", end_time="11:00",
                                            materia="Analisi", valid_from="2026-09-07"),
        db=rt_db,
    )
    new = calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(day_of_week=0, start_time="14:00", end_time="16:00",
                                            materia="Fisica", valid_from="2026-10-12"),
        db=rt_db,
    )
    calendar_service.set_entry_state(
        schemas.CalendarEntryStateSet(date="2026-09-28", entry_key=f"tpl_{old.id}",
                                      template_entry_id=old.id, note="portare il libro"),
        db=rt_db,
    )

    # Un'ora nuova non compare nelle settimane prima della sua validità
    september = calendar_service.get_week_view("2026-09-28", db=rt_db).days[0].events
    assert [e.materia for e in september] == ["Analisi"]

    calendar_service.delete_template_entry(old.id, from_date="2026-10-12", db=rt_db)

    october = calendar_service.get_week_view("2026-10-12", db=rt_db).days[0].events
    assert [e.materia for e in october] == ["Fisica"]
    september = calendar_service.get_week_view("2026-09-28", db=rt_db).days[0].events
    assert [(e.materia, e.note) for e in september] == [("Analisi", "portare il libro")]
    with session_scope(rt_db) as s:
        assert s.get(CalendarEntryState, 1) is not None

    # Un'ora che non era ancora mai valsa si cancella davvero
    calendar_service.delete_template_entry(new.id, from_date="2026-10-12", db=rt_db)
    assert [e.id for e in calendar_service.list_template_entries(db=rt_db)] == [old.id]


def test_to_recover_includes_previous_week(rt_db):
    calendar_service.create_template_entry(
        schemas.CalendarTemplateEntryCreate(day_of_week=4, start_time="09:00", end_time="11:00",
                                            materia="Chimica", valid_from="2026-01-05"),
        db=rt_db,
    )
    week = calendar_service.get_week_view("2026-03-09", db=rt_db)
    assert [item.date for item in week.summary.to_recover] == ["2026-03-06", "2026-03-13"]


def test_calendar_api_rejects_bad_input(client):
    assert client.get("/api/v1/calendar/week", params={"date": "2026-13-45"}).status_code in (400, 422)
    assert client.get("/api/v1/calendar/day", params={"date": "abc"}).status_code in (400, 422)
    bad_state = {"date": "xxxxxxxxxx", "entry_key": "tpl_1", "status": "seguita"}
    assert client.post("/api/v1/calendar/entry-state", json=bad_state).status_code == 422
    bad_status = {"date": "2026-10-12", "entry_key": "tpl_1", "status": "boh"}
    assert client.post("/api/v1/calendar/entry-state", json=bad_status).status_code == 422
    bad_time = {"day_of_week": 0, "start_time": "25:99", "end_time": "26:00", "materia": "X"}
    assert client.post("/api/v1/calendar/template", json=bad_time).status_code == 422
    missing = {"date": "2026-10-12", "entry_key": "tpl_1", "lesson_id": 999}
    assert client.post("/api/v1/calendar/link-lesson", json=missing).status_code == 404


@pytest.mark.parametrize('status', ['seguire', 'seguita', 'nonseguita', 'saltare'])
def test_unrecorded_status_can_link(rt_db, tmp_path, status):
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    tpl = calendar_service.create_template_entry(schemas.CalendarTemplateEntryCreate(
        valid_from='2026-10-01', day_of_week=0, start_time='09:00', end_time='10:00', materia='Prova'), db=rt_db)
    key = f'tpl_{tpl.id}'
    calendar_service.set_entry_state(schemas.CalendarEntryStateSet(date='2026-10-12', entry_key=key, status=status), db=rt_db)
    assert not calendar_service.get_day_view('2026-10-12', db=rt_db).events[0].is_recorded
    with session_scope(rt_db) as session:
        lid = LessonRepository(session).get_or_create(str(tmp_path / 'lesson')).id
    linked = calendar_service.link_lesson(schemas.CalendarLinkLessonRequest(date='2026-10-12', entry_key=key, lesson_id=lid), db=rt_db)
    assert linked.status == 'seguita'
    assert calendar_service.get_day_view('2026-10-12', db=rt_db).events[0].is_recorded


@pytest.mark.parametrize('whole_day', [False, True])
def test_cancelled_hour_rejects_import_and_link(client, rt_db, tmp_path, whole_day):
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    tpl = calendar_service.create_template_entry(schemas.CalendarTemplateEntryCreate(
        valid_from='2026-10-01', day_of_week=0, start_time='09:00', end_time='10:00', materia='Prova'), db=rt_db)
    key = f'tpl_{tpl.id}'
    calendar_service.set_entry_state(schemas.CalendarEntryStateSet(
        date='2026-10-12', entry_key=key, status='seguita' if whole_day else 'annullata'), db=rt_db)
    if whole_day:
        calendar_service.set_day_state(schemas.CalendarDayStateSet(date='2026-10-12', status='annullata'), db=rt_db)
    assert calendar_service.get_day_view('2026-10-12', db=rt_db).events[0].status == 'annullata'
    with session_scope(rt_db) as session:
        lid = LessonRepository(session).get_or_create(str(tmp_path / 'lesson')).id
    linked = client.post('/api/v1/calendar/link-lesson', json={'date': '2026-10-12', 'entry_key': key, 'lesson_id': lid})
    imported = client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Prova',
        'appunti': 'Appunti', 'calendar_entry_id': key, 'calendar_date': '2026-10-12'})
    for response in [linked, imported]:
        assert response.status_code == 422, response.text
        assert 'Ora annullata' in response.text


def _range_template(rt_db, valid_from="2026-09-07", valid_to=None):
    return calendar_service.create_template_entry(schemas.CalendarTemplateEntryCreate(
        day_of_week=0, start_time="09:00", end_time="11:00", materia="Intervallo",
        docente="Prof. Rossi", valid_from=valid_from, valid_to=valid_to,
    ), db=rt_db)


def _range_events(rt_db, date):
    return calendar_service.get_week_view(date, db=rt_db).days[0].events


def test_template_added_only_in_range(rt_db):
    entry = _range_template(rt_db, "2026-10-12", "2026-10-26")
    assert entry.valid_to == "2026-10-26"
    assert not _range_events(rt_db, "2026-10-05")
    assert [e.template_entry_id for e in _range_events(rt_db, "2026-10-12")] == [entry.id]
    assert _range_events(rt_db, "2026-10-19")
    assert not _range_events(rt_db, "2026-10-26")


@pytest.mark.parametrize("start", ["2026-09-07", "2026-10-12", "2026-10-19"])
@pytest.mark.parametrize("end", [None, "2026-11-09"])
def test_template_range_preserves_future_data(rt_db, tmp_path, start, end):
    from rt.db.models import CalendarEntryState, CalendarOverride
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope

    old = _range_template(rt_db, start, end)
    key = f"tpl_{old.id}"
    lesson_dir = tmp_path / "lezione"
    lesson_dir.mkdir()
    (lesson_dir / "info.yaml").write_text("titolo: 'Lezione collegata'\nmateria: 'Altro'\n", encoding="utf-8")
    with session_scope(rt_db) as session:
        lesson = LessonRepository(session).get_or_create(str(lesson_dir))
        lesson.titolo = "Lezione collegata"
        lesson_id = lesson.id
    calendar_service.set_entry_state(schemas.CalendarEntryStateSet(
        date="2026-10-26", entry_key=key, template_entry_id=old.id, note="Portare il libro",
    ), db=rt_db)
    calendar_service.link_lesson(schemas.CalendarLinkLessonRequest(
        date="2026-10-26", entry_key=key, template_entry_id=old.id, lesson_id=lesson_id,
    ), db=rt_db)
    # Anche i vecchi stati scritti senza la chiave esterna devono seguire la nuova chiave.
    calendar_service.set_entry_state(schemas.CalendarEntryStateSet(
        date="2026-11-02", entry_key=key, status="saltare", note="Nota senza riferimento",
    ), db=rt_db)
    override = calendar_service.create_override(schemas.CalendarOverrideCreate(
        date="2026-10-26", template_entry_id=old.id, action="modified",
        start_time="10:00", end_time="12:00", materia="Intervallo", docente="Prof. Verdi",
    ), db=rt_db)
    calendar_service.delete_template_entry(old.id, from_date="2026-10-12", to_date="2026-10-26", db=rt_db)
    entries = calendar_service.list_template_entries(db=rt_db)
    continuation = next(e for e in entries if e.id != old.id)
    assert (continuation.valid_from, continuation.valid_to) == ("2026-10-26", end)
    assert (continuation.start_time, continuation.end_time, continuation.docente) == ("09:00", "11:00", "Prof. Rossi")
    assert all(e.valid_to is None or e.valid_from < e.valid_to for e in entries)
    assert not _range_events(rt_db, "2026-10-12")
    assert not _range_events(rt_db, "2026-10-19")
    after = _range_events(rt_db, "2026-10-26")[0]
    assert after.key == f"tpl_{continuation.id}"
    assert after.note == "Portare il libro" and after.status == "seguita"
    assert after.lesson.id == lesson_id
    assert after.is_modified and after.docente == "Prof. Verdi" and after.start_time == "10:00"
    later = _range_events(rt_db, "2026-11-02")[0]
    assert later.status == "saltare" and later.note == "Nota senza riferimento"
    with session_scope(rt_db) as session:
        assert session.get(CalendarOverride, override.id).template_entry_id == continuation.id
        states = session.scalars(select(CalendarEntryState)).all()
        assert all(s.template_entry_id == continuation.id and s.entry_key == f"tpl_{continuation.id}" for s in states)
        assert next(s for s in states if s.date == "2026-10-26").manual_link
    if start < "2026-10-12":
        assert _range_events(rt_db, "2026-09-07")
        assert next(e for e in entries if e.id == old.id).valid_to == "2026-10-12"
    else:
        assert all(e.id != old.id for e in entries)
    if end:
        assert not _range_events(rt_db, end)


@pytest.mark.parametrize("cut_from,cut_to", [("2026-09-07", "2026-10-12"), ("2026-10-26", "2026-11-09")])
def test_template_disjoint_range_is_noop(rt_db, cut_from, cut_to):
    entry = _range_template(rt_db, "2026-10-12", "2026-10-26")
    calendar_service.delete_template_entry(entry.id, from_date=cut_from, to_date=cut_to, db=rt_db)
    assert calendar_service.list_template_entries(db=rt_db) == [entry]


@pytest.mark.parametrize("cut_from,cut_to", [("2026-10-12", "2026-10-26"), ("2026-10-05", "2026-11-02")])
def test_template_range_covering_whole_validity_leaves_nothing(rt_db, cut_from, cut_to):
    entry = _range_template(rt_db, "2026-10-12", "2026-10-26")
    calendar_service.delete_template_entry(entry.id, from_date=cut_from, to_date=cut_to, db=rt_db)
    assert not calendar_service.list_template_entries(db=rt_db)


@pytest.mark.parametrize("end", ["2026-10-12", "2026-10-05"])
def test_template_api_rejects_invalid_range(client, end):
    result = client.post("/api/v1/calendar/template", json={
        "day_of_week": 0, "start_time": "09:00", "end_time": "11:00", "materia": "Intervallo",
        "valid_from": "2026-10-12", "valid_to": end,
    })
    assert result.status_code in (400, 422)
    assert result.json()["error"]["code"] == "invalid_date_range"


def test_template_api_delete_requires_start_and_ordered_end(client):
    result = client.post("/api/v1/calendar/template", json={
        "day_of_week": 0, "start_time": "09:00", "end_time": "11:00", "materia": "Intervallo",
        "valid_from": "2026-10-12", "valid_to": "2026-11-09",
    })
    assert result.status_code == 201
    entry = result.json()
    assert entry["valid_to"] == "2026-11-09"
    for query in ["to=2026-10-26", "from=2026-10-26&to=2026-10-26", "from=2026-10-26&to=2026-10-19"]:
        response = client.delete(f"/api/v1/calendar/template/{entry['id']}?{query}")
        assert response.status_code in (400, 422)
    assert client.delete(f"/api/v1/calendar/template/{entry['id']}?from=2026-10-19&to=2026-10-26").status_code == 204


def test_template_range_failure_rolls_back_continuation_and_references(rt_db):
    from sqlalchemy import event
    from rt.db.models import CalendarTemplateEntry
    old = _range_template(rt_db, "2026-10-12")
    calendar_service.set_entry_state(schemas.CalendarEntryStateSet(
        date="2026-10-26", entry_key=f"tpl_{old.id}", template_entry_id=old.id, note="Da conservare",
    ), db=rt_db)
    def fail_delete(_mapper, _connection, _target):
        raise RuntimeError("Errore durante la modifica")
    event.listen(CalendarTemplateEntry, "before_delete", fail_delete)
    try:
        with pytest.raises(RuntimeError, match="Errore durante"):
            calendar_service.delete_template_entry(old.id, from_date="2026-10-12", to_date="2026-10-26", db=rt_db)
    finally:
        event.remove(CalendarTemplateEntry, "before_delete", fail_delete)
    assert calendar_service.list_template_entries(db=rt_db) == [old]
    after = _range_events(rt_db, "2026-10-26")[0]
    assert after.key == f"tpl_{old.id}" and after.note == "Da conservare"
