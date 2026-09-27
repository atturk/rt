import os

import pytest

from rt.core.lesson_paths import lesson_path
from rt.db.models import Lesson
from rt.db.session import session_scope
from rt.storage import fs
from tests.api_support import isolated_workspace, make_lesson
from tests.golden_support import AUDIO_FIXTURE


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def test_delete_db_lesson_removes_rows_and_media(api_client, workspace, rt_db):
    path = fs.create_db_lesson(os.path.join(workspace, "[2026-09-05] BIOCHIMICA"))
    with fs.open(lesson_path(path, "info.yaml"), "w") as stream:
        stream.write("data: '2026-09-05'\nmateria: BIOCHIMICA\n")
    fs.copy2(AUDIO_FIXTURE, os.path.join(path, "audio.wav"))
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    media = fs.real_path(os.path.join(path, "audio.wav"))
    assert media and os.path.isfile(media)
    response = api_client.delete(f"/api/v1/lessons/{lesson_id}")
    assert response.status_code == 204, response.text
    assert not os.path.exists(media)
    assert api_client.get(f"/api/v1/lessons/{lesson_id}").status_code == 404
    with session_scope(rt_db) as session:
        assert session.get(Lesson, lesson_id) is None


def test_delete_folder_lesson_and_reject_active_job(api_client, workspace, rt_db):
    path = make_lesson(workspace)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    response = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "prepare"})
    assert response.status_code == 202
    assert api_client.delete(f"/api/v1/lessons/{lesson_id}").status_code == 409
    assert os.path.isdir(path)
    assert api_client.post(f"/api/v1/jobs/{response.json()['job_id']}/cancel").status_code < 300
    assert api_client.delete(f"/api/v1/lessons/{lesson_id}").status_code == 204
    assert not os.path.exists(path)
