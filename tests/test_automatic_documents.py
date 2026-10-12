"""V5a: documenti reali, coda condivisa e cambi concorrenti durante il debounce."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from rt.pipeline.anchors import make_anchor
from rt.core.idempotency import PhaseStatus, check_phase_status, compute_source_fingerprint, record_phase_fingerprint
from rt.core.lesson_paths import lesson_path
from rt.core.models import DecisionLedger, ScienceIssue, ScienceSeverity, ScienceType
from rt.core.state import WorkflowState, compute_effective_workflow_state
from rt.pipeline.ledger import write_ledger_file
from rt.pipeline.review import _draft_hashes, save_science_issues
from rt.pipeline.rewrite import load_draft
from rt.services.document_edit_service import save_document_edit
from rt.services.documents_service import request_documents, run_documents
from rt.services.jobs import DbJobQueue
from rt.services.review_service import record_review_decision, undo_last_decision
from rt.services.worker import Worker
from tests.api_support import isolated_workspace
from tests.test_document_edit import _preview, _synthetic_lesson


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    path = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    draft = load_draft(path)
    issues = [ScienceIssue(id=f"sci_{i:06d}", type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH, unit_id=unit.unit_id, claim=unit.content,
        reason="Testo da correggere", suggested_fix=f"Correzione {unit.unit_id}.",
        anchor=make_anchor(unit.content, 0, len(unit.content)))
        for i, unit in enumerate(draft.units, 1)]
    save_science_issues(issues, path)
    write_ledger_file(DecisionLedger(schema_version="2.0"), path)
    record_phase_fingerprint(path, "review", compute_source_fingerprint(path, "review"), {},
        metadata={"completed_items": [unit.unit_id for unit in draft.units], "unit_hashes": _draft_hashes(path)})
    return path


def decide(lesson, i):
    return record_review_decision(lesson, f"sci_{i:06d}", "accepted", channel="web", validate=True)


def state(lesson):
    return json.loads(Path(lesson_path(lesson, "documents.json")).read_text())


def final(lesson, name="rielaborato.md"):
    return Path(lesson_path(lesson, name)).read_text()


def fast_clock(monkeypatch, lesson):
    clock = SimpleNamespace(now=state(lesson)["changed_at"])
    clock.time = lambda: clock.now
    def sleep(seconds):
        clock.now += seconds
    clock.sleep = sleep
    monkeypatch.setattr("rt.services.documents_service.time", clock)
    return clock


def test_three_decisions_share_job_and_real_debounce_writes_final_files(lesson, rt_db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Una decisione o il documento automatico non rifanno la verifica")
    monkeypatch.setattr("rt.llm.client.LLMClient.call_structured", forbidden)
    before = _draft_hashes(lesson)
    queue = DbJobQueue(rt_db)
    for i in (1, 2, 3):
        decide(lesson, i)
    assert len(queue.list(lesson_id=lesson, job_type="documents")) == 1
    assert state(lesson)["version"] == 3
    changed_at = state(lesson)["changed_at"]
    started = time.time()
    job = Worker(queue, job_types=["documents"]).run_once()
    assert time.time() >= changed_at + 3
    assert time.time() - started >= max(0, changed_at + 3 - started - 0.05)
    assert queue.get(job.id).state == "succeeded"
    for uid in ("1.1", "1.2", "2.1"):
        assert f"Correzione {uid}." in final(lesson)
    assert "`accepted`" in final(lesson, "Errori concettuali.md")
    assert check_phase_status(lesson, "build")[0] == PhaseStatus.VALID
    assert check_phase_status(lesson, "review")[0] == PhaseStatus.VALID
    assert _draft_hashes(lesson) == before
    assert compute_effective_workflow_state(lesson) == WorkflowState.COMPLETED


def test_undo_rewrites_files_and_reopens_workflow_without_new_review(lesson, rt_db, monkeypatch):
    for i in (1, 2, 3):
        decide(lesson, i)
    fast_clock(monkeypatch, lesson)
    queue = DbJobQueue(rt_db)
    Worker(queue, job_types=["documents"]).run_once()
    undo_last_decision(lesson, "sci_000001")
    Worker(queue, job_types=["documents"]).run_once()
    assert "Correzione 1.1." not in final(lesson)
    assert "Testo dell'unità 1.1." in final(lesson)
    assert check_phase_status(lesson, "build")[0] == PhaseStatus.VALID
    assert check_phase_status(lesson, "review")[0] == PhaseStatus.VALID
    assert compute_effective_workflow_state(lesson) == WorkflowState.HUMAN_REVIEW_REQUIRED


def test_saved_editor_changes_update_both_documents_while_lease_is_active(lesson, rt_db, api_client, monkeypatch):
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    from rt.services.document_edit_lease import acquire
    lease = acquire(lesson_id)
    changed = save_document_edit(lesson, _preview(lesson).replace("Testo dell'unità 1.1.", "Paragrafo salvato nell'editor."))
    assert changed["changed"]
    fast_clock(monkeypatch, lesson)
    queue = DbJobQueue(rt_db)
    job = Worker(queue, job_types=["documents"]).run_once()
    assert queue.get(job.id).state == "succeeded"
    assert "Paragrafo salvato nell'editor." in final(lesson)
    assert Path(lesson_path(lesson, "Errori concettuali.md")).is_file()
    assert check_phase_status(lesson, "build")[0] == PhaseStatus.VALID
    assert lease["token"]
    assert compute_effective_workflow_state(lesson) != WorkflowState.COMPLETED


def test_last_change_restarts_debounce_without_holding_lesson_lock(lesson, rt_db, monkeypatch):
    decide(lesson, 1)
    clock = fast_clock(monkeypatch, lesson)
    initial = clock.now
    changed_at = []
    def sleep(seconds):
        clock.now += seconds
        if not changed_at and clock.now >= initial + 2:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(decide, lesson, 2).result(timeout=2)
            changed_at.append(clock.now)
    clock.sleep = sleep
    run_documents(lesson)
    assert clock.now >= changed_at[0] + 3
    assert "Correzione 1.1." in final(lesson) and "Correzione 1.2." in final(lesson)
    assert state(lesson)["written_version"] == state(lesson)["version"] == 2
    assert len(DbJobQueue(rt_db).list(lesson_id=lesson, job_type="documents")) == 1


def test_change_between_render_and_job_finish_is_not_lost(lesson, rt_db, monkeypatch):
    decide(lesson, 1)
    fast_clock(monkeypatch, lesson)
    queue = DbJobQueue(rt_db)
    original = queue.finish
    changed = []
    def finish(*args, **kwargs):
        if not changed:
            changed.append(True)
            decide(lesson, 2)
        return original(*args, **kwargs)
    monkeypatch.setattr(queue, "finish", finish)
    worker = Worker(queue, job_types=["documents"])
    worker.run_once()
    pending = queue.list(lesson_id=lesson, job_type="documents", state=["queued"])
    assert len(pending) == 1
    worker.run_once()
    assert "Correzione 1.2." in final(lesson)
    assert state(lesson)["written_version"] == 2


def test_running_documents_allow_api_decisions_and_editor_saves(lesson, rt_db, api_client, monkeypatch):
    decide(lesson, 1)
    queue = DbJobQueue(rt_db)
    worker = Worker(queue, job_types=["documents"])
    worker.register()
    job = queue.claim(worker.worker_id, ["documents"])
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    decided = api_client.post(f"/api/v1/lessons/{lesson_id}/issues/sci_000002/decision", json={"decision": "accepted"})
    assert decided.status_code == 200, decided.text
    lease = api_client.post(f"/api/v1/lessons/{lesson_id}/document/lease", json={})
    assert lease.status_code == 200, lease.text
    markdown = _preview(lesson).replace("Testo dell'unità 2.1.", "Modifica mentre i documenti lavorano.")
    saved = api_client.put(f"/api/v1/lessons/{lesson_id}/document/draft", json={"markdown": markdown, "lease_token": lease.json()["token"]})
    assert saved.status_code == 200, saved.text
    assert len(queue.list(lesson_id=lesson, job_type="documents")) == 1
    fast_clock(monkeypatch, lesson)
    worker.execute(job)
    assert "Modifica mentre i documenti lavorano." in final(lesson)


def test_unchanged_editor_save_does_not_queue_documents(lesson, rt_db):
    assert not save_document_edit(lesson, _preview(lesson))["changed"]
    assert not DbJobQueue(rt_db).list(lesson_id=lesson, job_type="documents")


def test_placed_images_update_final_files_without_manual_build(lesson, rt_db, monkeypatch):
    from rt.pipeline.add_images import save_image_descriptions
    from rt.pipeline.image_placement import save_image_placement
    save_image_descriptions(lesson, {"image-1": {"filename": "assets/images/test.png", "alt_text": "Lipidi"}})
    assert save_image_placement(lesson, {"1": ["image-1"]}, False)
    fast_clock(monkeypatch, lesson)
    Worker(DbJobQueue(rt_db), job_types=["documents"]).run_once()
    assert "assets/images/test.png" in final(lesson)
    assert check_phase_status(lesson, "build")[0] == PhaseStatus.VALID


def test_explicit_build_completes_queued_documents_without_second_execution(lesson, rt_db):
    from rt.pipeline.build import run_build
    decide(lesson, 1)
    result = run_build(lesson)
    assert result['lesson_dir'] == lesson
    assert 'Correzione 1.1.' in final(lesson)
    assert state(lesson)['written_version'] == state(lesson)['version']
    queue = DbJobQueue(rt_db)
    assert Worker(queue, job_types=['documents']).run_once() is None
    jobs = queue.list(lesson_id=lesson, job_type='documents')
    assert len(jobs) == 1 and jobs[0].state == 'succeeded'
    assert jobs[0].result['reason'] == 'documents_already_written'


def test_explicit_build_after_automatic_preserves_historical_build_manifest(lesson, rt_db, monkeypatch):
    from rt.pipeline.build import run_build
    from rt.core.manifest import load_manifest
    decide(lesson, 1)
    fast_clock(monkeypatch, lesson)
    queue = DbJobQueue(rt_db)
    Worker(queue, job_types=["documents"]).run_once()
    assert load_manifest(lesson).phase_records["build"]["automatic_documents"]
    result = run_build(lesson)
    assert not result["skipped"]
    record = load_manifest(lesson).phase_records["build"]
    assert "automatic_documents" not in record
    assert set(record["artifact_fingerprints"]) == {"rielaborato.md"}
    assert "Correzione 1.1." in final(lesson)
    assert Worker(queue, job_types=["documents"]).run_once() is None


def test_restore_during_running_documents_restarts_debounce_and_writes_restored_text(lesson, rt_db, monkeypatch):
    from rt.services.document_restore_service import restore_pipeline_version
    save_document_edit(lesson, _preview(lesson).replace("Testo dell'unità 1.1.", "Modifica da annullare."))
    clock = fast_clock(monkeypatch, lesson)
    started = clock.now
    restored_at = []
    def sleep(seconds):
        clock.now += seconds
        if not restored_at and clock.now >= started + 2:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(restore_pipeline_version, None, lesson).result(timeout=2)
            assert result["modified_units"] == 1
            restored_at.append(clock.now)
    clock.sleep = sleep
    queue = DbJobQueue(rt_db)
    job = Worker(queue, job_types=["documents"]).run_once()
    assert job.state == "succeeded"
    assert clock.now >= restored_at[0] + 3
    assert "Modifica da annullare." not in final(lesson)
    assert "Testo dell'unità 1.1." in final(lesson)
    assert state(lesson)["written_version"] == state(lesson)["version"]
    assert len(queue.list(lesson_id=lesson, job_type="documents")) == 1
