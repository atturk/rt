"""
tests/test_phase_validation.py
Validazione manuale delle fasi (4.1.0b3): una fase STALE per una modifica voluta ai suoi file
torna VALID senza rieseguirla, via API (POST /lessons/{id}/phases/{fase}/validate) e servizio;
MISSING e INVALID non si forzano, le fasi a monte vanno validate prima, la lezione occupata
rifiuta. La parità con 'rt validate-phase' è in tests/test_api_parity.py.
"""
import json

import pytest

from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.core.lesson_paths import lesson_path
from rt.core.manifest import load_manifest
from rt.storage import fs
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    assert run_mock_pipeline(lesson_dir, auto_accept=True).status.value == "completed"
    return lesson_dir


def _lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


def _edit_json(lesson_dir, name, change):
    path = lesson_path(lesson_dir, name)
    with fs.open(path, encoding="utf-8") as f:
        data = json.load(f)
    change(data)
    with fs.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _retitle_first_unit(data):
    data["macro_sections"][0]["units"][0]["title"] += " (rivisto a mano)"


def _status(lesson_dir, phase):
    return check_phase_status(lesson_dir, phase)[0]


def _validate(client, lesson_id, phase):
    return client.post(f"/api/v1/lessons/{lesson_id}/phases/{phase}/validate")


def test_stale_phase_becomes_valid_and_downstream_follows_its_inputs(api_client, lesson):
    _edit_json(lesson, "outline.json", _retitle_first_unit)
    assert _status(lesson, "rewrite") == PhaseStatus.STALE
    assert _status(lesson, "build") == PhaseStatus.STALE
    lesson_id = _lesson_id(api_client)

    res = _validate(api_client, lesson_id, "rewrite")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"] is True and body["previous_status"] == "STALE" and body["status"] == "VALID"

    assert _status(lesson, "rewrite") == PhaseStatus.VALID
    assert _status(lesson, "review") == PhaseStatus.VALID  # stessa bozza: la review resta buona
    # Il documento finale è stato costruito con la scaletta di prima: resta da rifare.
    assert _status(lesson, "build") == PhaseStatus.STALE
    record = load_manifest(lesson).phase_records["rewrite"]
    assert record["manual_validation"]["channel"] == "api"
    assert record["manual_validation"]["previous_status"] == "STALE"
    assert set(record["unit_fingerprints"]) == set(record["completed_items"])

    phases = {p["phase"]: p for p in api_client.get(f"/api/v1/lessons/{lesson_id}/phases").json()["phases"]}
    assert phases["rewrite"]["manual_validation"]["previous_status"] == "STALE"
    assert phases["build"]["manual_validation"] is None

    res = _validate(api_client, lesson_id, "build")
    assert res.status_code == 200, res.text
    assert _status(lesson, "build") == PhaseStatus.VALID


def test_valid_phase_is_left_alone(api_client, lesson):
    before = load_manifest(lesson).phase_records["outline"]
    res = _validate(api_client, _lesson_id(api_client), "outline")
    assert res.status_code == 200 and res.json()["changed"] is False
    assert load_manifest(lesson).phase_records["outline"] == before


def test_missing_and_invalid_cannot_be_forced(api_client, lesson):
    lesson_id = _lesson_id(api_client)
    fs.remove(lesson_path(lesson, "science_issues.json"))
    res = _validate(api_client, lesson_id, "review")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "phase_not_validatable"
    assert res.json()["error"]["details"]["status"] == "MISSING"

    with fs.open(lesson_path(lesson, "draft.json"), "w", encoding="utf-8") as f:
        f.write("{ non è json")
    res = _validate(api_client, lesson_id, "rewrite")
    assert res.status_code == 409 and res.json()["error"]["details"]["status"] == "INVALID"
    assert "manual_validation" not in load_manifest(lesson).phase_records["rewrite"]


def test_upstream_must_be_valid_first(api_client, lesson):
    _edit_json(lesson, "outline.json", _retitle_first_unit)
    res = _validate(api_client, _lesson_id(api_client), "build")
    assert res.status_code == 409
    assert "rewrite" in res.json()["error"]["message"]
    assert _status(lesson, "build") == PhaseStatus.STALE


def test_incomplete_phase_is_refused_and_checkpoint_restored(api_client, lesson):
    from rt.core.manifest import save_manifest
    # Review fatta su una bozza poi modificata, e che non aveva rivisto tutte le unità:
    # validarla non la renderebbe completa.
    _edit_json(lesson, "draft.json", lambda data: data["units"][0].update(
        {"body_markdown": str(data["units"][0].get("body_markdown", "")) + "\n\nAggiunta a mano."}))
    manifest = load_manifest(lesson)
    manifest.phase_records["review"]["completed_items"] = manifest.phase_records["review"]["completed_items"][:-1]
    save_manifest(manifest, lesson)
    assert _status(lesson, "review") == PhaseStatus.STALE
    before = load_manifest(lesson).phase_records["review"]
    res = _validate(api_client, _lesson_id(api_client), "review")
    assert res.status_code == 409, res.text
    assert res.json()["error"]["details"]["status"] == "PARTIAL"
    assert load_manifest(lesson).phase_records["review"] == before


def test_refused_while_a_job_is_queued_or_the_document_is_edited(api_client, lesson, rt_db):
    from rt.services.jobs import DbJobQueue
    lesson_id = _lesson_id(api_client)
    _edit_json(lesson, "outline.json", _retitle_first_unit)
    queue = DbJobQueue(rt_db)
    job_id = queue.enqueue("run_phase", lesson, {"phase": "build", "options": {"mock": True}})
    res = _validate(api_client, lesson_id, "rewrite")
    assert res.status_code == 409 and res.json()["error"]["code"] == "lesson_busy"
    queue.cancel(job_id)

    lease = api_client.post(f"/api/v1/lessons/{lesson_id}/document/lease").json()
    res = _validate(api_client, lesson_id, "rewrite")
    assert res.status_code == 409 and res.json()["error"]["code"] == "document_edit_busy"
    api_client.delete(f"/api/v1/lessons/{lesson_id}/document/lease", params={"token": lease["token"]})
    assert _validate(api_client, lesson_id, "rewrite").status_code == 200


def test_a_real_run_replaces_the_manual_validation(api_client, lesson):
    from rt.pipeline.rewrite import run_rewrite
    _edit_json(lesson, "outline.json", _retitle_first_unit)
    assert _validate(api_client, _lesson_id(api_client), "rewrite").status_code == 200
    run_rewrite(lesson, force=True, force_mock=True)
    assert "manual_validation" not in load_manifest(lesson).phase_records["rewrite"]


def test_unknown_phase_is_rejected(api_client, lesson):
    assert _validate(api_client, _lesson_id(api_client), "setup").status_code == 422
