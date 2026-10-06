"""Stato di studio: API, letture, scaletta attuale e riepilogo senza query per lezione."""
import pytest
from sqlalchemy import event, select

from rt.db.models import StudyUnit
from rt.db.session import read_scope
from rt.services import lesson_service, study_progress_service as service
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def ready(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = make_lesson(root)
    assert not run_mock_pipeline(path).error
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    units = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"]
    return path, lid, units


def test_default_status_change_and_read(api_client, ready):
    path, lid, units = ready
    first = units[0]
    assert first["status"] == "da-imparare"
    assert first["status_at"] is None and first["last_read_at"] is None
    base = f"/api/v1/lessons/{lid}/study/units/{first['id']}"
    assert api_client.post(base + "/read").status_code == 204
    reading = service.list_units(lid)[0]
    assert reading["status"] == "da-imparare" and reading["status_at"] is None
    assert reading["last_read_at"] is not None
    for status in ("in-apprendimento", "appreso", "da-imparare", "appreso"):
        response = api_client.put(base, json={"status": status})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status
        assert response.json()["status_at"] is not None
        assert service.list_units(lid)[0]["last_read_at"] == reading["last_read_at"]
    changed = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"][0]
    assert changed["status"] == "appreso"
    assert changed["status_at"] and changed["last_read_at"]
    summary = api_client.get("/api/v1/lessons").json()[0]
    assert summary["study_learned"] == 1 and summary["study_learning"] == 0
    assert summary["study_last_at"] == changed["status_at"]
    assert api_client.get(f"/api/v1/lessons/{lid}").json()["study_learned"] == 1


def test_removed_unit_is_ignored_without_deleting_its_progress(api_client, ready):
    from rt.pipeline.outline import load_outline, save_outline
    path, lid, units = ready
    uid = units[0]["id"]
    service.set_status(lid, path, uid, "appreso")
    service.mark_read(lid, path, uid)
    outline = load_outline(path)
    for macro in outline.macro_sections:
        for u in macro.units:
            if u.id == uid:
                u.id = "99.9"
    save_outline(outline, path)
    summary = service.summaries({lid: path})[lid]
    assert summary == {"study_learned": 0, "study_learning": 0, "study_last_at": None}
    assert service.list_units(lid)[0]["status"] == "appreso"
    assert api_client.get("/api/v1/lessons").json()[0]["study_learned"] == 0


def test_summaries_use_one_query_for_all_lessons(ready, rt_db):
    path, lid, units = ready
    service.set_status(lid, path, units[0]["id"], "in-apprendimento")
    lesson_service.list_lessons()  # scaletta e file in cache
    queries = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if "FROM study_units" in statement:
            queries.append(statement)
    event.listen(rt_db.engine, "before_cursor_execute", record)
    try:
        result = service.summaries({lid: path, 999: path})
    finally:
        event.remove(rt_db.engine, "before_cursor_execute", record)
    assert len(queries) == 1
    assert result[lid]["study_learning"] == 1 and result[999]["study_last_at"] is None


def test_invalid_status_unknown_lesson_and_unit(api_client, ready):
    path, lid, units = ready
    base = f"/api/v1/lessons/{lid}/study/units/"
    assert api_client.put(base + units[0]["id"], json={"status": "letto"}).status_code == 422
    assert api_client.put(base + "99.9", json={"status": "appreso"}).status_code == 404
    assert api_client.post(base + "99.9/read").status_code == 404
    assert api_client.post("/api/v1/lessons/9999/study/units/1.1/read").status_code == 404


def test_lesson_deletion_removes_progress(api_client, ready, rt_db):
    path, lid, units = ready
    service.set_status(lid, path, units[0]["id"], "appreso")
    assert api_client.delete(f"/api/v1/lessons/{lid}").status_code == 204
    with read_scope(rt_db) as session:
        assert session.scalars(select(StudyUnit)).all() == []
