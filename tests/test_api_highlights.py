"""Evidenziazioni dello Studio (4.2.2): per unità, nel database, cancellate con la lezione."""
import os

import pytest
from sqlalchemy import select

from rt.core.lesson_paths import lesson_path
from rt.db.models import StudyHighlight
from rt.db.session import read_scope
from rt.storage import fs
from tests.api_support import isolated_workspace

SOURCE = {"startMeta": {"parentTagName": "P", "parentIndex": 0, "textOffset": 0},
          "endMeta": {"parentTagName": "P", "parentIndex": 0, "textOffset": 5}, "text": "Il re", "id": "a1"}


@pytest.fixture
def lesson_id(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = fs.create_db_lesson(os.path.join(root, "[2026-09-05] BIOCHIMICA"))
    with fs.open(lesson_path(path, "info.yaml"), "w") as stream:
        stream.write("data: '2026-09-05'\nmateria: BIOCHIMICA\n")
    return api_client.get("/api/v1/lessons").json()[0]["id"]


def _add(api_client, lid, unit="1.1", color=0):
    response = api_client.post(f"/api/v1/lessons/{lid}/highlights", json={"unit_id": unit, "color": color, "source": SOURCE})
    assert response.status_code == 201, response.text
    return response.json()


def test_add_list_delete_and_clear_by_unit(api_client, lesson_id):
    first = _add(api_client, lesson_id, color=2)
    _add(api_client, lesson_id, color=4)
    other = _add(api_client, lesson_id, unit="1.2")
    listed = api_client.get(f"/api/v1/lessons/{lesson_id}/highlights", params={"unit": "1.1"}).json()
    assert [(h["color"], h["source"]["text"]) for h in listed] == [(2, "Il re"), (4, "Il re")]

    assert api_client.delete(f"/api/v1/lessons/{lesson_id}/highlights/{first['id']}").status_code == 204
    assert len(api_client.get(f"/api/v1/lessons/{lesson_id}/highlights", params={"unit": "1.1"}).json()) == 1
    assert api_client.delete(f"/api/v1/lessons/{lesson_id}/highlights/{first['id']}").status_code == 404

    assert api_client.delete(f"/api/v1/lessons/{lesson_id}/highlights", params={"unit": "1.1"}).status_code == 204
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/highlights", params={"unit": "1.1"}).json() == []
    assert [h["id"] for h in api_client.get(f"/api/v1/lessons/{lesson_id}/highlights", params={"unit": "1.2"}).json()] == [other["id"]]


def test_invalid_color_and_unknown_lesson(api_client, lesson_id):
    bad = api_client.post(f"/api/v1/lessons/{lesson_id}/highlights", json={"unit_id": "1.1", "color": 5, "source": SOURCE})
    assert bad.status_code == 422
    assert api_client.get("/api/v1/lessons/9999/highlights", params={"unit": "1.1"}).status_code == 404


def test_lesson_deletion_removes_highlights(api_client, lesson_id, rt_db):
    _add(api_client, lesson_id)
    assert api_client.delete(f"/api/v1/lessons/{lesson_id}").status_code == 204
    with read_scope(rt_db) as session:
        assert session.scalars(select(StudyHighlight)).all() == []
