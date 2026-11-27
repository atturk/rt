"""
Test per la cartella dati di sistema (macOS Application Support, Windows %LOCALAPPDATA%\\RT)
e la migrazione sicura da ~/.rt in rt.services.data_service.post_update.

Ogni test usa esclusivamente HOME, LOCALAPPDATA e RT_DATA_DIR temporanee.
"""
from datetime import timedelta
import errno
import json
import os
import plistlib
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from rt import desktop
from rt.core import bundle, paths
from rt.db.engine import create_db_engine, open_database, reset_database_cache
from rt.db.models import (
    Job,
    Lesson,
    LessonFile,
    LlmDeferred,
    RecallSession,
    StateDocument,
    TelegramCommand,
    utcnow,
)
from rt.services import data_service, doctor_service, service_manager as sm


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Ambiente isolato con HOME, LOCALAPPDATA e installazione finti."""
    root = tmp_path / "app"
    (root / "config.example" / "rt").mkdir(parents=True)
    (root / "config.example" / "general.yaml").write_text('version: "1"\n', encoding="utf-8")
    (root / "config.example" / "rt" / "outline.yaml").write_text("x: 1\n", encoding="utf-8")
    (root / "VERSION").write_text("4.3.10b4\n", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    local_app_data = tmp_path / "localappdata"
    local_app_data.mkdir()
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # su Windows expanduser("~") usa USERPROFILE
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("RT_LAUNCH_AGENTS_DIR", str(agents))
    monkeypatch.delenv("RT_DATA_DIR", raising=False)
    monkeypatch.delenv("RT_DATABASE_URL", raising=False)
    monkeypatch.delenv("RT_SECRETS_FILE", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    from rt.security import secrets as sec
    sec._reset_for_tests()

    monkeypatch.setattr(paths, "project_root", lambda: str(root))
    monkeypatch.setattr("rt.core.config._default_project_root", lambda: str(root))
    monkeypatch.setattr(paths, "DEFAULT_DATA_DIR", str(home / ".rt"))
    monkeypatch.setattr(paths, "PLATFORM_DATA_DIR", None)
    monkeypatch.setattr(bundle, "_APPLIED_BROWSERS_PATH", None)
    monkeypatch.setattr(sm, "supported", lambda: False)

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    reset_database_cache()
    yield root, home, local_app_data, agents
    reset_database_cache()


def _fake_launchd(monkeypatch, loaded=None):
    loaded = loaded if loaded is not None else set()
    calls = []
    monkeypatch.setattr(sm, "supported", lambda: True)
    monkeypatch.setattr(sm.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(sm, "menubar_supported", lambda: True)

    def fake_run(cmd, capture_output=True, text=True, timeout=30):
        calls.append(cmd[1:])
        verb, rc, out = cmd[1], 0, ""
        if verb == "bootstrap":
            loaded.add(cmd[3].replace("\\", "/").rsplit("/", 1)[-1].replace(".plist", ""))
        elif verb == "bootout":
            label = cmd[2].rsplit("/", 1)[-1]
            rc = 0 if label in loaded else 3
            loaded.discard(label)
        elif verb == "print":
            label = cmd[2].rsplit("/", 1)[-1]
            if label in loaded:
                out = "gui/501/x = {\n\tstate = running\n\tpid = 4242\n\tlast exit code = 0\n}\n"
            else:
                rc = 113
        return subprocess.CompletedProcess(cmd, rc, out, "")

    monkeypatch.setattr(sm.subprocess, "run", fake_run)
    return calls, loaded


def _seed_legacy_app_data(home, *, include_folder_lesson=True):
    """Popola ~/.rt come un'installazione 4.3.10b3 con DB, lezioni, config, .env, components."""
    old_dir = home / ".rt"
    data_service.init_data_dir(str(old_dir), say=lambda _m: None)
    lessons_dir = old_dir / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    folder_lesson = lessons_dir / "[2026-10-01] FISIOLOGIA"
    if include_folder_lesson:
        folder_lesson.mkdir(parents=True)
        (folder_lesson / "info.yaml").write_text("materia: FISIOLOGIA\n", encoding="utf-8")

    db_lesson_path = str(lessons_dir / "[2026-10-02] ANATOMIA")
    external_lesson_path = str(home / "AltreLezioni" / "[2026-10-03] CHIMICA")
    sibling_path = str(home / ".rt-dev" / "non-toccare")

    (old_dir / "config" / "general.yaml").write_text(
        f'version: "1"\n'
        f"telegram:\n"
        f"  lessons_root: {lessons_dir}\n"
        f"  backup_hint: {sibling_path}\n",
        encoding="utf-8",
    )
    (old_dir / "config" / "rt" / "outline.yaml").write_text(
        f"x: 1\ncache_dir: {old_dir / 'cache'}\n",
        encoding="utf-8",
    )
    (old_dir / ".env").write_text(
        f"RT_TELEGRAM_CHAT_ID=42\n"
        f"RT_CUSTOM_DIR={old_dir / 'extra'}\n"
        f'RT_QUOTED="{old_dir / "quoted"}"\n'
        f"RT_SIBLING={sibling_path}\n",
        encoding="utf-8",
    )
    (old_dir / "models").mkdir(exist_ok=True)
    (old_dir / "models" / "components.json").write_text(
        json.dumps(
            {
                "transcription": {
                    "state": "downloading",
                    "auto_resume": True,
                    "pid": 99999,
                    "percent": 42,
                    "eta_seconds": 30.0,
                    "eta_label": "circa 30 s",
                },
                "browser": {
                    "state": "downloading",
                    "auto_resume": True,
                    "pid": 88888,
                    "detached_pid": 77777,
                    "percent": 15,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    db_url = "sqlite:///" + str(old_dir / "rt.db")
    db = open_database(db_url)
    try:
        with Session(db.engine) as session, session.begin():
            l_db = Lesson(
                path=db_lesson_path,
                folder_name="[2026-10-02] ANATOMIA",
                materia="ANATOMIA",
                storage="db",
            )
            l_ext = Lesson(
                path=external_lesson_path,
                folder_name="[2026-10-03] CHIMICA",
                materia="CHIMICA",
                storage="db",
            )
            session.add_all([l_db, l_ext])
            session.flush()
            session.add(
                LessonFile(
                    lesson_id=l_db.id,
                    name="info.yaml",
                    content=b"materia: ANATOMIA\n",
                    media_path=None,
                )
            )
            session.add(
                LessonFile(
                    lesson_id=l_db.id,
                    name="audio.m4a",
                    content=None,
                    media_path="1_audio.m4a",
                )
            )
            session.add(
                Job(
                    id="job-done-1",
                    type="run_pipeline",
                    state="succeeded",
                    lesson_path=db_lesson_path,
                    payload={},
                )
            )
            session.add(
                RecallSession(
                    lesson_path=db_lesson_path,
                    channel="web",
                    state="ended",
                    started_at="2026-10-02T10:00:00",
                )
            )
            session.add(
                TelegramCommand(
                    kind="start_recall",
                    lesson_path=db_lesson_path,
                    state="done",
                )
            )
            session.add(
                LlmDeferred(
                    key="k1",
                    lesson_path=db_lesson_path,
                    provider="deepseek",
                    model="deepseek-chat",
                )
            )
            session.add(
                StateDocument(
                    key=str(old_dir / ".rt_telegram" / "state.json"),
                    payload={"ok": True},
                )
            )
            if include_folder_lesson:
                session.add(
                    Lesson(
                        path=str(folder_lesson),
                        folder_name=folder_lesson.name,
                        materia="FISIOLOGIA",
                        storage="folder",
                    )
                )
    finally:
        db.engine.dispose()
    reset_database_cache()
    return old_dir, folder_lesson, db_lesson_path, external_lesson_path


def test_platform_data_dir_per_os(sandbox, monkeypatch):
    _root, home, local_app_data, _agents = sandbox

    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert paths.platform_data_dir() == str(home / "Library" / "Application Support" / "RT")

    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.platform_data_dir() == str(local_app_data / "RT")

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert paths.platform_data_dir() == str(home / "AppData" / "Local" / "RT")

    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths.platform_data_dir() == str(home / ".rt")


def test_fresh_app_install_uses_platform_dir_without_creating_dot_rt(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    expected = home / "Library" / "Application Support" / "RT"
    assert paths.default_data_dir() == str(expected)
    assert paths.data_dir() == str(expected)
    assert paths.active_data_dir() is None

    say = desktop._sayer()
    assert desktop.prepare("4.3.10b4", say)
    assert paths.active_data_dir() == str(expected)
    assert (expected / paths.DATA_MARKER).is_file()
    assert (expected / "rt.db").is_file()
    assert (expected / "app-version").read_text(encoding="utf-8").strip() == "4.3.10b4"
    assert (expected / "logs" / "desktop.log").is_file()
    assert not (home / ".rt").exists()


def test_terminal_install_keeps_dot_rt(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: None)

    assert paths.default_data_dir() == str(home / ".rt")
    target = data_service.init_data_dir(say=lambda _m: None)
    assert target == str(home / ".rt")
    assert not (home / "Library" / "Application Support" / "RT").exists()


def test_migration_moves_everything_rewrites_paths_services_env_and_log(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)
    _calls, loaded = _fake_launchd(monkeypatch)

    old_dir, folder_lesson, db_lesson_path, external_lesson_path = _seed_legacy_app_data(
        home, include_folder_lesson=False
    )
    # Aggiungiamo manualmente un record con storage="folder" senza info completo? No, qui è valida
    # e testiamo la conversione / riscrittura del DB: teniamo una lezione folder con path in ~/.rt/lessons
    # e disabilitiamo solo la conversione automatica? No, lasciamo che la migrazione riscriva i path
    # e poi _convert_folder_lessons trovi i file nel percorso nuovo!
    folder_lesson.mkdir(parents=True, exist_ok=True)
    (folder_lesson / "info.yaml").write_text("data: '2026-10-01'\nmateria: FISIOLOGIA\n", encoding="utf-8")
    (folder_lesson / "trascritto grezzo.md").write_text("testo", encoding="utf-8")
    db = open_database("sqlite:///" + str(old_dir / "rt.db"))
    try:
        with Session(db.engine) as session, session.begin():
            session.add(
                Lesson(
                    path=str(folder_lesson),
                    folder_name=folder_lesson.name,
                    materia="FISIOLOGIA",
                    storage="folder",
                )
            )
    finally:
        db.engine.dispose()
    reset_database_cache()

    # Servizi launchd installati prima della migrazione con i percorsi vecchi (~/.rt)
    sm.install(["api", "worker", "menubar"], data_dir=str(old_dir), say=lambda _m: None)
    assert "com.atturk.rt.api" in loaded
    assert plistlib.loads(open(sm.plist_path("api"), "rb").read())["EnvironmentVariables"]["RT_DATA_DIR"] == str(old_dir)

    # bundle.apply_env() chiamato prima della migrazione (come fa cli.main())
    bundle.apply_env()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(old_dir / "browsers")

    # desktop.log scritto prima della migrazione
    say = desktop._sayer()
    say("prima della migrazione")
    assert (old_dir / "logs" / "desktop.log").is_file()

    # Evitiamo che _convert_folder_lessons tocchi i file della folder lesson così verifichiamo
    # direttamente Lesson.path riscritto in DB (la conversione folder->db è testata altrove).
    monkeypatch.setattr(data_service, "_convert_folder_lessons", lambda _say: True)

    assert desktop.prepare("4.3.10b4", say)
    say("dopo la migrazione")

    new_dir = home / "Library" / "Application Support" / "RT"
    assert paths.default_data_dir() == str(new_dir)
    assert paths.active_data_dir() == str(new_dir)

    # 1. Backup creato in backups/prima-dello-spostamento-<data>.db
    backups = list((new_dir / "backups").glob("prima-dello-spostamento-*.db"))
    assert len(backups) == 1

    # 3. ~/.rt ricreata con SOLO rt-data.json e location -> new_dir
    assert [p.name for p in old_dir.iterdir()] == [paths.DATA_MARKER]
    marker = json.loads((old_dir / paths.DATA_MARKER).read_text(encoding="utf-8"))
    assert marker["layout"] == 1
    assert marker["location"] == str(new_dir)
    assert "moved_at" in marker

    # 4. DB riscritto in una transazione (path, lesson_path, state_documents; non tocca esterni)
    new_db = open_database("sqlite:///" + str(new_dir / "rt.db"))
    try:
        with Session(new_db.engine) as session:
            paths_by_materia = {l.materia: l.path for l in session.scalars(select(Lesson))}
            assert paths_by_materia["ANATOMIA"] == str(new_dir / "lessons" / "[2026-10-02] ANATOMIA")
            assert paths_by_materia["FISIOLOGIA"] == str(new_dir / "lessons" / "[2026-10-01] FISIOLOGIA")
            assert paths_by_materia["CHIMICA"] == external_lesson_path
            job = session.get(Job, "job-done-1")
            assert job.lesson_path == paths_by_materia["ANATOMIA"]
            rs = session.scalar(select(RecallSession))
            assert rs.lesson_path == paths_by_materia["ANATOMIA"]
            tc = session.scalar(select(TelegramCommand))
            assert tc.lesson_path == paths_by_materia["ANATOMIA"]
            ld = session.get(LlmDeferred, "k1")
            assert ld.lesson_path == paths_by_materia["ANATOMIA"]
            sd = session.get(StateDocument, str(new_dir / ".rt_telegram" / "state.json"))
            assert sd is not None and sd.payload == {"ok": True}
    finally:
        new_db.engine.dispose()

    # 4b. config/*.yaml e .env riscritti (senza toccare ~/.rt-dev)
    general_text = (new_dir / "config" / "general.yaml").read_text(encoding="utf-8")
    assert str(new_dir / "lessons") in general_text
    assert str(home / ".rt-dev" / "non-toccare") in general_text
    assert f"{old_dir}/" not in general_text
    outline_text = (new_dir / "config" / "rt" / "outline.yaml").read_text(encoding="utf-8")
    assert str(new_dir / "cache") in outline_text
    env_text = (new_dir / ".env").read_text(encoding="utf-8")
    assert f"RT_CUSTOM_DIR={new_dir / 'extra'}" in env_text
    assert f'RT_QUOTED="{new_dir / "quoted"}"' in env_text
    assert f"RT_SIBLING={home / '.rt-dev' / 'non-toccare'}" in env_text

    # 4c. components.json azzera stati "downloading"
    comp = json.loads((new_dir / "models" / "components.json").read_text(encoding="utf-8"))
    for cid in ("transcription", "browser"):
        assert comp[cid]["state"] == "not_downloaded"
        assert comp[cid]["auto_resume"] is False
        assert comp[cid]["pid"] is None

    # 5. launchd .plist riscritti sul percorso nuovo
    for svc in ("api", "worker", "menubar"):
        spec = plistlib.loads(open(sm.plist_path(svc), "rb").read())
        assert spec["EnvironmentVariables"]["RT_DATA_DIR"] == str(new_dir)
        assert spec["WorkingDirectory"] == str(new_dir)
        assert spec["StandardOutPath"] == str(new_dir / "logs" / f"{svc}.log")
        assert spec["StandardErrorPath"] == str(new_dir / "logs" / f"{svc}.log")

    # 3 (piano). bundle.apply_env nello stesso processo segue data_dir
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(new_dir / "browsers")

    # desktop.log scritto prima e continuato dopo nel percorso nuovo
    dlog = (new_dir / "logs" / "desktop.log").read_text(encoding="utf-8")
    assert "prima della migrazione" in dlog
    assert "dopo la migrazione" in dlog

    # doctor mostra il percorso nuovo
    chk = doctor_service.check_data_dir()
    assert chk.status == doctor_service.OK and chk.message == str(new_dir)


def test_migration_postponed_when_running_job_has_live_lease(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    old_dir, _folder, db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    db = open_database("sqlite:///" + str(old_dir / "rt.db"))
    try:
        with Session(db.engine) as session, session.begin():
            session.add(
                Job(
                    id="job-live",
                    type="run_pipeline",
                    state="running",
                    lesson_path=db_lesson_path,
                    lease_until=utcnow() + timedelta(minutes=5),
                    payload={},
                )
            )
    finally:
        db.engine.dispose()
    reset_database_cache()

    messages = []
    assert not data_service.post_update(say=messages.append)
    assert any("rimandato" in m for m in messages)
    assert (old_dir / "rt.db").is_file()
    assert not (home / "Library" / "Application Support" / "RT").exists()


def test_migration_proceeds_when_running_job_lease_is_expired(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    old_dir, _folder, db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    db = open_database("sqlite:///" + str(old_dir / "rt.db"))
    try:
        with Session(db.engine) as session, session.begin():
            session.add(
                Job(
                    id="job-stale",
                    type="run_pipeline",
                    state="running",
                    lesson_path=db_lesson_path,
                    active_lesson=db_lesson_path,
                    lease_until=utcnow() - timedelta(minutes=5),
                    payload={},
                )
            )
    finally:
        db.engine.dispose()
    reset_database_cache()

    assert data_service.post_update(say=lambda _m: None)
    new_db_path = home / "Library" / "Application Support" / "RT" / "rt.db"
    assert new_db_path.is_file()
    new_db = open_database("sqlite:///" + str(new_db_path))
    try:
        with Session(new_db.engine) as session:
            job = session.get(Job, "job-stale")
            expected_path = str(home / "Library" / "Application Support" / "RT" / "lessons" / "[2026-10-02] ANATOMIA")
            assert job.lesson_path == expected_path
            assert job.active_lesson == expected_path
    finally:
        new_db.engine.dispose()


def test_migration_aborts_cleanly_when_rename_fails(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    old_dir, _folder, _db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    marker_before = (old_dir / paths.DATA_MARKER).read_bytes()

    def broken_rename(src, dst):
        raise OSError(errno.EXDEV, "Cross-device link", src, dst)

    monkeypatch.setattr(data_service.os, "rename", broken_rename)
    messages = []
    assert not data_service.post_update(say=messages.append)
    assert any("rimandato" in m for m in messages)
    assert (old_dir / paths.DATA_MARKER).read_bytes() == marker_before
    assert (old_dir / "rt.db").is_file()
    assert not list((old_dir / "backups").glob("prima-dello-spostamento-*.db"))
    assert not (home / "Library" / "Application Support" / "RT").exists()


def test_migration_rolls_back_completely_on_post_rename_error(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    old_dir, _folder, db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    # Eseguiamo prima ensure/load_config così general.yaml è già alla forma corrente prima del test di rollback
    from rt.core.config import load_config
    load_config()
    marker_before = (old_dir / paths.DATA_MARKER).read_bytes()
    general_before = (old_dir / "config" / "general.yaml").read_bytes()
    env_before = (old_dir / ".env").read_bytes()
    comp_before = (old_dir / "models" / "components.json").read_bytes()

    bundle.apply_env()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(old_dir / "browsers")

    monkeypatch.setattr(
        data_service,
        "_rewrite_db_paths",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("errore simulato nel DB")),
    )

    messages = []
    assert not data_service.post_update(say=messages.append)
    assert any("ripristinato tutto" in m for m in messages)

    new_dir = home / "Library" / "Application Support" / "RT"
    assert not new_dir.exists()
    assert (old_dir / paths.DATA_MARKER).read_bytes() == marker_before
    assert (old_dir / "config" / "general.yaml").read_bytes() == general_before
    assert (old_dir / ".env").read_bytes() == env_before
    assert (old_dir / "models" / "components.json").read_bytes() == comp_before
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(old_dir / "browsers")
    assert not list((old_dir / "backups").glob("prima-dello-spostamento-*.db"))

    # DB intatto con i percorsi originali
    db = open_database("sqlite:///" + str(old_dir / "rt.db"))
    try:
        with Session(db.engine) as session:
            anat = session.scalar(select(Lesson).where(Lesson.materia == "ANATOMIA"))
            assert anat.path == db_lesson_path
    finally:
        db.engine.dispose()


def test_migration_rolls_back_when_service_install_fails(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)
    _fake_launchd(monkeypatch)

    old_dir, _folder, db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    sm.install(["api", "worker"], data_dir=str(old_dir), say=lambda _m: None)
    marker_before = (old_dir / paths.DATA_MARKER).read_bytes()
    general_before = (old_dir / "config" / "general.yaml").read_bytes()

    orig_install = sm.install

    def fail_on_new(names=None, start=True, data_dir=None, port=None, say=print):
        if data_dir and str(home / "Library" / "Application Support" / "RT") in data_dir:
            raise sm.ServiceError("LaunchAgents non scrivibile")
        return orig_install(names=names, start=start, data_dir=data_dir, port=port, say=say)

    monkeypatch.setattr(sm, "install", fail_on_new)
    messages = []
    assert not data_service.post_update(say=messages.append)
    assert any("ripristinato tutto" in m for m in messages)

    new_dir = home / "Library" / "Application Support" / "RT"
    assert not new_dir.exists()
    assert (old_dir / paths.DATA_MARKER).read_bytes() == marker_before
    assert (old_dir / "config" / "general.yaml").read_bytes() == general_before
    spec = plistlib.loads(open(sm.plist_path("api"), "rb").read())
    assert spec["EnvironmentVariables"]["RT_DATA_DIR"] == str(old_dir)
    db = open_database("sqlite:///" + str(old_dir / "rt.db"))
    try:
        with Session(db.engine) as session:
            anat = session.scalar(select(Lesson).where(Lesson.materia == "ANATOMIA"))
            assert anat.path == db_lesson_path
    finally:
        db.engine.dispose()


def test_simulated_downgrade_finds_data_via_location_marker(sandbox, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    old_dir, _folder, _db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    assert data_service.post_update(say=lambda _m: None)
    new_dir = home / "Library" / "Application Support" / "RT"

    # Logica pre-4.3.10b4: default_data_dir() era ~/.rt e leggeva "location" da ~/.rt/rt-data.json
    legacy_path = paths.legacy_data_dir()
    assert paths.is_initialized(legacy_path)
    location = paths.read_marker(legacy_path).get("location")
    resolved = os.path.abspath(os.path.expanduser(location)) if location else legacy_path
    assert resolved == str(new_dir)


def test_no_migration_with_explicit_rt_data_dir_or_external_location(sandbox, tmp_path, monkeypatch):
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)

    # 1. RT_DATA_DIR esplicita già attiva: ~/.rt esiste ma non viene spostata
    old_dir, _folder, _db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    explicit = tmp_path / "custom-data"
    data_service.init_data_dir(str(explicit), say=lambda _m: None)
    monkeypatch.setenv("RT_DATA_DIR", str(explicit))
    assert data_service.post_update(say=lambda _m: None)
    assert not (home / "Library" / "Application Support" / "RT").exists()
    assert (old_dir / "rt.db").is_file()
    assert paths.is_initialized(str(explicit))

    # 2. 3.x con location su disco esterno: non si tocca
    monkeypatch.delenv("RT_DATA_DIR")
    ext_dir = tmp_path / "external-disk" / ".rt"
    data_service.init_data_dir(str(ext_dir), say=lambda _m: None)
    # Riscriviamo ~/.rt come redirect 3.x verso ext_dir
    for p in list(old_dir.iterdir()):
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
        else:
            p.unlink()
    paths.write_marker(str(old_dir), created="2026-01-01T00:00:00", location=str(ext_dir))

    assert data_service.post_update(say=lambda _m: None)
    assert paths.active_data_dir() == str(ext_dir)
    assert not (home / "Library" / "Application Support" / "RT").exists()
    assert paths.read_marker(str(old_dir))["location"] == str(ext_dir)


def test_windows_open_log_streams_suspended_and_reopened(sandbox, monkeypatch):
    _root, home, local_app_data, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.WINDOWS)

    old_dir, _folder, _db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    log_path = old_dir / "logs" / "desktop.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "a", encoding="utf-8", buffering=1, newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    print("riga prima su windows")

    assert data_service.post_update(say=lambda _m: None)
    print("riga dopo su windows")

    new_log = local_app_data / "RT" / "logs" / "desktop.log"
    assert getattr(sys.stdout, "name", "") == str(new_log)
    sys.stdout.close()
    text = new_log.read_text(encoding="utf-8")
    assert "riga prima su windows" in text
    assert "riga dopo su windows" in text


def test_empty_platform_dir_does_not_block_migration(sandbox, monkeypatch):
    """Una cartella Application Support/RT vuota (creata da altri) non deve rimandare lo
    spostamento per sempre; una non vuota sì."""
    _root, home, _local, _agents = sandbox
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(bundle, "kind", lambda _r=None: bundle.MACOS)
    old_dir, _folder, _db_lesson_path, _ext = _seed_legacy_app_data(home, include_folder_lesson=False)
    new_dir = home / "Library" / "Application Support" / "RT"
    new_dir.mkdir(parents=True)
    messages = []
    data_service.post_update(say=messages.append)
    assert (new_dir / paths.DATA_MARKER).is_file()
    assert (new_dir / "rt.db").is_file()
    assert paths.read_marker(str(old_dir)).get("location") == str(new_dir)
