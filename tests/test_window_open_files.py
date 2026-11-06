"""Test per l'apertura e l'importazione di collezioni .rtdb e .zip dal desktop."""
import io
import json
import os
import zipfile
from unittest.mock import Mock

import pytest

from rt import window
from rt.core import opened_files
from rt.services import backup_service as bs


@pytest.fixture
def dummy_rtdb(tmp_path):
    """Crea un file .rtdb valido (archivio ZIP con struttura di backup)."""
    target = tmp_path / "collezione.rtdb"
    snap_dir = "rt-backup-2026-11-03"
    manifest = {
        "format": 1,
        "created": "2026-11-03T14:30:00",
        "rt_version": "4.3.8",
        "database": "rt.db",
        "segreti": False,
        "media": [],
        "archivio": [],
    }
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr(f"{snap_dir}/manifest.json", json.dumps(manifest))
        zf.writestr(f"{snap_dir}/rt.db", b"SQLite format 3\x00" + b"\x00" * 84)
    return str(target)


def test_rtdb_cancelled_confirmation_touches_nothing(dummy_rtdb, monkeypatch, tmp_path):
    """Un .rtdb passato al gestore Python chiama la conferma e, se annullata, non tocca niente."""
    reg = opened_files.register_file(dummy_rtdb)
    assert reg is not None
    token = reg["token"]

    fake_window = Mock()
    fake_window.create_confirmation_dialog.return_value = False

    stream_mock = Mock()
    monkeypatch.setattr(window, "_stream_backup", stream_mock)
    monkeypatch.setattr(window, "_backup_running", False)

    stop_mock = Mock()
    monkeypatch.setattr("rt.desktop.stop_background", stop_mock)

    api = window.DesktopApi(fake_window, base_url="http://127.0.0.1:8765")
    res = api.importa_collezione(token)
    assert res == {"ok": True}

    # Verifica che la conferma sia stata mostrata con il messaggio atteso
    fake_window.create_confirmation_dialog.assert_called_once()
    title, message = fake_window.create_confirmation_dialog.call_args.args
    assert title == "Importa"
    assert "Sostituisce tutte le lezioni, il database e il calendario attuali. Quelli attuali vengono messi da parte." in message
    assert "2026-11-03" in message
    assert "4.3.8" in message

    # Se annullata, non avvia il restore e non ferma i servizi
    stream_mock.assert_not_called()
    stop_mock.assert_not_called()


def test_rtdb_confirmed_starts_restore(dummy_rtdb, monkeypatch):
    """Un .rtdb confermato avvia il ripristino con _stream_backup."""
    reg = opened_files.register_file(dummy_rtdb)
    token = reg["token"]

    fake_window = Mock()
    fake_window.create_confirmation_dialog.return_value = True

    stream_mock = Mock(return_value=True)
    monkeypatch.setattr(window, "_stream_backup", stream_mock)
    monkeypatch.setattr(window, "_backup_running", False)

    api = window.DesktopApi(fake_window, base_url="http://127.0.0.1:8765")
    api.importa_collezione(token)

    stream_mock.assert_called_once()
    args, kwargs = stream_mock.call_args
    assert args[1] == ["restore", dummy_rtdb, "--yes", "--json"]
    assert kwargs.get("tipo") == "importa"


def test_rtdb_refuses_when_backup_running(dummy_rtdb, monkeypatch):
    """Se un lavoro di trasferimento è già in corso, rifiuta senza aprire dialoghi."""
    reg = opened_files.register_file(dummy_rtdb)
    token = reg["token"]

    fake_window = Mock()
    monkeypatch.setattr(window, "_backup_running", True)
    notice_mock = Mock()
    monkeypatch.setattr(window, "_notice", notice_mock)

    api = window.DesktopApi(fake_window, base_url="http://127.0.0.1:8765")
    api.importa_collezione(token)

    fake_window.create_confirmation_dialog.assert_not_called()
    notice_mock.assert_called_once_with(fake_window, "Un trasferimento è già in corso.")


def test_legacy_zip_collection_still_supported(tmp_path, monkeypatch):
    """Gli archivi .zip di collezione continuano a funzionare."""
    target = tmp_path / "vecchia_collezione.zip"
    snap_dir = "rt-backup-2026-10-01"
    manifest = {
        "format": 1,
        "created": "2026-10-01T10:00:00",
        "rt_version": "4.3.0",
        "database": "rt.db",
        "segreti": False,
        "media": [],
        "archivio": [],
    }
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr(f"{snap_dir}/manifest.json", json.dumps(manifest))
        zf.writestr(f"{snap_dir}/rt.db", b"SQLite format 3\x00" + b"\x00" * 84)

    reg = opened_files.register_file(str(target))
    token = reg["token"]

    fake_window = Mock()
    fake_window.create_confirmation_dialog.return_value = True

    stream_mock = Mock(return_value=True)
    monkeypatch.setattr(window, "_stream_backup", stream_mock)
    monkeypatch.setattr(window, "_backup_running", False)

    api = window.DesktopApi(fake_window, base_url="http://127.0.0.1:8765")
    api.importa_collezione(token)

    stream_mock.assert_called_once()
    assert stream_mock.call_args.args[1] == ["restore", str(target), "--yes", "--json"]
