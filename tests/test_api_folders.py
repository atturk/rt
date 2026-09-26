"""
tests/test_api_folders.py
RT4-FA6: scelta della cartella dati dalla web. La finestra nativa di Finder passa da
un'astrazione sostituita nei test; il ripiego è il navigatore basato su GET /system/folders
(solo cartelle, solo dentro la home, solo da loopback).
"""
import pytest
from fastapi.testclient import TestClient

from rt.services import folder_picker

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def home(tmp_path, monkeypatch, rt_db):
    home = tmp_path / "home"
    for d in ("Documenti/Università", "Documenti/RT Lezioni", "Scrivania", ".nascosta"):
        (home / d).mkdir(parents=True)
    (home / "Documenti" / "nota.txt").write_text("file, non cartella", encoding="utf-8")
    (tmp_path / "fuori").mkdir()
    (home / "collegamento").symlink_to(tmp_path / "fuori")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(folder_picker.Path, "home", classmethod(lambda cls: home))
    yield home
    folder_picker.set_native_chooser(None)


@pytest.fixture
def local(api_token):
    from rt.api.app import create_app
    client = TestClient(create_app(), client=LOCAL)
    client.headers["Authorization"] = f"Bearer {api_token}"
    return client


def test_listing_starts_from_home_with_only_folders(local, home):
    res = local.get("/api/v1/system/folders")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["path"] == str(home.resolve()) and data["parent"] is None and data["home"] == str(home.resolve())
    # niente cartelle nascoste, niente link che escono dalla home
    assert [f["name"] for f in data["folders"]] == ["Documenti", "Scrivania"]

    sub = local.get("/api/v1/system/folders", params={"path": data["folders"][0]["path"]}).json()
    assert [f["name"] for f in sub["folders"]] == ["RT Lezioni", "Università"]  # nessun file
    assert sub["parent"] == str(home.resolve())


def test_listing_refuses_paths_outside_home(local, home, tmp_path):
    for path in (str(tmp_path / "fuori"), "/", str(home / ".." / "..")):
        res = local.get("/api/v1/system/folders", params={"path": path})
        assert res.status_code == 403 and res.json()["error"]["code"] == "folder_not_allowed"
    assert local.get("/api/v1/system/folders", params={"path": str(home / "inesistente")}).status_code == 403


def test_loopback_only(api_client, home):
    """TestClient senza client esplicito arriva da 'testclient', cioè non da loopback."""
    assert api_client.get("/api/v1/system/folders").status_code == 403
    res = api_client.post("/api/v1/system/choose-folder", json={})
    assert res.status_code == 403 and res.json()["error"]["code"] == "loopback_only"


def test_requires_authentication(home):
    from rt.api.app import create_app
    assert TestClient(create_app(), client=LOCAL).get("/api/v1/system/folders").status_code == 401


def test_native_chooser_unavailable_falls_back(local, home, monkeypatch):
    monkeypatch.setenv("RT_NATIVE_FOLDER_PICKER", "0")
    assert local.post("/api/v1/system/choose-folder", json={}).json() == {"status": "unavailable", "path": None}


def test_native_chooser_chosen_and_cancelled(local, home):
    seen = []

    def chosen(start):
        seen.append(start)
        return str(home / "Documenti" / "RT Lezioni")

    folder_picker.set_native_chooser(chosen)
    res = local.post("/api/v1/system/choose-folder", json={"start": str(home)})
    assert res.json() == {"status": "chosen", "path": str(home / "Documenti" / "RT Lezioni")} and seen == [str(home)]

    folder_picker.set_native_chooser(lambda start: None)
    assert local.post("/api/v1/system/choose-folder", json={}).json() == {"status": "cancelled", "path": None}


def test_macos_chooser_parses_osascript(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(folder_picker.shutil, "which", lambda name: "/usr/bin/osascript")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "annulla" in str(tmp_path):
            return subprocess.CompletedProcess(args, 1, "", "execution error: User canceled. (-128)")
        return subprocess.CompletedProcess(args, 0, "/Users/me/RT Lezioni/\n", "")

    monkeypatch.setattr(folder_picker.subprocess, "run", run)
    assert folder_picker._macos_chooser(str(tmp_path)) == "/Users/me/RT Lezioni"
    # il percorso iniziale e il testo passano come argomenti, mai dentro lo script
    assert calls[0][-2:] == [folder_picker.PROMPT, str(tmp_path)]

    monkeypatch.setattr(folder_picker.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "User canceled. (-128)"))
    assert folder_picker._macos_chooser(None) is None
    monkeypatch.setattr(folder_picker.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "altro errore"))
    with pytest.raises(folder_picker.FolderPickerUnavailable):
        folder_picker._macos_chooser(None)
