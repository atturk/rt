"""Import di una lezione che l'utente ha già: due studenti alla stessa lezione (stessa data,
materia e ora) con fonti e argomenti diversi. L'import si ferma con un conflitto; con la
scelta "replace" la lezione viene sostituita per intero (file, scaletta, stato dello studio),
con "keep" si tengono entrambe."""
import io
import json
import os

import pytest
import yaml

from rt.services import study_progress_service as progress
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from rt.storage.export import export_zip
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline

DAY = "2026-09-05"


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="replace-worker")


def _set_info(lesson_dir, **fields):
    path = os.path.join(lesson_dir, "info.yaml")
    with open(path, encoding="utf-8") as f:
        info = yaml.safe_load(f)
    info.update(fields)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(info, f, allow_unicode=True)


def _lesson_id(api_client, folder):
    return next(item["id"] for item in api_client.get("/api/v1/lessons").json() if item["folder_name"] == folder)


def _archive_from_b(api_client, workspace, ora="09:00", argomenti="Membrane"):
    """La lezione di B, esportata e poi tolta da questo RT: resta solo il suo ZIP."""
    folder = f"[{DAY}] BIOCHIMICA - {argomenti}"
    lesson = make_lesson(workspace, name=folder)
    _set_info(lesson, argomenti=argomenti, ora=ora, cartella=folder)
    with open(os.path.join(lesson, "slide del professore.md"), "w", encoding="utf-8") as f:
        f.write("# Slide\n")
    payload = export_zip(lesson, scope="all")
    assert api_client.delete(f"/api/v1/lessons/{_lesson_id(api_client, folder)}").status_code == 204
    return payload


@pytest.fixture
def lesson_a(api_client, workspace):
    """La lezione di A: solo audio, scaletta fatta e un'unità già studiata."""
    path = make_lesson(workspace)
    _set_info(path, ora="9:00")
    assert not run_mock_pipeline(path).error
    lid = _lesson_id(api_client, os.path.basename(path))
    uid = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"][0]["id"]
    progress.set_status(lid, path, uid, "appreso")
    return path, lid


def _import(api_client, worker, payload, decisions=None):
    data = {"decisions": json.dumps(decisions)} if decisions is not None else None
    response = api_client.post("/api/v1/lessons/import-zip", data=data,
                               files=[("archives", ("lezione-di-b.zip", payload, "application/zip"))])
    assert response.status_code == 202, response.text
    while worker.run_once() is not None:
        pass
    job = api_client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert job["state"] == "succeeded", job
    return job["result"]


def test_same_lesson_with_other_topics_is_a_conflict_not_a_silent_duplicate(api_client, workspace, worker, lesson_a):
    _path, lid = lesson_a
    result = _import(api_client, worker, _archive_from_b(api_client, workspace))
    item = result["results"][0]
    assert item["status"] == "conflict" and item["code"] == "lesson_already_present"
    assert item["existing"]["lesson_id"] == lid and item["existing"]["ora"] == "09:00"
    assert item["incoming"]["argomenti"] == "Membrane"
    assert item["can_keep_both"] is True
    assert "alle 09:00" in item["reason"]
    assert result["imported"] == 0 and result["conflicts"] == 1
    assert len(api_client.get("/api/v1/lessons").json()) == 1  # niente duplicato silenzioso


def test_replace_swaps_files_outline_and_study_state(api_client, workspace, worker, lesson_a):
    _path, lid = lesson_a
    payload = _archive_from_b(api_client, workspace)
    first = _import(api_client, worker, payload)["results"][0]
    result = _import(api_client, worker, payload, [{"file": "lezione-di-b.zip", "action": "replace",
                                                    "lesson_id": first["existing"]["lesson_id"]}])
    item = result["results"][0]
    assert item["status"] == "imported" and item["replaced_lesson_id"] == lid
    lessons = api_client.get("/api/v1/lessons").json()
    assert [entry["id"] for entry in lessons] == [item["lesson_id"]]
    assert lessons[0]["argomenti"] == "Membrane"
    files = api_client.get(f"/api/v1/lessons/{item['lesson_id']}/export",
                           params={"format": "zip", "scope": "all"}).content
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(files)).namelist()
    assert any(name.endswith("/slide del professore.md") for name in names)
    assert not any(name.endswith("outline.json") for name in names)  # la scaletta di A non resta
    assert progress.list_units(item["lesson_id"]) == []  # nemmeno il suo stato dello studio


def test_keep_both_imports_next_to_the_existing_lesson(api_client, workspace, worker, lesson_a):
    payload = _archive_from_b(api_client, workspace)
    result = _import(api_client, worker, payload, [{"file": "lezione-di-b.zip", "action": "keep"}])
    assert result["results"][0]["status"] == "imported"
    assert len(api_client.get("/api/v1/lessons").json()) == 2


def test_other_hour_is_another_lesson(api_client, workspace, worker, lesson_a):
    result = _import(api_client, worker, _archive_from_b(api_client, workspace, ora="11:00"))
    assert result["results"][0]["status"] == "imported"


def test_replace_of_a_different_lesson_asks_again(api_client, workspace, worker, lesson_a):
    _path, lid = lesson_a
    payload = _archive_from_b(api_client, workspace)
    result = _import(api_client, worker, payload, [{"file": "lezione-di-b.zip", "action": "replace", "lesson_id": lid + 99}])
    assert result["results"][0]["status"] == "conflict"
    assert api_client.get(f"/api/v1/lessons/{lid}").status_code == 200


def test_failed_replace_restores_the_original_lesson(api_client, workspace, worker, lesson_a, monkeypatch):
    path, lid = lesson_a
    studied = progress.list_units(lid)
    payload = _archive_from_b(api_client, workspace)
    real = progress.restore_units
    calls = []

    def fail_first(session, lesson_id, rows):
        calls.append(lesson_id)
        if len(calls) == 1:
            raise RuntimeError("disco pieno")
        return real(session, lesson_id, rows)

    monkeypatch.setattr(progress, "restore_units", fail_first)
    result = _import(api_client, worker, payload, [{"file": "lezione-di-b.zip", "action": "replace", "lesson_id": lid}])
    assert result["results"][0]["status"] == "rejected" and "disco pieno" in result["results"][0]["reason"]
    lessons = api_client.get("/api/v1/lessons").json()
    assert [entry["folder_name"] for entry in lessons] == [os.path.basename(path)]
    restored = lessons[0]["id"]
    assert [(row["unit_id"], row["status"]) for row in progress.list_units(restored)] == \
        [(row["unit_id"], row["status"]) for row in studied]  # stato dello studio di A rimesso


def test_invalid_decisions_are_rejected(api_client, workspace):
    response = api_client.post("/api/v1/lessons/import-zip", data={"decisions": json.dumps([{"file": "a.zip", "action": "replace"}])},
                               files=[("archives", ("a.zip", b"PK\x03\x04", "application/zip"))])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_decision"
