"""
tests/test_db_bootstrap.py
Fase D: il database è sempre attivo. Ogni comando rt lo crea e lo migra da solo (sotto lock),
importa le lezioni esistenti al primo avvio e, se il DB è illeggibile, si ferma con le
istruzioni per ripristinarlo.
"""
import os
import subprocess
import sys

import pytest

from rt.db.bootstrap import INITIAL_IMPORT_KEY, ensure_database, initial_import
from rt.db.engine import DatabaseUnavailable, current_revision, head_revision, reset_database_cache
from rt.db.repositories import LessonRepository, SettingRepository
from rt.db.session import session_scope
from tests.test_db_sync import lessons  # noqa: F401 - fixture condivisa

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "home" / ".rt" / "rt.db")
    monkeypatch.setenv("RT_DATABASE_URL", url)
    reset_database_cache()
    return url


def test_ensure_creates_and_migrates_missing_database(db_url, tmp_path):
    db = ensure_database(auto_import=False)
    assert os.path.isfile(tmp_path / "home" / ".rt" / "rt.db")
    assert current_revision(db.engine) == head_revision()
    assert ensure_database(auto_import=False) is db  # in cache: nessun lavoro al secondo giro


def test_ensure_returns_none_only_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("RT_DATABASE_URL", "off")
    reset_database_cache()
    assert ensure_database() is None


def test_first_run_imports_existing_lessons_once(db_url, lessons):
    root, dirs = lessons
    messages = []
    db = ensure_database(lessons_root=root, on_progress=messages.append)
    with session_scope(db) as s:
        assert len(LessonRepository(s).list_all()) == 3
        assert SettingRepository(s).get(INITIAL_IMPORT_KEY)["synced"] == 3
    assert "importo 3 lezioni" in messages[0]
    # secondo avvio: nessun nuovo import, nessun messaggio
    messages.clear()
    assert initial_import(db, lessons_root=root, on_progress=messages.append) is None
    assert messages == []


def test_import_waits_for_a_lessons_root(db_url, lessons, monkeypatch):
    root, _ = lessons
    monkeypatch.setattr("rt.db.bootstrap._configured_lessons_root", lambda: None)
    db = ensure_database()
    with session_scope(db) as s:
        assert SettingRepository(s).get(INITIAL_IMPORT_KEY) is None
    monkeypatch.setattr("rt.db.bootstrap._configured_lessons_root", lambda: root)
    assert initial_import(db)["synced"] == 3


def test_broken_database_raises_with_restore_instructions(tmp_path, monkeypatch):
    path = tmp_path / "rt.db"
    path.write_bytes(b"not a sqlite database at all" * 100)
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    with pytest.raises(DatabaseUnavailable) as exc:
        ensure_database()
    message = str(exc.value)
    assert str(path) in message and "backup" in message and ".rotto" in message


def test_cli_command_creates_database_and_imports(db_url, lessons, tmp_path, capsys, monkeypatch):
    from rt.cli import main
    root, dirs = lessons
    monkeypatch.setattr("rt.db.bootstrap._configured_lessons_root", lambda: root)
    main(["status", dirs[0]])
    assert os.path.isfile(tmp_path / "home" / ".rt" / "rt.db")
    assert "importo 3 lezioni" in capsys.readouterr().err


def test_cli_stops_on_broken_database(tmp_path, monkeypatch, capsys, lessons):
    from rt.cli import main
    _, dirs = lessons
    path = tmp_path / "rt.db"
    path.write_bytes(b"garbage" * 1000)
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    with pytest.raises(SystemExit) as exc:
        main(["status", dirs[0]])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Database di RT illeggibile" in err and "rilancia il comando" in err
    # la diagnosi del database resta disponibile anche con il DB rotto
    main(["db", "status"])


def test_concurrent_first_start_migrates_once(tmp_path):
    """Due processi rt avviati insieme sullo stesso DB nuovo: il lock evita migrazioni parallele."""
    url = "sqlite:///" + str(tmp_path / "rt.db")
    code = ("from rt.db.bootstrap import ensure_database; "
            "db = ensure_database(auto_import=False); "
            "from rt.db.engine import current_revision; print(current_revision(db.engine))")
    env = dict(os.environ, RT_DATABASE_URL=url)
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=PROJECT_ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [p.communicate(timeout=120) for p in procs]
    for p, (out, err) in zip(procs, outs):
        assert p.returncode == 0, err
        assert out.strip() == head_revision()


def test_wal_switch_retries_while_another_process_holds_the_lock():
    """SQLite può rifiutare journal_mode=WAL con 'database is locked' senza aspettare il
    busy_timeout (visto in CI con tre processi sullo stesso DB nuovo): si riprova."""
    import sqlite3
    from rt.db.engine import _enable_wal

    class Cursor:
        def __init__(self):
            self.calls = 0

        def execute(self, sql):
            self.calls += 1
            if self.calls < 3:
                raise sqlite3.OperationalError("database is locked")

    cur = Cursor()
    _enable_wal(cur)
    assert cur.calls == 3
