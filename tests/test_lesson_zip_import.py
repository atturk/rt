"""Importazione di lezioni da archivi ZIP completi: la richiesta salva gli archivi e accoda il
job import_lesson_zips (controlli immediati: nome, dimensione, firma ZIP); estrazione e
verifica le fa il worker, qui in processo (Worker.run_once) come farebbe 'rt worker'."""
import io
import json
import os
import zipfile

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from rt.storage.export import export_zip
from tests.api_support import isolated_workspace, make_lesson


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="zip-worker")


def _post(client, *archives):
    return client.post("/api/v1/lessons/import-zip", files=[("archives", (name, content, "application/zip"))
                                                         for name, content in archives])


def _run(client, worker, response):
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["type"] == "import_lesson_zips" and accepted["lesson_id"] is None
    assert client.get(f"/api/v1/jobs/{accepted['job_id']}").json()["state"] == "queued"
    while worker.run_once() is not None:
        pass
    job = client.get(f"/api/v1/jobs/{accepted['job_id']}").json()
    assert job["state"] == "succeeded", job
    return job


def _uploads(root):
    folder = os.path.join(root, ".rt", "uploads")
    return os.listdir(folder) if os.path.isdir(folder) else []


def test_import_all_roundtrip_rejects_duplicate_and_continues(api_client, workspace, worker):
    lesson = make_lesson(workspace)
    payload = export_zip(lesson, scope="all")
    os.rename(lesson, lesson + "-outside")
    job = _run(api_client, worker, _post(api_client, ("one.zip", payload), ("two.zip", payload)))
    results = job["result"]["results"]
    assert [item["status"] for item in results] == ["imported", "rejected"]
    assert [item["file"] for item in results] == ["one.zip", "two.zip"]
    assert results[1]["reason"].endswith("esiste già.")
    assert job["result"]["imported"] == 1 and job["result"]["rejected"] == 1
    lesson_id = results[0]["lesson_id"]
    assert api_client.get(f"/api/v1/lessons/{lesson_id}").status_code == 200
    assert job["progress"]["phase"] == "import_lesson_zips" and job["progress"]["current"] == 2
    assert _uploads(workspace) == []  # upload temporaneo rimosso a job concluso


def test_same_name_archives_do_not_overwrite_each_other(api_client, workspace, worker):
    lesson = make_lesson(workspace)
    payload = export_zip(lesson, scope="all")
    os.rename(lesson, lesson + "-outside")
    job = _run(api_client, worker, _post(api_client, ("lezione.zip", payload), ("lezione.zip", b"PK\x03\x04broken")))
    assert [item["status"] for item in job["result"]["results"]] == ["imported", "rejected"]
    assert job["result"]["results"][1]["reason"] == "Archivio ZIP non valido."


def test_import_rejects_zip_slip_and_corrupt_content(api_client, workspace, worker):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("lesson/../outside", b"bad")
        zipped.writestr("lesson/rt-export.json", json.dumps({"format": "rt-lesson", "version": 1, "scope": "all"}))
    job = _run(api_client, worker, _post(api_client, ("bad.zip", archive.getvalue()), ("corrupt.zip", b"not a zip"),
                                         ("notes.txt", b"hello")))
    results = job["result"]["results"]
    assert [item["status"] for item in results] == ["rejected", "rejected", "rejected"]
    assert results[1]["reason"] == "Archivio ZIP non valido."  # firma ZIP controllata già alla richiesta
    assert results[2]["reason"] == "Serve un archivio ZIP."
    assert not os.path.exists(os.path.join(workspace, "outside"))


def test_cheap_validation_errors_come_back_immediately(api_client, workspace):
    response = _post(api_client, ("corrupt.zip", b"not a zip"), ("notes.txt", b"hello"), ("empty.zip", b""))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_archive"
    assert [item["reason"] for item in error["details"]["results"]] == [
        "Archivio ZIP non valido.", "Serve un archivio ZIP.", "File vuoto: empty.zip."]
    assert _uploads(workspace) == []  # nessun job: niente file lasciati


def test_too_many_archives_is_rejected_before_saving(api_client, workspace):
    response = _post(api_client, *[(f"a{i}.zip", b"PK\x03\x04") for i in range(21)])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_archives"
    assert _uploads(workspace) == []


def test_oversized_archive_is_rejected_without_stopping_the_others(api_client, workspace, worker, monkeypatch):
    lesson = make_lesson(workspace)
    payload = export_zip(lesson, scope="all")
    os.rename(lesson, lesson + "-outside")
    monkeypatch.setenv("RT_API_MAX_UPLOAD_MB", str((len(payload) + 1024) / (1024 * 1024)))
    job = _run(api_client, worker, _post(api_client, ("big.zip", b"PK\x03\x04" + b"0" * (len(payload) + 4096)),
                                         ("ok.zip", payload)))
    results = job["result"]["results"]
    assert [item["status"] for item in results] == ["rejected", "imported"]
    assert "troppo grandi" in results[0]["reason"]


def test_job_types_are_registered_for_rt_worker():
    from rt.services.worker import registered_handlers
    handlers = registered_handlers()
    assert getattr(handlers["import_lesson_zips"], "upload_cleanup", False)  # upload pulito a fine job
    assert "telegram_topic_export" in handlers
