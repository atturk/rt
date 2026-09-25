"""
tests/test_db_schema.py
RT4-B1: migrazioni Alembic su SQLite in memoria e su file, coerenza modelli/migrazioni
(alembic check), pragma SQLite, risoluzione dell'URL e comando 'rt db'.
"""
import os
import sqlite3

import pytest
from alembic import command
from sqlalchemy import inspect, text

from rt.db import engine as db_engine
from rt.db.engine import (
    alembic_config, create_db_engine, current_revision, default_sqlite_path, get_database,
    head_revision, reset_database_cache, resolve_database_url, upgrade_database,
)
from rt.db.models import Base
from rt.db.repositories import LessonRepository, SettingRepository
from rt.db.session import session_scope

TABLES = {"lessons", "phase_runs", "issues", "review_decisions", "llm_calls", "settings", "state_documents",
          "jobs", "job_events", "workers"}


def test_migrations_apply_in_memory():
    url = "sqlite://"
    engine = create_db_engine(url)
    upgrade_database(url, engine)
    assert TABLES <= set(inspect(engine).get_table_names())
    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_migrations_apply_on_file_and_are_idempotent(tmp_path):
    path = tmp_path / "sub" / "rt.db"
    url = f"sqlite:///{path}"
    upgrade_database(url)
    upgrade_database(url)
    assert path.is_file()
    con = sqlite3.connect(path)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    assert TABLES <= tables


def test_models_match_migrations(tmp_path):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    engine = create_db_engine(url)
    upgrade_database(url, engine)
    command.check(alembic_config(url, engine))  # solleva se i modelli divergono dalle migrazioni
    engine.dispose()


def test_downgrade_to_base_and_back(tmp_path):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    engine = create_db_engine(url)
    upgrade_database(url, engine)
    command.downgrade(alembic_config(url, engine), "base")
    assert not (TABLES & set(inspect(engine).get_table_names()))
    upgrade_database(url, engine)
    assert TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_sqlite_pragmas(rt_db):
    with rt_db.engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() >= 5000


def test_repositories_roundtrip(rt_db, tmp_path):
    lesson_dir = tmp_path / "lezione"
    lesson_dir.mkdir()
    with session_scope(rt_db) as s:
        lesson = LessonRepository(s).get_or_create(str(lesson_dir))
        assert LessonRepository(s).get_or_create(str(lesson_dir)).id == lesson.id
        SettingRepository(s).set("ui.theme", {"name": "dark"})
    with session_scope(rt_db) as s:
        assert LessonRepository(s).get_by_path(str(lesson_dir)).folder_name == "lezione"
        assert SettingRepository(s).get("ui.theme") == {"name": "dark"}
        assert SettingRepository(s).get("missing", 3) == 3


def test_url_resolution(monkeypatch, tmp_path):
    from rt.core.config import RTConfig
    cfg = RTConfig()
    monkeypatch.delenv("RT_DATABASE_URL", raising=False)
    cfg.telegram.lessons_root = str(tmp_path)
    assert resolve_database_url(cfg) == "sqlite:///" + str(tmp_path / ".rt" / "rt.db")
    cfg.database_url = "postgresql://u@h/rt"
    assert resolve_database_url(cfg) == "postgresql://u@h/rt"
    cfg.database_url = "off"
    assert resolve_database_url(cfg) is None
    monkeypatch.setenv("RT_DATABASE_URL", "sqlite:///x.db")
    assert resolve_database_url(cfg) == "sqlite:///x.db"
    monkeypatch.setenv("RT_DATABASE_URL", "off")
    assert resolve_database_url(cfg) is None
    assert default_sqlite_path(None).endswith(os.path.join(".rt", "rt.db"))


def test_get_database_does_not_create_without_request(monkeypatch, tmp_path):
    path = tmp_path / "rt.db"
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    assert get_database() is None
    assert not path.exists()
    assert get_database(create=True) is not None
    reset_database_cache()
    assert get_database() is not None


def test_broken_database_falls_back_to_none(monkeypatch, tmp_path, caplog):
    path = tmp_path / "rt.db"
    path.write_bytes(b"not a sqlite database at all" * 100)
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    assert get_database() is None


def test_cli_db_upgrade_and_status(monkeypatch, tmp_path, capsys):
    from rt.cli import main
    path = tmp_path / "rt.db"
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    main(["db", "status"])
    assert "rt db upgrade" in capsys.readouterr().out
    main(["db", "upgrade"])
    assert path.is_file()
    main(["db", "status"])
    assert head_revision() in capsys.readouterr().out
