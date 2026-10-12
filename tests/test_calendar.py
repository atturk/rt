"""Test per il calendario (4.2.5 CA1a)."""
import pytest
from fastapi.testclient import TestClient

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
