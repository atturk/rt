"""Test per il backup leggero prima degli aggiornamenti, rotazione a 5 e ripristino (Voce 5)."""
import os
import sqlite3
import time
import zipfile
from unittest.mock import Mock, patch

import pytest

from rt.core import paths
from rt.services import backup_service as bs


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("RT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{data_dir}/rt.db")

    # Inizializza un database SQLite finto con una tabella
    db_file = data_dir / "rt.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test_data (name) VALUES ('valore_originale')")
    conn.commit()
    conn.close()

    # Crea cartella lezioni con file di testo e file multimediali da escludere
    lesson_dir = data_dir / "lessons" / "[2026-10-01] MATERIA - Titolo Lezione"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "info.yaml").write_text("titolo: Titolo Lezione\n", encoding="utf-8")
    (lesson_dir / "trascritto grezzo.md").write_text("# Trascritto\n", encoding="utf-8")
    state_dir = lesson_dir / "_state"
    state_dir.mkdir()
    (state_dir / "outline.json").write_text('{"units": []}', encoding="utf-8")

    # File che DEVONO essere esclusi dal backup leggero
    (lesson_dir / "audio.mp3").write_bytes(b"FAKE_AUDIO_DATA")
    (lesson_dir / "slide.pdf").write_bytes(b"FAKE_PDF_DATA")
    media_dir = lesson_dir / "media"
    media_dir.mkdir()
    (media_dir / "image.png").write_bytes(b"FAKE_PNG_DATA")

    return {
        "data_dir": data_dir,
        "db_file": db_file,
        "lesson_dir": lesson_dir,
    }


def test_create_pre_update_backup_and_exclusions(test_env):
    zip_path = bs.create_pre_update_backup(version="4.3.8")
    assert os.path.isfile(zip_path)
    assert os.path.basename(zip_path).startswith("rt-4.3.8-")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        # Include database, manifest e file di testo
        assert "rt.db" in names
        assert "manifest.json" in names
        assert any("info.yaml" in n for n in names)
        assert any("trascritto grezzo.md" in n for n in names)
        assert any("outline.json" in n for n in names)

        # Esclude audio, immagini, PDF e cartella media
        assert not any(n.endswith(".mp3") for n in names)
        assert not any(n.endswith(".pdf") for n in names)
        assert not any(n.endswith(".png") for n in names)
        assert not any("/media/" in n for n in names)


def test_rotate_pre_update_backups_keeps_last_5(test_env):
    dest = bs.pre_update_dir()
    os.makedirs(dest, exist_ok=True)

    # Crea 7 backup finti con timestamp progressivi
    for i in range(1, 8):
        fake_zip = os.path.join(dest, f"rt-4.3.8-2026110{i}-120000.zip")
        with zipfile.ZipFile(fake_zip, "w") as zf:
            zf.writestr("manifest.json", f'{{"rt_version": "4.3.8", "type": "pre_update", "created": "2026-11-0{i}T12:00:00"}}')
        # Imposta mtime crescente
        os.utime(fake_zip, (1000 + i * 10, 1000 + i * 10))

    backups_before = bs.list_pre_update_backups()
    assert len(backups_before) == 7

    bs.rotate_pre_update_backups(keep=5)

    backups_after = bs.list_pre_update_backups()
    assert len(backups_after) == 5

    # I due più vecchi (20261101 e 20261102) sono stati eliminati
    filenames = [b["filename"] for b in backups_after]
    assert "rt-4.3.8-20261101-120000.zip" not in filenames
    assert "rt-4.3.8-20261102-120000.zip" not in filenames
    assert "rt-4.3.8-20261107-120000.zip" in filenames


def test_restore_pre_update_backup(test_env):
    # 1. Crea il backup iniziale
    zip_path = bs.create_pre_update_backup(version="4.3.8")

    # 2. Modifica i dati correnti: database e testi
    conn = sqlite3.connect(str(test_env["db_file"]))
    conn.execute("UPDATE test_data SET name = 'valore_modificato'")
    conn.commit()
    conn.close()

    lesson_info = test_env["lesson_dir"] / "info.yaml"
    lesson_info.write_text("titolo: Titolo Modificato\n", encoding="utf-8")

    # File media aggiunto successivamente (non deve sparire dopo il restore)
    new_media = test_env["lesson_dir"] / "media" / "foto.jpg"
    new_media.write_bytes(b"NEW_PHOTO")

    # 3. Esegue il ripristino
    aside = bs.restore_pre_update_backup(zip_path)
    assert os.path.isdir(aside)

    # 4. Verifica che i dati del database siano stati ripristinati allo stato del backup
    conn = sqlite3.connect(str(test_env["db_file"]))
    row = conn.execute("SELECT name FROM test_data WHERE id = 1").fetchone()
    conn.close()
    assert row[0] == "valore_originale"

    # 5. Verifica che il file di testo sia stato ripristinato
    assert "Titolo Lezione" in lesson_info.read_text(encoding="utf-8")

    # 6. Verifica che i media esistenti non siano stati toccati
    assert new_media.exists()
    assert new_media.read_bytes() == b"NEW_PHOTO"

    # 7. Verifica che i dati messi da parte contengano le modifiche
    assert os.path.exists(os.path.join(aside, "rt.db"))


def test_app_update_install_aborts_if_backup_fails(monkeypatch, tmp_path):
    from rt.core import app_update

    def fail_backup(version=None):
        raise bs.BackupError("Spazio su disco esaurito")

    monkeypatch.setattr(bs, "create_pre_update_backup", fail_backup)

    with pytest.raises(app_update.AppUpdateError) as exc_info:
        app_update.install("/path/fake-installer", project_root=str(tmp_path))

    assert "Backup pre-aggiornamento non riuscito" in str(exc_info.value)
    assert "Spazio su disco esaurito" in str(exc_info.value)


def test_version_run_update_aborts_if_backup_fails(monkeypatch, tmp_path, capsys):
    from rt.core import version

    monkeypatch.setattr(version, "get_current_version", lambda root: "4.3.7")
    monkeypatch.setattr(version, "get_latest_remote_version", lambda root, **kw: "4.3.8")
    monkeypatch.setattr(version, "_stop_services", lambda root: [])

    def fail_backup(ver=None):
        raise bs.BackupError("Errore I/O durante la copia")

    monkeypatch.setattr(bs, "create_pre_update_backup", fail_backup)

    # Non deve essere un checkout git per questo ramo di test
    monkeypatch.setattr(os.path, "exists", lambda p: False)

    code = version._run_update(str(tmp_path))
    assert code == 1

    err = capsys.readouterr().err
    assert "Backup pre-aggiornamento non riuscito" in err
    assert "Errore I/O durante la copia" in err


def test_cli_restore_pre_update(test_env, capsys):
    from rt import cli_system
    import argparse

    zip_path = bs.create_pre_update_backup(version="4.3.8")

    # Modifica il db
    conn = sqlite3.connect(str(test_env["db_file"]))
    conn.execute("UPDATE test_data SET name = 'modificato'")
    conn.commit()
    conn.close()

    # Esegue restore con --pre-update e --yes
    args = argparse.Namespace(source=None, pre_update=True, yes=True, json=False)
    cli_system.cmd_restore(args)

    out = capsys.readouterr().out
    assert "Ripristino completato con successo" in out

    # Verifica db ripristinato
    conn = sqlite3.connect(str(test_env["db_file"]))
    row = conn.execute("SELECT name FROM test_data WHERE id = 1").fetchone()
    conn.close()
    assert row[0] == "valore_originale"

