import os
import time
from datetime import datetime, timedelta
from rt.telegram.registry import (
    register_pending,
    resolve_pending,
    prune_registry,
    _acquire_lock,
    _release_lock,
    _lock_path,
    _load_registry,
    _save_registry,
)


def test_registry_register_and_resolve(tmp_path):
    state_dir = str(tmp_path / ".rt_telegram")
    lesson_dir = str(tmp_path / "lesson_1")
    os.makedirs(lesson_dir, exist_ok=True)

    short_id = register_pending(
        lesson_dir=lesson_dir,
        round_=1,
        kind="outline_confirmation",
        state_dir=state_dir,
    )
    assert len(short_id) == 10
    
    entry = resolve_pending(short_id, state_dir=state_dir)
    assert entry is not None
    assert entry["lesson_dir"] == os.path.abspath(lesson_dir)
    assert entry["round"] == 1
    assert entry["kind"] == "outline_confirmation"
    assert entry.get("message_thread_id") is None
    assert "created_at" in entry

    # Risoluzione id inesistente
    assert resolve_pending("nonexistent", state_dir=state_dir) is None


def test_registry_register_with_message_thread_id(tmp_path):
    state_dir = str(tmp_path / ".rt_telegram")
    lesson_dir = str(tmp_path / "lesson_topics")
    os.makedirs(lesson_dir, exist_ok=True)

    short_id = register_pending(
        lesson_dir=lesson_dir,
        round_=1,
        kind="outline_confirmation",
        state_dir=state_dir,
        message_thread_id=5,
    )
    entry = resolve_pending(short_id, state_dir=state_dir)
    assert entry is not None
    assert entry["message_thread_id"] == 5



def test_registry_stale_lock_recovery(tmp_path):
    state_dir = str(tmp_path / ".rt_telegram")
    os.makedirs(state_dir, exist_ok=True)
    lock_file = _lock_path(state_dir)
    
    # Crea un file di lock stale con mtime vecchio di 40 secondi
    with open(lock_file, "w") as f:
        f.write("stale")
    old_time = time.time() - 40
    os.utime(lock_file, (old_time, old_time))

    # _acquire_lock deve recuperare e acquisire il lock senza sollevare eccezioni
    _acquire_lock(state_dir, retries=3, backoff=0.05)
    try:
        assert os.path.isfile(lock_file)
    finally:
        _release_lock(state_dir)
    assert not os.path.exists(lock_file)


def test_registry_prune(tmp_path):
    state_dir = str(tmp_path / ".rt_telegram")
    os.makedirs(state_dir, exist_ok=True)

    now = datetime.now()
    old_date = (now - timedelta(days=10)).isoformat()
    recent_date = (now - timedelta(days=2)).isoformat()

    data = {
        "schema_version": "1.0",
        "entries": {
            "old_entry": {
                "lesson_dir": "/tmp/old",
                "round": 1,
                "kind": "outline_confirmation",
                "created_at": old_date,
            },
            "recent_entry": {
                "lesson_dir": "/tmp/recent",
                "round": 1,
                "kind": "outline_confirmation",
                "created_at": recent_date,
            },
        },
    }
    _save_registry(state_dir, data)

    # Prune con max_age_days = 7
    prune_registry(state_dir, max_age_days=7)

    loaded = _load_registry(state_dir)
    assert "old_entry" not in loaded["entries"]
    assert "recent_entry" in loaded["entries"]
