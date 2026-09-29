"""
RT4-G1: 'rt backup' / 'rt restore' (rt.services.backup_service): DB coerente, media
incrementali per hash, configurazione e segreti cifrati, verifica dei media referenziati.
"""
import hashlib
import os

import pytest

from rt.db.engine import get_database, reset_database_cache
from rt.db.models import Lesson, LessonFile
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
                       + f"\ntelegram:\n  lessons_root: {str(tmp_path / 'sparita')!r}\n", encoding="utf-8")
    from rt.core.config import load_config
    assert load_config().telegram.lessons_root == str(tmp_path / "sparita")
    assert doctor_service.check_config().status == doctor_service.OK
    assert doctor_service.check_folder_lessons().status == doctor_service.OK
