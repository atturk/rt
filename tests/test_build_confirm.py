"""
tests/test_build_confirm.py
RT4-FA2: il build è la conferma finale dell'utente ("ciò che vedo in anteprima diventa
l'elaborato finale").

- Requisiti del build: prepare, outline e rewrite VALID. La review non è una dipendenza:
  STALE, PARTIAL, issue pendenti o orfane sono avvisi (phase_report, rt status).
- Il build resta STALE se cambiano segmenti, scaletta, bozza, decisioni o immagini dopo di
  lui, non se cambia la review.
- Recall, immagini e download funzionano dopo il rewrite, senza build.
- La migrazione cartella -> DB non cambia lo stato delle fasi.
"""
import io
import json
import os
import zipfile

import pytest

from rt.core.idempotency import (
    PROCESSOR_VERSIONS, PhaseStatus, UPSTREAM_DEPENDENCIES, _legacy_build_fingerprint,
    check_phase_status, mark_downstream_stale,
)
from rt.core.lesson_paths import lesson_path
from rt.core.manifest import load_manifest, save_manifest
from rt.pipeline.build import run_build
from rt.services.review_service import build_warnings, orphan_issue_ids
from rt.storage import fs
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline

PHASES = ("prepare", "outline", "rewrite", "review", "build")


def _statuses(lesson_dir):
    return {ph: check_phase_status(lesson_dir, ph)[0] for ph in PHASES}


def _reviewed_lesson(root):
    """Scaletta approvata, review fatta con le 10 issue del mock da decidere, nessun build."""
    from rt.services.outline_service import approve_outline
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)  # si ferma sull'outline
    approve_outline(lesson_dir, channel="api")
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)  # si ferma sulle issue
    return lesson_dir


def _make_review_stale_like_old_lessons(lesson_dir):
    """Come le lezioni revisionate prima di RT 3.3.2 (Task 81): impronta della review
    calcolata con review_v1.1."""
    manifest = load_manifest(lesson_dir)
    rec = manifest.phase_records["review"]
    rec["processor_version"] = "review_v1.1"
    rec["source_fingerprint"] = "0" * 64
    rec.pop("input_hashes", None)
    save_manifest(manifest, lesson_dir)


def _edit_draft(lesson_dir, transform):
    path = lesson_path(lesson_dir, "draft.json")
    with fs.open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for unit in data["units"]:
        unit["content"] = transform(unit["content"])
    with fs.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@pytest.fixture
def root(tmp_path, monkeypatch):
    return isolated_workspace(tmp_path, monkeypatch)


# ---------------------------------------------------------------- dipendenze

def test_build_depends_on_prepare_outline_rewrite_only():
    assert UPSTREAM_DEPENDENCIES["build"] == ["prepare", "outline", "rewrite"]


def test_stale_review_does_not_block_build(root):
    """La situazione di Patologia: review STALE; il build si fa e resta VALID."""
    lesson_dir = _reviewed_lesson(root)
    _make_review_stale_like_old_lessons(lesson_dir)
    status, reason = check_phase_status(lesson_dir, "review")
    assert status == PhaseStatus.STALE
    # il motivo dice la vera causa, non "draft.json o segments.json modificati"
    assert "versione precedente" in reason and "review_v1.1" in reason
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.MISSING

    run_build(lesson_dir)
    assert _statuses(lesson_dir) == {
        "prepare": PhaseStatus.VALID, "outline": PhaseStatus.VALID, "rewrite": PhaseStatus.VALID,
        "review": PhaseStatus.STALE, "build": PhaseStatus.VALID,
    }
    from rt.core.state import WorkflowState, compute_effective_workflow_state
    assert compute_effective_workflow_state(lesson_dir) == WorkflowState.COMPLETED


def test_rewrite_changes_after_build_make_it_stale(root):
    lesson_dir = _reviewed_lesson(root)
    run_build(lesson_dir)
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID

    _edit_draft(lesson_dir, lambda text: text + " Aggiunta.")
    status, reason = check_phase_status(lesson_dir, "build")
    assert status == PhaseStatus.STALE
    assert "bozza" in reason

    run_build(lesson_dir)
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_stale_rewrite_makes_build_stale(root):
    lesson_dir = _reviewed_lesson(root)
    run_build(lesson_dir)
    manifest = load_manifest(lesson_dir)
    manifest.phase_records["rewrite"]["source_fingerprint"] = "0" * 64
    save_manifest(manifest, lesson_dir)
    status, reason = check_phase_status(lesson_dir, "build")
    assert status == PhaseStatus.STALE
    assert "'rewrite'" in reason


def test_new_review_does_not_make_build_stale(root):
    lesson_dir = _reviewed_lesson(root)
    run_build(lesson_dir)
    path = lesson_path(lesson_dir, "science_issues.json")
    with fs.open(path, "r", encoding="utf-8") as f:
        issues = json.load(f)
    with fs.open(path, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=4)  # review rigenerata: file diverso
    assert mark_downstream_stale(lesson_dir, "review") == []
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_decisions_after_build_make_it_stale(root):
    """Una decisione cambia il testo dell'anteprima: il documento non è più aggiornato."""
    from rt.services.review_service import record_review_decision
    lesson_dir = _reviewed_lesson(root)
    run_build(lesson_dir)
    issue_id = json.load(fs.open(lesson_path(lesson_dir, "science_issues.json"), encoding="utf-8"))[0]["id"]
    record_review_decision(lesson_dir, issue_id, "rejected", channel="api")
    status, reason = check_phase_status(lesson_dir, "build")
    assert status == PhaseStatus.STALE and "decisioni" in reason


def test_build_record_of_previous_versions_is_still_valid(root):
    """Documenti creati prima di RT4-FA2 (impronta con science_issues.json): restano VALID
    finché non cambia nulla; con immagini posizionate dopo, diventano STALE."""
    from rt.pipeline.image_placement import save_image_placement
    lesson_dir = _reviewed_lesson(root)
    run_build(lesson_dir)
    manifest = load_manifest(lesson_dir)
    rec = manifest.phase_records["build"]
    rec["source_fingerprint"] = _legacy_build_fingerprint(lesson_dir)
    rec.pop("input_hashes", None)
    save_manifest(manifest, lesson_dir)
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID
    save_image_placement(lesson_dir, {"1": ["abc"]}, carousel=False)
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.STALE


# ---------------------------------------------------------------- avvisi

def test_warnings_list_pending_and_stale_review(root):
    lesson_dir = _reviewed_lesson(root)
    codes = {w["code"]: w for w in build_warnings(lesson_dir)}
    assert set(codes) == {"pending_issues"}
    assert codes["pending_issues"]["count"] == 10
    assert codes["pending_issues"]["message"].startswith("10 issue ancora da valutare")

    _make_review_stale_like_old_lessons(lesson_dir)
    codes = {w["code"]: w for w in build_warnings(lesson_dir)}
    assert set(codes) == {"review_stale", "pending_issues"}
    assert codes["review_stale"]["message"].startswith("Revisione non aggiornata")


def test_warnings_count_orphan_issues(root):
    """Issue che non trovano più il loro testo nella bozza: orfane, non pendenti."""
    lesson_dir = _reviewed_lesson(root)
    issues = json.load(fs.open(lesson_path(lesson_dir, "science_issues.json"), encoding="utf-8"))
    claims = [i["claim"] for i in issues if i["claim"]]
    _edit_draft(lesson_dir, lambda text: text.replace(claims[0], "testo riscritto a mano"))
    orphans = orphan_issue_ids(lesson_dir)
    assert len(orphans) == sum(1 for c in claims if c == claims[0])  # nel mock le issue condividono il claim
    codes = {w["code"]: w for w in build_warnings(lesson_dir)}
    assert codes["orphan_issues"]["count"] == len(orphans)
    assert codes["orphan_issues"]["message"].endswith("il loro testo non è più nella bozza.")
    assert codes.get("pending_issues", {}).get("count", 0) == 10 - len(orphans)
    assert "review_stale" in codes  # la bozza è cambiata dopo la review

    # una issue rifiutata non è orfana: il testo resta com'è
    from rt.services.review_service import record_review_decision
    record_review_decision(lesson_dir, orphans[0], "rejected", channel="api")
    assert orphans[0] not in orphan_issue_ids(lesson_dir)


def test_no_warnings_when_review_is_done(root):
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)
    assert build_warnings(lesson_dir) == []


def test_missing_review_is_a_warning_not_a_block(root):
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=False, auto_accept=True)
    assert [w["code"] for w in build_warnings(lesson_dir)] == ["review_missing"]
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_stale_reason_names_the_processor_version():
    from rt.core.idempotency import stale_reason
    reason = stale_reason("/non/esiste", "review", {"processor_version": "review_v1.1"}, "generico")
    assert PROCESSOR_VERSIONS["review"] in reason and "review_v1.1" in reason
    assert stale_reason("/non/esiste", "review", {"processor_version": PROCESSOR_VERSIONS["review"]}, "generico") == "generico"


def test_rt_status_shows_warnings(root, capsys):
    import argparse
    from rt.cli import cmd_status
    lesson_dir = _reviewed_lesson(root)
    _make_review_stale_like_old_lessons(lesson_dir)
    cmd_status(argparse.Namespace(lesson_dir=lesson_dir, issues=False, json=False))
    out = capsys.readouterr().out
    assert "Avvisi per il documento finale" in out
    assert "10 issue ancora da valutare" in out
    assert "Revisione non aggiornata" in out


# ---------------------------------------------------------------- API

@pytest.fixture
def api_lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = _reviewed_lesson(root)
    _make_review_stale_like_old_lessons(lesson_dir)
    return lesson_dir


def _lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


def test_api_phase_report_exposes_build_warnings(api_client, api_lesson):
    lesson_id = _lesson_id(api_client)
    phases = {p["phase"]: p for p in api_client.get(f"/api/v1/lessons/{lesson_id}/phases").json()["phases"]}
    assert phases["review"]["status"] == "STALE"
    assert phases["review"]["warnings"] == []
    codes = [w["code"] for w in phases["build"]["warnings"]]
    assert codes == ["review_stale", "pending_issues"]
    detail = api_client.get(f"/api/v1/lessons/{lesson_id}").json()
    assert [w["code"] for w in detail["phase_report"][-1]["warnings"]] == codes


def test_api_actions_available_after_rewrite_without_build(api_client, api_lesson):
    lesson_id = _lesson_id(api_client)
    actions = api_client.get(f"/api/v1/lessons/{lesson_id}").json()["actions"]
    assert actions["recall"] == {"available": True, "reason": None, "preview": False}
    assert actions["images"]["available"] is True
    assert actions["export_markdown"] == {"available": True, "reason": None, "preview": True}
    assert actions["export_zip"]["preview"] is True


def test_api_actions_explain_what_is_missing(api_client, tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    actions = api_client.get(f"/api/v1/lessons/{_lesson_id(api_client)}").json()["actions"]
    for name in ("recall", "images", "export_markdown", "export_zip"):
        assert actions[name]["available"] is False
        assert "rielaborazione" in actions[name]["reason"]


def test_api_export_without_build_is_the_preview(api_client, api_lesson):
    from rt.pipeline.build import render_lesson_documents
    lesson_id = _lesson_id(api_client)
    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export")
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "anteprima" in disposition
    assert res.text == render_lesson_documents(api_lesson)["rielaborato"]

    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export", params={"format": "zip"})
    assert res.status_code == 200
    assert "%28anteprima%29.zip" in res.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = [n.split("/", 1)[1] for n in zf.namelist()]
        readme = next(n for n in zf.namelist() if n.endswith("LEGGIMI - anteprima.txt"))
        assert "ANTEPRIMA" in zf.read(readme).decode("utf-8")
    assert any(n.endswith("(anteprima).md") for n in names)
    assert "Errori concettuali.md" in names

    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export", params={"format": "zip", "scope": "all"})
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = [n.split("/", 1)[1] for n in zf.namelist()]
    assert "LEGGIMI - anteprima.txt" in names and "draft.json" in names

    # dopo il build: documento finale, senza "anteprima"
    run_build(api_lesson)
    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export")
    assert "anteprima" not in res.headers["content-disposition"]
    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export", params={"format": "zip"})
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert not any("anteprima" in n for n in zf.namelist())
    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is True


def test_api_document_is_preview_until_build(api_client, api_lesson):
    lesson_id = _lesson_id(api_client)
    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is False and doc["sections"]


def test_api_images_job_works_without_build(api_client, api_lesson, rt_db, tmp_path):
    from PIL import Image
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    lesson_id = _lesson_id(api_client)
    png = tmp_path / "slide.png"
    Image.new("RGB", (24, 24), (30, 120, 200)).save(png, format="PNG")
    with open(png, "rb") as f:
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/images", files={"files": ("slide.png", f, "image/png")})
    assert res.status_code == 202, res.text
    worker = Worker(DbJobQueue(rt_db), worker_id="w", mock=True)
    while worker.run_once() is not None:
        pass
    job = api_client.get(f"/api/v1/jobs/{res.json()['job_id']}").json()
    assert job["state"] == "succeeded", job
    images = api_client.get(f"/api/v1/lessons/{lesson_id}/images").json()["images"]
    assert len(images) == 1 and images[0]["in_document"] is True  # nell'anteprima
    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is False and f"assets/images/{images[0]['name']}" in doc["markdown"]
    assert check_phase_status(api_lesson, "build")[0] == PhaseStatus.MISSING
    # il build successivo le include nel documento finale
    run_build(api_lesson)
    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is True and f"assets/images/{images[0]['name']}" in doc["markdown"]


# ---------------------------------------------------------------- migrazione cartella -> DB

@pytest.mark.parametrize("flat_layout", [False, True], ids=["_state", "layout-piatto"])
def test_migration_keeps_valid_phases_valid(root, rt_db, flat_layout):
    """La migrazione copia i file byte per byte: gli hash, e quindi lo stato delle fasi, non
    cambiano (anche per il vecchio layout con i file di stato alla radice)."""
    from rt.storage.migrate import migrate_storage
    from rt.db.engine import reset_database_cache
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)
    if flat_layout:
        state = os.path.join(lesson_dir, "_state")
        for name in os.listdir(state):
            os.replace(os.path.join(state, name), os.path.join(lesson_dir, name))
        os.rmdir(state)
    before = {ph: check_phase_status(lesson_dir, ph) for ph in PHASES}
    assert all(status == PhaseStatus.VALID for status, _ in before.values()), before
    report = migrate_storage(root)
    assert not report.errors and report.migrated == [lesson_dir]
    fs.reset_cache()
    reset_database_cache()
    assert fs.is_db_lesson(lesson_dir)
    assert not os.path.isdir(lesson_dir)
    after = {ph: check_phase_status(lesson_dir, ph) for ph in PHASES}
    assert after == before
