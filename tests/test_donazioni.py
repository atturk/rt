"""Test per la gestione delle donazioni (Voce 7)."""
from rt.core import donazioni
from scripts.build_docs_site import prepare_landing


def test_system_info_donazioni_empty(api_client, monkeypatch):
    monkeypatch.setattr(donazioni, "DONAZIONI_URL", "")
    res = api_client.get("/api/v1/system/info")
    assert res.status_code == 200
    data = res.json()
    assert "donazioni_url" in data
    assert data["donazioni_url"] == ""


def test_system_info_donazioni_custom(api_client, monkeypatch):
    monkeypatch.setattr(donazioni, "DONAZIONI_URL", "https://ko-fi.com/example")
    res = api_client.get("/api/v1/system/info")
    assert res.status_code == 200
    data = res.json()
    assert data["donazioni_url"] == "https://ko-fi.com/example"


def test_build_docs_site_donazioni_empty(tmp_path):
    prepare_landing(str(tmp_path), donazioni_url="")
    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Sostieni RT" not in index_html
    assert "DONAZIONI_SEGNAPOSTO" not in index_html


def test_build_docs_site_donazioni_configured(tmp_path):
    prepare_landing(str(tmp_path), donazioni_url="https://ko-fi.com/example")
    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<a class="btn pri" href="https://ko-fi.com/example">Sostieni RT</a>' in index_html


def test_build_docs_site_versione(tmp_path):
    prepare_landing(str(tmp_path), donazioni_url="")
    versione = open("VERSION", encoding="utf-8").read().strip()
    download = (tmp_path / "download.html").read_text(encoding="utf-8")
    assert "{{VERSIONE}}" not in download
    assert f"releases/download/v{versione}/RT-{versione}-macos-arm64.dmg" in download
    assert f"RT-{versione}-windows-x64-setup.exe" in download
    assert (tmp_path / ".nojekyll").exists()
    assert not (tmp_path / "img" / "README.md").exists()
