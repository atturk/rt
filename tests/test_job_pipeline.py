"""
tests/test_job_pipeline.py
RT4-D2: pipeline come job, pause per le decisioni e ripresa automatica.

- run completo in coda: pausa sull'outline, approvazione, ripresa, pausa sulle issue,
  decisioni, ripresa, build;
- job run_phase, ingest_audio (metadati mancanti → attesa → ripresa), recall_generate;
- ingest_audio fuori da macOS fallisce con un messaggio chiaro;
- 'rt run --queue' segue il job dagli eventi;
- senza worker, Telegram e i servizi eseguono in processo come prima.
"""
import os
import shutil
import threading

import pytest

from rt.services import outline_service
from rt.services.job_handlers import (
    INGEST_AUDIO, RECALL_GENERATE, RUN_PHASE, RUN_PIPELINE, pipeline_payload,
)
from rt.services.jobs import has_live_worker, run_job_or_inline
from rt.services.pipeline_service import PipelineOptions
from rt.services.review_service import is_review_complete, list_pending_issues, record_review_decision
from rt.services.worker import Worker
from tests.golden_support import AUDIO_FIXTURE, LESSON_NAME
from tests.test_jobs import MOCK_OPTIONS, _payload, _worker, make_lesson, queue  # noqa: F401


def test_queued_run_pauses_for_outline_and_issues_then_builds(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir, auto_accept=False))
    worker = _worker(queue)

    job = worker.run_once()
    assert job.state == "waiting_for_decision" and job.decision["kind"] == "outline_approval"
    assert worker.run_once() is None  # nulla da fare finché non si decide

    # l'approvazione (da CLI, Telegram o API) rimette il job in coda da sola
    outline_service.approve_outline(lesson_dir, actor="user", channel="api")
    assert queue.get(job_id).state == "queued"

    job = worker.run_once()
    assert job.state == "waiting_for_decision" and job.decision["kind"] == "science_issue"
    pending = list_pending_issues(lesson_dir, with_context=False)
    assert pending
    for i, item in enumerate(pending):
        record_review_decision(lesson_dir, item["issue"]["id"], "rejected", channel="api")
        # il job riparte solo con l'ultima decisione
        assert queue.get(job_id).state == ("queued" if i == len(pending) - 1 else "waiting_for_decision")
    assert is_review_complete(lesson_dir)

    job = worker.run_once()
    assert job.state == "succeeded", job.error
    assert job.result["status"] == "completed"
    assert os.path.isfile(os.path.join(lesson_dir, "[2026-09-05] BIOCHIMICA - Lezione Accademica Rielaborata.md"))
    types = [e.type for e in queue.events(job_id)]
    assert types.count("job_waiting") == 2 and types.count("job_resumed") == 2
    assert types.count("decision_required") == 2


def test_run_phase_jobs(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    for phase in ("prepare", "outline"):
        job_id = queue.enqueue(RUN_PHASE, lesson_dir, {"phase": phase, "options": {"mock": True}})
        job = _worker(queue).run_once()
        assert job.state == "succeeded", job.error
        assert phase in job.result["phase_results"]
    assert os.path.isfile(os.path.join(lesson_dir, "_state", "outline.json"))
    bad = queue.enqueue(RUN_PHASE, lesson_dir, {"phase": "boh", "options": {"mock": True}})
    _worker(queue).run_once()
    assert "Fase sconosciuta" in queue.get(bad).error


def test_ingest_audio_waits_for_metadata_then_resumes(queue, tmp_path):
    shutil.copy(AUDIO_FIXTURE, tmp_path / "demo_lecture.wav")
    out_dir = str(tmp_path / "out")
    opts = {"mock": True, "dest_dir": out_dir, "rename": False}
    job_id = queue.enqueue(INGEST_AUDIO, None, {"inputs": [str(tmp_path / "demo_lecture.wav")], "options": opts})
    job = _worker(queue).run_once()
    assert job.state == "waiting_for_decision" and job.decision["kind"] == "setup_metadata"
    queue.resume(job_id, {"options": {"date": "2026-09-05", "materia": "BIOCHIMICA", "argomenti": "Lipidi"}})
    job = _worker(queue).run_once()
    assert job.state == "succeeded", job.error
    assert job.lesson_path.endswith(LESSON_NAME)
    assert queue.get(job_id).payload["options"]["dest_dir"] == out_dir  # merge, non sostituzione


def test_ingest_audio_needs_macos(queue, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    shutil.copy(AUDIO_FIXTURE, tmp_path / "demo_lecture.wav")
    for job_type, payload in (
        (INGEST_AUDIO, {"inputs": [str(tmp_path / "demo_lecture.wav")], "options": {"mock": False}}),
        (RUN_PIPELINE, pipeline_payload(str(tmp_path / "demo_lecture.wav"), PipelineOptions())),
    ):
        job_id = queue.enqueue(job_type, None, payload)
        _worker(queue).run_once()
        job = queue.get(job_id)
        assert job.state == "failed" and "solo su macOS" in job.error


def test_recall_generate_job(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    assert _worker(queue).run_once().state == "succeeded"
    queue.enqueue(RECALL_GENERATE, lesson_dir, {"force_mock": True})
    job = _worker(queue).run_once()
    assert job.state == "succeeded", job.error
    assert job.result["questions"] > 0


@pytest.fixture
def background_worker(queue):
    stop = threading.Event()
    worker = Worker(queue, poll_interval=0.05, on_message=lambda m: None)
    worker.register()
    thread = threading.Thread(target=worker.run, kwargs={"stop_event": stop}, daemon=True)
    thread.start()
    yield worker
    stop.set()
    thread.join(timeout=10)


def test_run_job_or_inline_without_worker_runs_in_process(queue):
    assert not has_live_worker("recall_generate")
    assert run_job_or_inline("recall_generate", None, {}, inline=lambda: 42) == {"inline": 42}
    assert queue.list() == []


def test_run_job_or_inline_uses_live_worker(queue, tmp_path, background_worker):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    result = run_job_or_inline(RUN_PHASE, lesson_dir, {"phase": "prepare", "options": {"mock": True}},
                               inline=lambda: pytest.fail("doveva passare dal worker"), poll_interval=0.05)
    assert "prepare" in result["phase_results"]
    assert [j.type for j in queue.list()] == [RUN_PHASE]


def test_run_job_or_inline_falls_back_when_nobody_picks_up(queue):
    stale = Worker(queue, job_types=["recall_generate"], on_message=lambda m: None)
    stale.register()  # registrato ma mai in esecuzione (worker appena morto)
    result = run_job_or_inline("recall_generate", None, {}, inline=lambda: "fatto",
                               pickup_timeout=0.1, poll_interval=0.02)
    assert result == {"inline": "fatto"}
    assert queue.list()[0].state == "cancelled"


def test_cli_run_queue_follows_job(queue, tmp_path, background_worker, capsys):
    from rt.cli import main
    lesson_dir = make_lesson(tmp_path / "lezioni")
    main(["run", lesson_dir, "--mock", "--auto-accept", "--with-review", "--channel", "terminal",
          "--no-rename", "--queue"])
    out = capsys.readouterr().out
    assert "in coda" in out and "▶ rewrite" in out and "✔ build" in out and "✅ Job completato" in out
    assert queue.list()[0].state == "succeeded"


def test_cli_run_queue_without_worker_warns(queue, tmp_path, capsys, monkeypatch):
    from rt import cli_jobs
    lesson_dir = make_lesson(tmp_path / "lezioni")

    def cancel_and_stream(self, job_id, after_id=0, **kw):
        self.cancel(job_id)  # l'utente annulla da un altro terminale
        return iter(())

    monkeypatch.setattr("rt.services.jobs.DbJobQueue.stream_events", cancel_and_stream)
    with pytest.raises(SystemExit) as exc:
        cli_jobs.run_queued([lesson_dir], PipelineOptions(mock=True), decisions=None)
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "Nessun worker attivo" in out.out and "cancelled" in out.err


def test_telegram_voice_transcription_inline_without_worker(queue, monkeypatch):
    from rt.telegram import daemon
    monkeypatch.setattr("rt.core.recall_stt.transcribe_voice_answer", lambda path, engine: f"testo da {path}")
    assert daemon._transcribe_voice("/tmp/x.ogg", "macparakeet") == "testo da /tmp/x.ogg"
    assert queue.list() == []


def test_telegram_voice_transcription_via_worker(queue, background_worker, monkeypatch):
    from rt.telegram import daemon
    monkeypatch.setattr("rt.core.recall_stt.transcribe_voice_answer", lambda path, engine: "dal worker")
    assert daemon._transcribe_voice("/tmp/x.ogg", "macparakeet") == "dal worker"
    assert [j.type for j in queue.list()] == ["transcribe_voice"]
