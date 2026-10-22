"""
RT4-G1: 'rt backup' / 'rt restore' (rt.services.backup_service): DB coerente, media
incrementali per hash, configurazione e segreti cifrati, verifica dei media referenziati.
"""
import hashlib
import json
import os
import shutil

import pytest

from rt.db.engine import get_database, reset_database_cache
from rt.db.models import Lesson, LessonFile, StudyUnit, utcnow
from rt.db.session import session_scope
from rt.services import backup_service as bs
from rt.services import data_service


@pytest.fixture
def data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("RT_DATA_DIR", str(data))
    monkeypatch.delenv("RT_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    reset_database_cache()
    data_service.init_data_dir(say=lambda _m: None)
    (data / "config" / "secrets.enc").write_text("cifrato", encoding="utf-8")
    (data / ".env").write_text("RT_TELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    db = get_database(create=True)
    yield data, db
    reset_database_cache()


def _add_media(db, data, lesson_id: int, name: str, content: bytes) -> str:
    rel = f"L{lesson_id}_{name}"
    (data / "media").mkdir(exist_ok=True)
    (data / "media" / rel).write_bytes(content)
    with session_scope(db) as s:
        if s.get(Lesson, lesson_id) is None:
            s.add(Lesson(id=lesson_id, path=f"/lezioni/L{lesson_id}", folder_name=f"L{lesson_id}", storage="db"))
            s.flush()
        s.add(LessonFile(lesson_id=lesson_id, name=name, media_path=rel, size=len(content),
                         sha256=hashlib.sha256(content).hexdigest()))
    return rel


def test_backup_is_incremental_and_complete(data, tmp_path, monkeypatch):
    data_dir, db = data
    monkeypatch.setenv("RT_SECRETS_FILE", str(data_dir / "config" / "secrets.enc"))
    _add_media(db, data_dir, 1, "audio.m4a", b"audio-1")
    dest = tmp_path / "esterno"

    first = bs.create_backup(str(dest), say=lambda _m: None)
    assert (first.media_total, first.media_copied) == (1, 1)
    snap = first.path
    assert os.path.isfile(os.path.join(snap, "rt.db"))
    assert open(os.path.join(snap, "config", "secrets.enc")).read() == "cifrato"
    assert open(os.path.join(snap, "env")).read() == "RT_TELEGRAM_CHAT_ID=42\n"
    assert first.master_key_warning and "chiave master" in first.master_key_warning

    _add_media(db, data_dir, 1, "slide.png", b"png")
    import time
    time.sleep(1.1)  # nome della cartella al secondo
    second = bs.create_backup(str(dest), say=lambda _m: None)
    assert (second.media_total, second.media_copied) == (2, 1)  # solo il file nuovo
    assert [b["path"] for b in bs.list_backups(str(dest))] == [second.path, first.path]


def test_backup_refuses_missing_media(data, tmp_path):
    data_dir, db = data
    rel = _add_media(db, data_dir, 1, "audio.m4a", b"audio")
    os.remove(data_dir / "media" / rel)
    assert bs.verify_media(db, str(data_dir / "media")) == [f"{rel}: file mancante"]
    with pytest.raises(bs.BackupError, match="mancano"):
        bs.create_backup(str(tmp_path / "b"), say=lambda _m: None)
    res = bs.create_backup(str(tmp_path / "b"), say=lambda _m: None, allow_missing=True)
    assert res.missing == [rel]


def test_restore_brings_back_db_media_and_config(data, tmp_path, monkeypatch):
    data_dir, db = data
    rel = _add_media(db, data_dir, 1, "audio.m4a", b"audio")
    monkeypatch.setattr(data_service, "running_services", lambda: [])
    at = utcnow()
    with session_scope(db) as s:
        s.add(StudyUnit(lesson_id=1, unit_id="1.1", status="appreso", status_at=at, last_read_at=at))
    snap = bs.create_backup(str(tmp_path / "b"), say=lambda _m: None).path

    # disastro: media persi, configurazione cambiata, una lezione in più nel DB
    os.remove(data_dir / "media" / rel)
    (data_dir / "config" / "secrets.enc").write_text("altro", encoding="utf-8")
    with session_scope(db) as s:
        s.add(Lesson(id=2, path="/lezioni/L2", folder_name="L2", storage="db"))

    aside = bs.restore_backup(str(tmp_path / "b"), say=lambda _m: None)  # la cartella: prende il più recente
    reset_database_cache()
    restored = get_database()
    with session_scope(restored) as s:
        assert s.get(Lesson, 2) is None and s.get(Lesson, 1) is not None
        study = s.get(StudyUnit, (1, "1.1"))
        assert study.status == "appreso" and study.status_at == at and study.last_read_at == at
    assert (data_dir / "media" / rel).read_bytes() == b"audio"
    assert (data_dir / "config" / "secrets.enc").read_text() == "cifrato"
    assert os.path.isfile(os.path.join(aside, "config", "secrets.enc"))  # la versione sostituita resta
    assert snap in [b["path"] for b in bs.list_backups(str(tmp_path / "b"))]


def test_restore_refuses_incomplete_backup(data, tmp_path):
    data_dir, db = data
    _add_media(db, data_dir, 1, "audio.m4a", b"audio")
    bs.create_backup(str(tmp_path / "b"), say=lambda _m: None)
    store = tmp_path / "b" / bs.STORE
    for base, _d, files in os.walk(store):
        for f in files:
            os.remove(os.path.join(base, f))
    with pytest.raises(bs.BackupError, match="incompleto"):
        bs.restore_backup(str(tmp_path / "b"), say=lambda _m: None, check_services=False)


def test_cli_backup_and_doctor(data, tmp_path, capsys):
    from rt.cli import main
    main(["backup", "--dest", str(tmp_path / "b")])
    assert "Backup completo" in capsys.readouterr().out
    # Doctor exits nonzero only for a FAIL; warnings are actionable but not fatal.
    exit_code = 0
    try:
        main(["doctor", "--json"])
    except SystemExit as exc:
        exit_code = exc.code
    out = capsys.readouterr().out
    assert '"Database"' in out and '"Cartella dati"' in out
    import json
    assert exit_code == (1 if json.loads(out)["status"] == "fail" else 0)


def test_doctor_ignores_missing_lessons_folder(data, tmp_path):
    """Le lezioni stanno nel database: né una cartella delle lezioni assente né una configurata
    e sparita (Mac del beta tester) danno avvisi; le lezioni a cartelle si cercano solo se c'è."""
    from rt.services import doctor_service
    data_dir, _db = data
    general = data_dir / "config" / "general.yaml"
    assert doctor_service.check_config().status == doctor_service.OK
    general.write_text(general.read_text(encoding="utf-8")
                       + f"\ntelegram:\n  lessons_root: {json.dumps(str(tmp_path / 'sparita'))}\n", encoding="utf-8")
    from rt.core.config import load_config
    assert load_config().telegram.lessons_root == str(tmp_path / "sparita")
    assert doctor_service.check_config().status == doctor_service.OK
    assert doctor_service.check_folder_lessons().status == doctor_service.OK


def test_restore_names_the_missing_media_store(data, tmp_path):
    """Copiando solo rt-backup-<data> su un altro Mac, l'errore dice dove cercare i media."""
    data_dir, db = data
    _add_media(db, data_dir, 1, "audio.m4a", b"audio")
    snap = bs.create_backup(str(tmp_path / "b"), say=lambda _m: None).path
    moved = tmp_path / "altro-mac" / os.path.basename(snap)
    shutil.copytree(snap, moved)
    with pytest.raises(bs.BackupError, match="manca la cartella .*media-store.*Nulla è stato modificato"):
        bs.restore_backup(str(moved), say=lambda _m: None, check_services=False)


def test_backup_progress_reports_phases_in_order(data, tmp_path):
    data_dir, db = data
    _add_media(db, data_dir, 1, "audio1.m4a", b"audio-1")
    _add_media(db, data_dir, 1, "audio2.m4a", b"audio-2")
    events = []
    bs.create_backup(str(tmp_path / "b"), say=lambda _m: None,
                     progress=lambda fase, fatto, tot: events.append((fase, fatto, tot)))
    assert events[0] == ("database", 0, 1)
    assert events[1] == ("database", 1, 1)
    media_events = [e for e in events if e[0] == "media"]
    assert media_events == [("media", 1, 2), ("media", 2, 2)]
    assert events[-1] == ("config", 1, 1)


def test_export_backup_and_restore_zip(data, tmp_path, monkeypatch):
    import zipfile
    data_dir, db = data
    rel = _add_media(db, data_dir, 1, "audio.m4a", b"audio-export")
    snap = bs.create_backup(str(tmp_path / "b"), say=lambda _m: None).path

    copy_events = []
    zip_path = bs.export_backup(snap, str(tmp_path / "esportato.zip"),
                                progress=lambda f, b, t: copy_events.append((f, b, t)))
    assert os.path.isfile(zip_path)
    assert copy_events[0][0] == "copia"
    assert copy_events[-1][1] == copy_events[-1][2]  # bytes_written == total_bytes

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        snap_base = os.path.basename(snap)
        assert f"{snap_base}/manifest.json" in names
        assert f"{snap_base}/rt.db" in names
        media_files = [n for n in names if n.startswith("media-store/")]
        assert len(media_files) == 1

    # Ripristino in una cartella dati vergine usando il file .zip
    other_data = tmp_path / "other_data"
    monkeypatch.setenv("RT_DATA_DIR", str(other_data))
    reset_database_cache()
    data_service.init_data_dir(say=lambda _m: None)

    aside = bs.restore_backup(zip_path, say=lambda _m: None, check_services=False)
    assert os.path.isdir(aside)
    reset_database_cache()
    restored_db = get_database()
    with session_scope(restored_db) as s:
        assert s.get(Lesson, 1) is not None
    assert (other_data / "media" / rel).read_bytes() == b"audio-export"


def test_restore_zip_rejects_unsafe_paths(data, tmp_path):
    import zipfile
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../pericolo.txt", "evil")
        zf.writestr("rt-backup-20261019-120000/manifest.json", "{}")
    with pytest.raises(bs.BackupError, match="non sicuro"):
        bs.restore_backup(str(bad_zip), say=lambda _m: None, check_services=False)


def test_export_error_cleans_up_part_file(data, tmp_path, monkeypatch):
    data_dir, db = data
    snap = bs.create_backup(str(tmp_path / "b"), say=lambda _m: None).path
    target_zip = tmp_path / "fallito.zip"

    def fail_progress(*_args):
        raise RuntimeError("simulated disk error")

    with pytest.raises(RuntimeError, match="simulated disk error"):
        bs.export_backup(snap, str(target_zip), progress=fail_progress)

    assert not os.path.exists(str(target_zip))
    assert not os.path.exists(str(target_zip) + ".part")


def test_cli_backup_progress_json(data, tmp_path, capsys):
    from rt.cli import main
    main(["backup", "--dest", str(tmp_path / "b"), "--progress-json"])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    phases = [l.get("fase") for l in lines if "fase" in l]
    assert "database" in phases and "config" in phases
    last = lines[-1]
    assert last.get("fine") is True
    assert "percorso" in last and "riepilogo" in last


def test_archive_roundtrip_and_incremental_store(data, tmp_path):
    data_dir, _db = data
    from rt.core.archive import register_file, original_path
    original = tmp_path / 'source.txt'
    original.write_text('contenuto condiviso')
    meta = register_file(str(original), nome='source.txt', tipo='testo')
    snap = bs.create_backup(str(tmp_path / 'backup'), say=lambda _: None).path
    shutil.rmtree(data_dir / 'archivio')
    bs.restore_backup(snap, say=lambda _: None, check_services=False)
    assert open(original_path(meta['impronta'])).read() == 'contenuto condiviso'


def test_export_without_secrets_and_import_preserves_local_keys(data, tmp_path, monkeypatch):
    import zipfile
    import yaml
    data_dir, db = data
    rel = _add_media(db, data_dir, 1, 'audio.m4a', b'audio')
    (data_dir / 'archivio').mkdir(exist_ok=True)
    (data_dir / 'archivio' / 'fonte.pdf').write_bytes(b'archivio')
    (data_dir / '.env').write_text('APP_KEY=old\nGOOGLE_API_KEY_1=old-google\nRT_MASTER_KEY=old-master\nACCESS_TOKEN="line1\nline2"\nNORMAL=imported\n')
    general = data_dir / 'config' / 'general.yaml'
    general.write_text(yaml.safe_dump({'telegram': {'lessons_root': '/old-pc/lessons', 'state_dir': '/old-pc/bot'}, 'database_url': 'sqlite:////old-pc/rt.db'}))
    # Keep using the database from the fixture when the foreign config is written.
    monkeypatch.setenv('RT_DATABASE_URL', db.url)
    snapshot = bs.create_backup(str(tmp_path / 'snapshots'), say=lambda _: None).path
    zipped = bs.export_backup(snapshot, str(tmp_path / 'collection.zip'))
    with zipfile.ZipFile(zipped) as archive:
        prefix = os.path.basename(snapshot)
        assert prefix + '/config/secrets.enc' not in archive.namelist()
        manifest = json.loads(archive.read(prefix + '/manifest.json'))
        assert manifest['segreti'] is False
        env = archive.read(prefix + '/env').decode()
        assert env == 'NORMAL=imported\n'
        assert not any(secret in env for secret in ('old-google', 'old-master', 'line2'))
        assert prefix + '/rt.db' in archive.namelist()
    (data_dir / 'config' / 'secrets.enc').write_text('local-encrypted')
    (data_dir / '.env').write_text('APP_KEY=local\nNEW_PASSWORD=local-password\nNORMAL=old\n')
    with session_scope(db) as session:
        session.add(Lesson(id=2, path='/other', folder_name='other', storage='db'))
    os.remove(data_dir / 'media' / rel)
    os.remove(data_dir / 'archivio' / 'fonte.pdf')
    lines = []
    aside = bs.restore_backup(zipped, check_services=False, say=lines.append)
    assert (data_dir / 'config' / 'secrets.enc').read_text() == 'local-encrypted'
    assert (data_dir / '.env').read_text() == 'NORMAL=imported\nAPP_KEY=local\nNEW_PASSWORD=local-password\n'
    assert (data_dir / 'media' / rel).read_bytes() == b'audio'
    assert (data_dir / 'archivio' / 'fonte.pdf').read_bytes() == b'archivio'
    assert not os.path.exists(os.path.join(aside, 'config', 'secrets.enc'))
    with session_scope(get_database()) as session:
        assert session.get(Lesson, 1) is not None
        assert session.get(Lesson, 2) is None
    config = yaml.safe_load(general.read_text())
    assert config['telegram']['lessons_root'] is None
    assert config['telegram']['state_dir'] == '.rt_telegram'
    assert config['database_url'] == 'sqlite:///' + str(data_dir / 'rt.db')
    assert any('telegram.lessons_root' in line for line in lines)


def test_collection_export_requires_confirmation_and_migrates_folders(data, tmp_path):
    data_dir, db = data
    from rt.db.sync import dual_write_lesson
    folder = tmp_path / '[2026-10-21] TEST'
    folder.mkdir()
    (folder / 'info.yaml').write_text('data: 2026-10-21\nmateria: TEST\n')
    dual_write_lesson(str(folder))
    target = tmp_path / 'collection.zip'
    assert bs.export_collection(str(target), confirm=lambda _: False, say=lambda _: None) is None
    assert folder.exists() and not target.exists()
    exported = bs.export_collection(str(target), confirm=lambda count: count == 1, say=lambda _: None)
    assert exported == str(target)
    assert not folder.exists()
    assert list((data_dir / 'backups').glob('migrazione-*/lezioni/*/info.yaml'))
    assert bs.inspect_backup_zip(exported)['segreti'] is False


@pytest.mark.parametrize('kind', ['invalid', 'future'])
def test_invalid_collection_does_not_change_data(data, tmp_path, kind):
    import zipfile
    data_dir, db = data
    original = (data_dir / 'config' / 'secrets.enc').read_bytes()
    target = tmp_path / 'bad.zip'
    if kind == 'invalid':
        target.write_bytes(b'not a zip')
    else:
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('rt-backup-test/manifest.json', json.dumps({'format': bs.FORMAT + 1, 'database': 'rt.db'}))
    with pytest.raises(bs.BackupError):
        bs.restore_backup(str(target), check_services=False, say=lambda _: None)
    assert (data_dir / 'config' / 'secrets.enc').read_bytes() == original
    assert not list((data_dir / 'backups').glob('prima-del-ripristino-*'))


def test_cli_collection_export_import_json(data, tmp_path, capsys, monkeypatch):
    from rt.cli import main
    data_dir, db = data
    monkeypatch.setattr(data_service, 'running_services', lambda: [])
    target = tmp_path / 'collection.zip'
    main(['export', str(target), '--yes', '--json'])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]['fine'] and events[-1]['percorso'] == str(target)
    main(['import', str(target), '--yes', '--json'])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]['fine'] and 'prima-del-ripristino-' in events[-1]['percorso']


def test_restore_closes_database_before_moving_files(data, tmp_path, monkeypatch):
    import rt.db.engine as engine
    data_dir, db = data
    snapshot = bs.create_backup(str(tmp_path / 'backup'), say=lambda _: None).path
    real_reset, real_move = engine.reset_database_cache, bs.shutil.move
    closed = []
    def reset():
        real_reset()
        closed.append(True)
    def move(source, destination, *args, **kwargs):
        if str(source).endswith(('rt.db', 'rt.db-wal', 'rt.db-shm')):
            assert closed, 'SQLite va chiuso prima dello spostamento, anche su Windows'
        return real_move(source, destination, *args, **kwargs)
    monkeypatch.setattr(engine, 'reset_database_cache', reset)
    monkeypatch.setattr(bs.shutil, 'move', move)
    bs.restore_backup(snapshot, check_services=False, say=lambda _: None)


def test_portable_import_rebases_windows_lesson_paths(data, tmp_path):
    from rt.db.models import Job, RecallSession
    from rt.storage import fs
    data_dir, db = data
    _add_media(db, data_dir, 1, 'audio.m4a', b'audio')
    old_path = r'C:\Users\Old\lessons\L1'
    with session_scope(db) as session:
        session.get(Lesson, 1).path = old_path
        session.add(Job(id='old-job', type='run_phase', state='succeeded', lesson_path=old_path, payload={}))
    snapshot = bs.create_backup(str(tmp_path / 'backups'), say=lambda _: None).path
    archive = bs.export_backup(snapshot, str(tmp_path / 'collection.zip'))
    bs.restore_backup(archive, check_services=False, say=lambda _: None)
    with session_scope(get_database()) as session:
        lesson = session.get(Lesson, 1)
        assert lesson.path == str(data_dir / 'lessons' / 'L1')
        assert session.get(Job, 'old-job').lesson_path == lesson.path
        assert fs.isfile(os.path.join(lesson.path, 'audio.m4a'))
