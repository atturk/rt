import io
import json
import os
import zipfile

import pytest

from rt.storage.export import export_zip
from tests.api_support import isolated_workspace, make_lesson


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def _post(client, *archives):
    return client.post("/api/v1/lessons/import-zip", files=[("archives", (name, content, "application/zip"))
                                                         for name, content in archives])


def test_import_all_roundtrip_rejects_duplicate_and_continues(api_client, workspace):
    lesson = make_lesson(workspace)
    payload = export_zip(lesson, scope="all")
    os.rename(lesson, lesson + "-outside")
    response = _post(api_client, ("one.zip", payload), ("two.zip", payload))
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [item["status"] for item in results] == ["imported", "rejected"]
    assert results[1]["reason"].endswith("esiste già.")
    lesson_id = results[0]["lesson_id"]
    assert api_client.get(f"/api/v1/lessons/{lesson_id}").status_code == 200


def test_import_rejects_zip_slip_and_corrupt_content(api_client, workspace):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("lesson/../outside", b"bad")
        zipped.writestr("lesson/rt-export.json", json.dumps({"format": "rt-lesson", "version": 1, "scope": "all"}))
    response = _post(api_client, ("bad.zip", archive.getvalue()), ("corrupt.zip", b"not a zip"))
    assert response.status_code == 200
    assert [item["status"] for item in response.json()["results"]] == ["rejected", "rejected"]
    assert not os.path.exists(os.path.join(workspace, "outside"))
