"""
tests/test_jobs.py
RT4-D1: coda dei job su database e worker con lease.

- enqueue → worker → succeeded in mock;
- annullamento in coda e durante il rewrite;
- worker morto a metà rewrite: il lease scade, un altro worker riprende il job e le chiamate
  LLM (contatore del mock) sono le stesse di una run senza interruzioni;
- un solo job mutante per lezione (vincolo UNIQUE nel DB + lock della lezione);
- comandi 'rt worker' e 'rt jobs'.
"""
import os
import shutil
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from rt.core.process_lock import lesson_work_lock
from rt.db.models import Job, utcnow
from rt.db.session import session_scope
from rt.services.context import RunContext
from rt.services.events import PhaseProgress
from rt.services.job_handlers import RUN_PIPELINE, run_pipeline_job
from rt.services.jobs import DbJobQueue, JobState
from rt.services.worker import JobOutcome, Worker
from tests.golden_support import INFO_YAML, LESSON_NAME, TRANSCRIPT_MD

MOCK_OPTIONS = {"mock": True, "auto_accept": True, "with_review": True, "rename": False, "channel": "terminal"}


def make_lesson(root, name=LESSON_NAME):
    lesson_dir = os.path.join(str(root), name)
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML)
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD)
    return lesson_dir


@pytest.fixture
def queue(rt_db, tmp_path, monkeypatch):
    # config vuota nella cwd: niente lessons_root o route della macchina di sviluppo
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)
    return DbJobQueue(rt_db)


def three_unit_outline():
    """Outline mock con tre unità (il mock standard ne produce una): serve un rewrite che si
    possa interrompere a metà."""
    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    units = [OutlineUnit(id=f"1.{i}", title=f"Unità {i}", start_segment_id=f"seg_{2 * i - 1:06d}",
                         end_segment_id=f"seg_{2 * i:06d}", key_concepts=["Concetto"]) for i in (1, 2, 3)]
    return Outline(schema_version="1.0", lesson_title="Lezione Accademica Rielaborata",
                   macro_sections=[OutlineMacro(id="1", title="Lipidi", units=units)])


@pytest.fixture
def mock_calls(monkeypatch):
    """Contatore delle chiamate LLM del mock deterministico (con outline a tre unità)."""
    from rt.llm.client import LLMClient
    original = LLMClient._generate_mock_response
    calls = []

    def counting(self, job_name, prompt, response_model):
        calls.append(job_name)
        if response_model.__name__ == "Outline":
            return three_unit_outline()
        return original(self, job_name, prompt, response_model)

    monkeypatch.setattr(LLMClient, "_generate_mock_response", counting)
    return calls


def _payload(lesson_dir, **overrides):
    return {"inputs": [lesson_dir], "options": dict(MOCK_OPTIONS, **overrides)}


def _worker(queue, **kwargs):
    kwargs.setdefault("poll_interval", 0)
    kwargs.setdefault("on_message", lambda msg: None)
    return Worker(queue, **kwargs)


def test_enqueue_worker_succeeded_in_mock(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir), created_by="test")
    assert queue.get(job_id).state == "queued"

    job = _worker(queue).run_once()
    assert job.id == job_id
    assert job.state == "succeeded", job.error
    assert job.result["status"] == "completed"
    assert job.attempts == 1 and job.finished_at is not None
    assert os.path.isfile(os.path.join(lesson_dir, "[2026-09-05] BIOCHIMICA - Lezione Accademica Rielaborata.md"))
    types = [e.type for e in queue.events(job_id)]
    assert types[0] == "job_queued" and types[1] == "job_started" and types[-1] == "job_finished"
    assert {"phase_started", "phase_progress", "phase_completed"} <= set(types)
    assert queue.get(job_id).progress["phase"] == "build"
    # la coda è vuota
    assert _worker(queue).run_once() is None


def test_pipeline_waits_for_outline_decision(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir, auto_accept=False))
    job = _worker(queue).run_once()
    assert job.state == "waiting_for_decision"
    assert job.decision["kind"] == "outline_approval"
    assert job.finished_at is None
    with session_scope(queue.db) as s:
        assert s.get(Job, job_id).active_lesson is None  # la lezione è libera mentre si aspetta


def test_cancel_queued_job(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    assert queue.cancel(job_id).state == "cancelled"
    assert _worker(queue).run_once() is None


def test_cancel_during_rewrite(queue, tmp_path, monkeypatch, mock_calls):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    from rt.services import worker as worker_mod
    original_emit = worker_mod.JobEventReporter.emit

    def emit(self, event):
        original_emit(self, event)
        if isinstance(event, PhaseProgress) and event.phase == "rewrite":
            if event.current == 1:
                queue.cancel(job_id)  # come farebbero 'rt jobs cancel' o l'API

    monkeypatch.setattr(worker_mod.JobEventReporter, "emit", emit)
    job = _worker(queue).run_once()
    assert job.state == "cancelled"
    # richiesta durante l'unità 1: il worker la vede all'evento dell'unità 2 e si ferma prima
    # della 3 (l'unità in corso non si interrompe a metà: resta nel checkpoint)
    assert mock_calls.count("rewrite") == 2 and "review" not in mock_calls
    assert "build" not in {e.payload.get("phase") for e in queue.events(job_id)}
    with session_scope(queue.db) as s:
        assert s.get(Job, job_id).active_lesson is None


class _WorkerKilled(BaseException):
    """Simula la morte del processo worker (kill -9): nessuna pulizia, il job resta 'running'."""


def test_killed_worker_job_resumes_without_duplicate_llm_calls(queue, tmp_path, mock_calls):
    # run di riferimento senza interruzioni, su una copia identica della lezione
    reference = make_lesson(tmp_path / "riferimento")
    ref_id = queue.enqueue(RUN_PIPELINE, reference, _payload(reference))
    assert _worker(queue).run_once().state == "succeeded"
    expected_calls = len(mock_calls)
    rewrite_calls = mock_calls.count("rewrite")
    assert rewrite_calls == 3
    assert queue.get(ref_id).attempts == 1
    mock_calls.clear()

    # il primo worker prende il job e muore durante il rewrite (dopo la prima unità)
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    claimed = queue.claim("worker-morto", [RUN_PIPELINE], lease_seconds=30)
    assert claimed.id == job_id

    class DyingReporter:
        def emit(self, event):
            if isinstance(event, PhaseProgress) and event.phase == "rewrite" and event.current == 2:
                raise _WorkerKilled()

    with pytest.raises(_WorkerKilled):
        run_pipeline_job(claimed, RunContext(lesson_dir=lesson_dir, reporter=DyingReporter()))
    calls_before_crash = len(mock_calls)
    assert mock_calls.count("rewrite") == 1
    assert queue.get(job_id).state == "running"

    # finché il lease è valido nessuno lo tocca
    assert _worker(queue).run_once() is None
    # lease scaduto: il job torna in coda e un nuovo worker lo completa dai checkpoint
    assert queue.requeue_expired(now=utcnow() + timedelta(seconds=31)) == [job_id]
    job = _worker(queue).run_once()
    assert job.state == "succeeded", job.error
    assert job.attempts == 2
    assert len(mock_calls) == expected_calls, (calls_before_crash, mock_calls)
    assert mock_calls.count("rewrite") == rewrite_calls
    requeued = [e for e in queue.events(job_id) if e.type == "job_requeued"]
    assert requeued and requeued[0].payload["worker_id"] == "worker-morto"


def test_expired_job_fails_after_max_attempts(queue, tmp_path):
    job_id = queue.enqueue("noop", None, {}, max_attempts=2)
    future = utcnow() + timedelta(hours=1)
    for attempt in (1, 2):
        assert queue.claim(f"w{attempt}", ["noop"], lease_seconds=1).attempts == attempt
        queue.requeue_expired(now=future + timedelta(minutes=attempt))
    job = queue.get(job_id)
    assert job.state == "failed" and "interrotto 2 volte" in job.error


def test_one_running_job_per_lesson(queue, tmp_path):
    lesson_a = make_lesson(tmp_path / "a")
    lesson_b = make_lesson(tmp_path / "b")
    first = queue.enqueue("noop", lesson_a, {})
    second = queue.enqueue("noop", lesson_a, {})
    other = queue.enqueue("noop", lesson_b, {})
    assert queue.claim("w1", ["noop"]).id == first
    # il secondo job della stessa lezione aspetta; quello dell'altra lezione parte
    assert queue.claim("w2", ["noop"]).id == other
    assert queue.claim("w3", ["noop"]) is None
    assert queue.finish(first, "w1", JobState.SUCCEEDED)
    assert queue.claim("w3", ["noop"]).id == second


def test_database_rejects_two_running_jobs_on_same_lesson(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "a")
    ids = [queue.enqueue("noop", lesson_dir, {}) for _ in range(2)]
    with session_scope(queue.db) as s:
        s.get(Job, ids[0]).active_lesson = s.get(Job, ids[0]).lesson_path
    with pytest.raises(IntegrityError):
        with session_scope(queue.db) as s:
            s.get(Job, ids[1]).active_lesson = s.get(Job, ids[1]).lesson_path


def test_worker_releases_job_when_lesson_is_busy(queue, tmp_path):
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    with lesson_work_lock(lesson_dir):  # come un 'rt run' in processo sulla stessa lezione
        _worker(queue).run_once()
    job = queue.get(job_id)
    assert job.state == "queued" and job.attempts == 0
    assert any(e.type == "job_requeued" and e.payload["reason"] == "lesson_busy" for e in queue.events(job_id))
    assert _worker(queue).run_once().state == "succeeded"


def test_lost_lease_does_not_record_result(queue):
    job_id = queue.enqueue("slow", None, {})

    def handler(job, ctx):
        # un altro worker ha ripreso il job (lease scaduto) mentre questo lavorava
        queue.requeue_expired(now=utcnow() + timedelta(hours=1))
        queue.claim("altro", ["slow"])
        ctx.check_cancelled()
        return JobOutcome(state=JobState.SUCCEEDED, result={"x": 1})

    worker = _worker(queue, handlers={"slow": handler}, lease_seconds=60)
    worker.run_once()
    job = queue.get(job_id)
    assert job.state == "running" and job.worker_id == "altro" and job.result is None


def test_unknown_job_type_fails(queue):
    job_id = queue.enqueue("sconosciuto", None, {})
    worker = _worker(queue, handlers={"x": lambda j, c: None}, job_types=["sconosciuto"])
    assert worker.run_once().state == "failed"
    assert "sconosciuto" in queue.get(job_id).error


def test_handler_exception_marks_failed_with_sanitized_error(queue):
    def boom(job, ctx):
        raise ValueError("chiave sk-segretissima non valida")

    job_id = queue.enqueue("boom", None, {})
    _worker(queue, handlers={"boom": boom}).run_once()
    job = queue.get(job_id)
    assert job.state == "failed" and job.error.startswith("ValueError")


def test_live_workers_registry(queue):
    worker = _worker(queue, handlers={"noop": lambda j, c: JobOutcome(state=JobState.SUCCEEDED)})
    assert queue.live_workers() == []
    worker.register()
    assert [w["id"] for w in queue.live_workers("noop")] == [worker.worker_id]
    assert queue.live_workers("altro") == []
    queue.stop_worker(worker.worker_id)
    assert queue.live_workers() == []


def test_stream_events_until_finished(queue):
    job_id = queue.enqueue("noop", None, {})
    _worker(queue, handlers={"noop": lambda j, c: JobOutcome(state=JobState.SUCCEEDED)}).run_once()
    events = list(queue.stream_events(job_id, poll_interval=0.01, timeout=5))
    assert [e.type for e in events] == ["job_queued", "job_started", "job_finished"]
    assert list(queue.stream_events(job_id, after_id=events[-1].id, timeout=1)) == []


def test_cli_worker_once_and_jobs(queue, tmp_path, capsys):
    from rt.cli import main
    lesson_dir = make_lesson(tmp_path / "lezioni")
    job_id = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    main(["jobs"])
    out = capsys.readouterr().out
    assert job_id[:12] in out and "queued" in out and "Worker attivi: 0" in out
    main(["worker", "--once"])
    assert "succeeded" in capsys.readouterr().out
    main(["jobs", "show", job_id[:8]])
    assert "job_finished" in capsys.readouterr().out
    main(["worker", "--once"])
    assert "Nessun job in coda" in capsys.readouterr().out
    other = queue.enqueue(RUN_PIPELINE, lesson_dir, _payload(lesson_dir))
    main(["jobs", "cancel", other])
    assert queue.get(other).state == "cancelled"


def test_stopped_worker_puts_job_back_in_queue(queue):
    def interrupted(job, ctx):
        raise KeyboardInterrupt  # Ctrl+C o SIGTERM su 'rt worker'

    job_id = queue.enqueue("lungo", None, {})
    with pytest.raises(KeyboardInterrupt):
        _worker(queue, handlers={"lungo": interrupted}).run_once()
    job = queue.get(job_id)
    assert job.state == "queued" and job.attempts == 0 and job.worker_id is None
