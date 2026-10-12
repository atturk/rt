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


def test_automatic_lesson_link(tmp_path, rt_db):
    """CA1b: Una lezione con stessa data, ora e materia si collega automaticamente all'ora e la segna Seguita."""
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
    assert ev.lesson.units_total == 3

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


