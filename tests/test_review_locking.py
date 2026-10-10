"""V2a: proprietario vivo, rinnovo e scritture concorrenti senza perdite."""
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from rt.core.config import RTConfig
from rt.core.filelock import file_lock, acquire_file_lock
from rt.core.models import DecisionLedger
from rt.pipeline.ledger import load_ledger, record_decision, write_ledger_file, revert_last_decision
from rt.pipeline.review_units import record_review_unit, load_review_units
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from tests.test_review_anchor_application import unit


def test_live_lock_is_not_stolen_after_thirty_seconds(tmp_path):
    path = str(tmp_path / 'review.lock')
    with file_lock(path):
        assert json.loads(open(path).read()) == {'pid': os.getpid(), 'host': socket.gethostname()}
        first = os.stat(path).st_mtime_ns
        # Attesa reale: verifica anche i rinnovi del context manager.
        threading.Event().wait(31)
        assert os.stat(path).st_mtime_ns > first
        with pytest.raises(TimeoutError):
            acquire_file_lock(path, retries=1, backoff=0)
        # Anche senza heartbeat, un proprietario vivo non è scaduto.
        os.utime(path, (time.time() - 60, time.time() - 60))
        with pytest.raises(TimeoutError):
            acquire_file_lock(path, retries=1, backoff=0)
    assert not os.path.exists(path)


def test_dead_owner_is_recovered(tmp_path):
    path = tmp_path / 'review.lock'
    path.write_text(json.dumps({'pid': 2**30, 'host': socket.gethostname()}))
    os.utime(path, (time.time() - 60, time.time() - 60))
    with file_lock(str(path)):
        assert json.loads(path.read_text())['pid'] == os.getpid()


@pytest.mark.parametrize('database', [False, True])
def test_concurrent_units_and_decisions(tmp_path, monkeypatch, database, request):
    if database:
        request.getfixturevalue('rt_db')
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    barrier = threading.Barrier(2)
    class Client:
        force_mock = True
    def writer(worker):
        barrier.wait()
        for i in range(12):
            uid = f'{worker}.{i}'
            record_review_unit(lesson, unit(uid, 'Testo'), RTConfig(), Client(), 0, 'clean')
            record_decision(lesson, uid, 'rejected')
        assert revert_last_decision(lesson, f'{worker}.0')
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(writer, [1, 2]))
    assert len(load_review_units(lesson)) == 24
    assert {d.issue_id for d in load_ledger(lesson).decisions} == {f'{w}.{i}' for w in [1, 2] for i in range(1, 12)}


def test_manifest_syncs_only_touched_lesson(tmp_path, monkeypatch, rt_db):
    from rt.core.manifest import load_manifest, save_manifest
    from rt.db import sync
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    calls = []
    original = sync.sync_lesson
    def track(session, path):
        calls.append(path)
        return original(session, path)
    monkeypatch.setattr(sync, 'sync_lesson', track)
    monkeypatch.setattr(sync, 'sync_all', lambda *a: pytest.fail('Sincronizzazione globale'))
    save_manifest(load_manifest(lesson), lesson)
    assert calls == [lesson]
