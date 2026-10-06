"""Export multiplo in coda: contenuto condiviso col GET, avanzamento e cancellazione."""
import io
import json
import os
import tempfile
import zipfile
from types import SimpleNamespace

import pytest

from rt.services.api_jobs import EXPORT_LESSONS, export_lessons_job, job_export_path
from rt.services.context import CancelToken, RunCancelled, RunContext
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.mark.parametrize("fmt", ["markdown", "zip"])
@pytest.mark.parametrize("study", [False, True])
def test_export_job_progress_download_and_compatibility(api_client, workspace, rt_db, fmt, study):
    first = make_lesson(workspace)
    second = make_lesson(workspace, name="seconda lezione")
    for lesson in (first, second):
        run_mock_pipeline(lesson, with_review=False)
    ids = [l["id"] for l in api_client.get("/api/v1/lessons").json()]
    from rt.services.lesson_service import resolve_lesson_dir
    from rt.services.study_progress_service import current_unit_ids, set_status
    for lid in ids:
        path = resolve_lesson_dir(lid)
        set_status(lid, path, next(iter(current_unit_ids(path))), "appreso")
    response = api_client.post("/api/v1/lesson-exports", json={"ids": ids + ids, "format": fmt, "name": "Oggi: 04/10", "study": study})
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["type"] == EXPORT_LESSONS and accepted["lesson_id"] is None
    url = f"/api/v1/lesson-exports/{accepted['job_id']}/file"
    assert api_client.get(url).status_code == 404
    assert Worker(DbJobQueue(rt_db)).run_once() is not None
    job = api_client.get(f"/api/v1/jobs/{accepted['job_id']}").json()
    assert job["state"] == "succeeded", job
    assert job["payload"]["ids"] == ids
    assert job["result"]["included"] == 2
    assert job["progress"]["current"] == job["progress"]["total"] == 2
    events = api_client.get(f"/api/v1/jobs/{accepted['job_id']}/events/list").json()
    progress = [e["payload"] for e in events if e["type"] == "phase_progress"]
    assert [p["current"] for p in progress] == [0, 1, 2]
    assert "1 su 2" in progress[0]["message"] and "2 su 2" in progress[1]["message"]
    assert os.path.basename(first) in " ".join(p["message"] for p in progress)
    download = api_client.get(url)
    assert download.status_code == 200 and "Oggi%200410" in download.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert len(archive.namelist()) == 2
        assert all(n.endswith(".md" if fmt == "markdown" else ".zip") for n in archive.namelist())
        if fmt == "zip":
            with zipfile.ZipFile(io.BytesIO(archive.read(archive.namelist()[0]))) as inner:
                assert any(n.endswith("/rt-export.json") for n in inner.namelist())
                description = json.loads(inner.read(next(n for n in inner.namelist() if n.endswith("/rt-export.json"))))
                assert ("study" in description) is study
                if study:
                    assert description["study"][0]["status"] == "appreso"
    assert api_client.get(url).content == download.content  # il download non consuma lo ZIP
    legacy = api_client.get("/api/v1/lesson-exports", params={"ids": ids, "format": fmt, "study": study})
    assert _contents(legacy.content) == _contents(download.content)
    os.unlink(job_export_path(accepted["job_id"], job["result"]["file"]))
    assert api_client.get(url).status_code == 404



def _contents(data: bytes) -> dict:
    """Contenuto dello ZIP di gruppo, aprendo anche gli ZIP interni: i byte degli archivi
    interni cambiano con l'orario di creazione delle voci, il loro contenuto no."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        out = {}
        for name in archive.namelist():
            payload = archive.read(name)
            if name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(payload)) as inner:
                    payload = {n: inner.read(n) for n in inner.namelist()}
            out[name] = payload
        return out


def test_export_validation_failed_and_wrong_job(api_client, workspace, rt_db):
    make_lesson(workspace)
    [lesson] = api_client.get("/api/v1/lessons").json()
    assert api_client.post("/api/v1/lesson-exports", json={"ids": []}).status_code == 422
    assert api_client.post("/api/v1/lesson-exports", json={"ids": [lesson["id"]], "format": "pdf"}).status_code == 422
    assert api_client.post("/api/v1/lesson-exports", json={"ids": [999999]}).status_code == 404
    job_id = api_client.post("/api/v1/lesson-exports", json={"ids": [lesson["id"]]}).json()["job_id"]
    Worker(DbJobQueue(rt_db)).run_once()
    job = api_client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "failed" and job["error"] == "Nessuna lezione del gruppo ha un documento finale aggiornato."
    assert api_client.get(f"/api/v1/lesson-exports/{job_id}/file").status_code == 404
    wrong_id = DbJobQueue(rt_db).enqueue("import_lesson_zips", None, {"archives": []})
    Worker(DbJobQueue(rt_db)).run_once()
    assert api_client.get(f"/api/v1/lesson-exports/{wrong_id}/file").status_code == 404
    assert api_client.get("/api/v1/lesson-exports/assente/file").status_code == 404


def test_cancellation_between_lessons_cleans_temporary_exports(workspace, rt_db, monkeypatch, tmp_path):
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.storage import export
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = make_lesson(workspace)
    second = make_lesson(workspace, name="seconda lezione")
    token = CancelToken()
    original = export.export_zip_to_tempfile
    processed = []

    def cancel_after_first(lesson_dir, scope, study=False):
        processed.append(lesson_dir)
        path = original(lesson_dir, scope, study=study)
        token.cancel()
        return path

    monkeypatch.setattr(export, "export_zip_to_tempfile", cancel_after_first)
    job = SimpleNamespace(id="annullato", payload={"ids": [lesson_id_for_dir(first), lesson_id_for_dir(second)], "format": "zip"})
    with pytest.raises(RunCancelled):
        export_lessons_job(job, RunContext(cancel_token=token))
    assert processed == [first]
    assert not list(tmp_path.glob("rt-export-*.zip"))
    assert not list(tmp_path.glob("rt-export-many-*.zip"))
    assert not os.path.exists(os.path.dirname(job_export_path(job.id, "lezioni.zip")))
