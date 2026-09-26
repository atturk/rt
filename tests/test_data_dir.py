"""
RT4-G1: cartella dati unica (rt.core.paths), creazione e migrazione dalla disposizione 3.x
(rt.services.data_service), completamento di 'rt -u'.
"""
import json
import os
import sqlite3

import pytest

from rt.core import paths
from rt.db.engine import reset_database_cache, resolve_database_url
from rt.services import data_service


@pytest.fixture
def install(tmp_path, monkeypatch):
    """Una cartella d'installazione finta (il codice di RT) e una home finta per ~/.rt."""
    root = tmp_path / "install"
    (root / "config.example" / "rt").mkdir(parents=True)
    (root / "config.example" / "general.yaml").write_text("version: \"1\"\n", encoding="utf-8")
    (root / "config.example" / "rt" / "outline.yaml").write_text("x: 1\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("rt.core.paths.project_root", lambda: str(root))
    monkeypatch.setattr("rt.core.config._default_project_root", lambda: str(root))
    monkeypatch.setattr("rt.core.paths.DEFAULT_DATA_DIR", str(home / ".rt"))
    monkeypatch.delenv("RT_DATABASE_URL", raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    reset_database_cache()
    yield root, home
    reset_database_cache()


def _legacy_install(root, lessons_root):
    """Una 3.x: config/ e .env nella cartella d'installazione, DB e media in <lezioni>/.rt."""
    (root / "config").mkdir()
    (root / "config" / "general.yaml").write_text(
        f"telegram:\n  lessons_root: {lessons_root}\n", encoding="utf-8")
    (root / "config" / "secrets.enc").write_text("cifrato", encoding="utf-8")
    (root / ".env").write_text("RT_TELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    (root / ".rt_telegram").mkdir()
    (root / ".rt_telegram" / "state.json").write_text("{}", encoding="utf-8")
    db_dir = lessons_root / ".rt"
    (db_dir / "media").mkdir(parents=True)
    (db_dir / "media" / "L1_audio.m4a").write_bytes(b"audio")
    conn = sqlite3.connect(db_dir / "rt.db")
    conn.execute("create table t (x)")
    conn.execute("insert into t values (7)")
    conn.commit()
    conn.close()
    return db_dir


def test_precedence_without_data_dir_is_unchanged(install):
    root, _home = install
    assert paths.active_data_dir() is None
    assert paths.config_home() == str(root)
    assert paths.env_file() == str(root / ".env")


def test_explicit_data_dir_wins(install, tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("RT_DATA_DIR", str(data))
    (tmp_path / "cwd" / "config").mkdir()  # anche con config/ nella cwd
    assert paths.active_data_dir() == str(data)
    assert paths.config_dir() == str(data / "config")
    assert paths.env_file() == str(data / ".env")
    assert resolve_database_url() == "sqlite:///" + str(data / "rt.db")


def test_init_data_dir_is_idempotent(install):
    root, home = install
    target = data_service.init_data_dir()
    assert target == str(home / ".rt")
    assert paths.active_data_dir() == target
    assert (home / ".rt" / "config" / "rt" / "outline.yaml").is_file()
    (home / ".rt" / "config" / "general.yaml").write_text("version: \"2\"\n", encoding="utf-8")
    data_service.init_data_dir()
    assert (home / ".rt" / "config" / "general.yaml").read_text(encoding="utf-8") == "version: \"2\"\n"
    # la configurazione ora arriva dalla cartella dati
    assert paths.config_dir() == str(home / ".rt" / "config")
    assert resolve_database_url() == "sqlite:///" + str(home / ".rt" / "rt.db")


def test_migrate_keeps_db_and_media_where_they_are(install, tmp_path):
    root, home = install
    lessons = tmp_path / "lezioni"
    db_dir = _legacy_install(root, lessons)

    plan = data_service.plan_migration()
    assert plan.data_dir == str(db_dir) and plan.redirect_from == str(home / ".rt")
    assert {s.what for s in plan.steps} == {"configurazione (YAML e secrets.enc)", "file .env",
                                            "stato del bot Telegram"}

    data_service.migrate(check_services=False, say=lambda _m: None)
    assert paths.active_data_dir() == str(db_dir)
    assert json.loads((home / ".rt" / paths.DATA_MARKER).read_text())["location"] == str(db_dir)
    assert (db_dir / "config" / "secrets.enc").read_text() == "cifrato"
    assert (db_dir / ".env").read_text() == "RT_TELEGRAM_CHAT_ID=42\n"
    assert (db_dir / ".rt_telegram" / "state.json").is_file()
    # gli originali restano, rinominati: la config vecchia non vince più dalla cwd
    assert not (root / "config").exists() and any(p.name.startswith("config.migrato-") for p in root.iterdir())
    assert resolve_database_url() == "sqlite:///" + str(db_dir / "rt.db")
    assert (db_dir / "media" / "L1_audio.m4a").read_bytes() == b"audio"
    # rifarla non fa nulla
    assert data_service.migrate(check_services=False).already_active


def test_migrate_into_explicit_data_dir_copies_db_and_moves_media(install, tmp_path, monkeypatch):
    root, _home = install
    lessons = tmp_path / "lezioni"
    db_dir = _legacy_install(root, lessons)
    data = tmp_path / "data"
    monkeypatch.setenv("RT_DATA_DIR", str(data))

    plan = data_service.migrate(check_services=False, say=lambda _m: None)
    assert [s.action for s in plan.steps if s.what in ("database", "media delle lezioni (audio e immagini)")] \
        == ["sqlite-backup", "move"]
    conn = sqlite3.connect(data / "rt.db")
    assert conn.execute("select x from t").fetchone() == (7,)
    conn.close()
    assert (data / "media" / "L1_audio.m4a").read_bytes() == b"audio"
    assert not (db_dir / "media").exists()
    assert any(p.name.startswith("rt.db.migrato-") for p in db_dir.iterdir())
    assert paths.is_initialized(str(data))


def test_migrate_refuses_while_rt_is_running(install, tmp_path, monkeypatch):
    root, _home = install
    _legacy_install(root, tmp_path / "lezioni")
    monkeypatch.setattr(data_service, "running_services", lambda: ["bot Telegram"])
    with pytest.raises(data_service.DataDirError, match="bot Telegram"):
        data_service.migrate(say=lambda _m: None)
    assert (root / "config").is_dir() and paths.active_data_dir() is None


def test_migrate_rolls_back_on_failure(install, tmp_path, monkeypatch):
    root, _home = install
    data = tmp_path / "data"
    monkeypatch.setenv("RT_DATA_DIR", str(data))
    db_dir = _legacy_install(root, tmp_path / "lezioni")

    def broken(_src, _dst):
        raise OSError("disco pieno")
    monkeypatch.setattr(data_service, "sqlite_copy", broken)
    with pytest.raises(data_service.DataDirError, match="disco pieno"):
        data_service.migrate(check_services=False, say=lambda _m: None)
    assert not (data / "config").exists() and (root / "config").is_dir()
    assert (db_dir / "rt.db").is_file() and not paths.is_initialized(str(data))


def test_auto_migrate_creates_data_dir_for_new_installs(install):
    _root, home = install
    plan = data_service.auto_migrate(say=lambda _m: None)
    assert plan is not None and paths.active_data_dir() == str(home / ".rt")
    assert data_service.auto_migrate(say=lambda _m: None) is None


def test_post_update_migrates_and_creates_database(install, tmp_path, monkeypatch):
    root, home = install
    lessons = tmp_path / "lezioni"
    lessons.mkdir()
    (root / "config").mkdir()
    (root / "config" / "general.yaml").write_text(f"telegram:\n  lessons_root: {lessons}\n", encoding="utf-8")
    monkeypatch.setattr("rt.services.service_manager.supported", lambda: False)
    messages = []
    assert data_service.post_update(say=messages.append)
    assert paths.active_data_dir() == str(home / ".rt")
    assert (home / ".rt" / "rt.db").is_file()
    assert "🗄  Database aggiornato." in messages
