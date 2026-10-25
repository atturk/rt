"""
tests/test_parallel_jobs.py
RT4-FA1: "Job in parallelo". 'rt web' avvia il worker con worker.concurrency thread (default 2,
1-4, da Impostazioni > Generali). Due job su lezioni diverse girano davvero insieme, due job
sulla stessa lezione no (active_lesson UNIQUE); il database SQLite in WAL regge le scritture
concorrenti di due pipeline complete.
"""
import threading
import time

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import JobOutcome, Worker
from rt.services.jobs import JobState
from tests.api_support import isolated_workspace, make_lesson


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def _run_threads(workers, until, timeout=60.0):
    stop = threading.Event()
    threads = [threading.Thread(target=w.run, kwargs={"stop_event": stop}, daemon=True) for w in workers]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        time.sleep(0.05)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert until(), "i job non sono finiti in tempo"


def _slow_handler(spans):
    def handler(job, ctx):
        start = time.monotonic()
        time.sleep(0.6)
        spans[job.id] = (start, time.monotonic())
        return JobOutcome(state=JobState.SUCCEEDED)
    return handler


def _overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def test_jobs_on_different_lessons_run_together(ws, rt_db):
    first, second = make_lesson(ws, "lezione A"), make_lesson(ws, "lezione B")
    spans = {}
    queue = DbJobQueue(rt_db)
    ids = [queue.enqueue("lento", first), queue.enqueue("lento", second)]
    workers = [Worker(DbJobQueue(rt_db), worker_id=f"w{i}", handlers={"lento": _slow_handler(spans)}, poll_interval=0.05)
               for i in range(2)]
    _run_threads(workers, lambda: all(queue.get(i).state == "succeeded" for i in ids))
    # si sovrappongono: sui runner Windows il secondo job può partire anche mezzo secondo dopo
    assert _overlap(spans[ids[0]], spans[ids[1]]) > 0


def test_jobs_on_same_lesson_never_overlap(ws, rt_db):
    lesson = make_lesson(ws, "lezione A")
    spans = {}
    queue = DbJobQueue(rt_db)
    ids = [queue.enqueue("lento", lesson), queue.enqueue("lento", lesson)]
    workers = [Worker(DbJobQueue(rt_db), worker_id=f"w{i}", handlers={"lento": _slow_handler(spans)}, poll_interval=0.05)
               for i in range(2)]
    _run_threads(workers, lambda: all(queue.get(i).state == "succeeded" for i in ids))
    assert _overlap(spans[ids[0]], spans[ids[1]]) <= 0


def test_two_mock_pipelines_in_parallel_on_sqlite_wal(ws, rt_db):
    """Due pipeline complete (mock) su due lezioni con due worker in thread: stesso DB SQLite in
    WAL, eventi, lease e checkpoint scritti insieme senza 'database is locked'."""
    from sqlalchemy import text
    with rt_db.engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
    lessons = [make_lesson(ws, "lezione A"), make_lesson(ws, "lezione B")]
    queue = DbJobQueue(rt_db)
    options = {"mock": True, "auto_accept": True, "with_review": True, "rename": False}
    ids = [queue.enqueue("run_pipeline", d, {"inputs": [d], "options": options}) for d in lessons]
    workers = [Worker(DbJobQueue(rt_db), worker_id=f"w{i}", poll_interval=0.05, mock=True) for i in range(2)]
    _run_threads(workers, lambda: all(queue.get(i).state in ("succeeded", "failed") for i in ids), timeout=120)
    jobs = [queue.get(i) for i in ids]
    assert [j.state for j in jobs] == ["succeeded", "succeeded"], [j.error for j in jobs]
    assert {j.worker_id for j in jobs} == {"w0", "w1"}  # uno per worker: sono girati insieme
    for job_id in ids:
        types = [e.type for e in queue.events(job_id)]
        assert types[-1] == "job_finished" and "phase_completed" in types


def test_worker_concurrency_returns_8_and_loads_config(ws):
    from rt.api.launcher import worker_concurrency
    from rt.core.config import load_config
    from rt.services.settings_service import general_config_path
    from pathlib import Path
    import yaml
    cfg_file = general_config_path(Path(ws).parent)
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(yaml.safe_dump({"worker": {"concurrency": 2}}), encoding="utf-8")
    cfg = load_config(str(Path(ws).parent))
    assert cfg.worker is not None
    assert worker_concurrency() == 8


def test_rt_worker_concurrency_cli(monkeypatch):
    import argparse
    from rt.cli_jobs import cmd_worker
    called = []

    def fake_run_workers(queue_factory, concurrency, **kwargs):
        called.append(concurrency)

    monkeypatch.setattr("rt.services.worker.run_workers", fake_run_workers)
    monkeypatch.setattr("rt.cli_jobs._queue", lambda: None)
    monkeypatch.setattr("rt.cli_jobs.prepare_worker_process", lambda q: None)
    monkeypatch.setattr("rt.services.worker.registered_handlers", lambda: {"prepare": None})
    monkeypatch.setattr("rt.services.jobs.detect_stt_capability", lambda *a, **k: "mock")

    args = argparse.Namespace(concurrency=None, types="prepare", lease=None, poll=1.0, mock=True, stt="none", once=False)
    cmd_worker(args)
    assert called == [8]

    called.clear()
    args_1 = argparse.Namespace(concurrency=1, types="prepare", lease=None, poll=1.0, mock=True, stt="none", once=False)
    cmd_worker(args_1)
    assert called == [1]


def test_local_transcription_slot():
    from rt.core.stt_slot import local_transcription_slot
    from rt.services.context import CancelToken, RunCancelled

    events = []
    wait_messages = []

    def task1():
        with local_transcription_slot():
            events.append("t1_start")
            time.sleep(0.3)
            events.append("t1_end")

    def task2():
        time.sleep(0.05)
        with local_transcription_slot(on_wait=wait_messages.append):
            events.append("t2_start")
            events.append("t2_end")

    t1 = threading.Thread(target=task1)
    t2 = threading.Thread(target=task2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert events == ["t1_start", "t1_end", "t2_start", "t2_end"]
    assert len(wait_messages) == 1
    assert "In attesa" in wait_messages[0]

    cancel_token = CancelToken()
    cancelled_raised = []
    hold_event = threading.Event()

    def task_occupy():
        with local_transcription_slot():
            hold_event.wait(3.0)

    def task_cancel():
        time.sleep(0.05)
        try:
            with local_transcription_slot(cancel_token=cancel_token):
                pass
        except RunCancelled:
            cancelled_raised.append(True)
        finally:
            hold_event.set()

    to = threading.Thread(target=task_occupy)
    tc = threading.Thread(target=task_cancel)
    to.start()
    tc.start()
    time.sleep(0.15)
    cancel_token.cancel()
    to.join()
    tc.join()
    assert cancelled_raised == [True]


def test_launcher_passes_concurrency_to_worker(ws, monkeypatch):
    import rt.api.launcher as launcher
    started = {}

    class FakePopen:
        pid = 1

        def __init__(self, cmd):
            started["cmd"] = cmd

        def poll(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(launcher, "worker_concurrency", lambda: 8)
    monkeypatch.setattr(launcher, "_already_running", lambda *a: False)
    monkeypatch.setattr("uvicorn.Server.run", lambda *a, **k: None)
    monkeypatch.setattr("rt.api.server.prepare", lambda **k: True)
    monkeypatch.setattr(launcher, "_open_when_ready", lambda *a: None)
    assert launcher.run_spa(open_browser=False, worker_args=["--mock"], say=lambda m: None) == 0
    assert started["cmd"][-3:] == ["--mock", "--concurrency", "8"]
