"""Test per la gestione delle donazioni (Voce 7)."""
import os
import tempfile
from unittest.mock import patch

from rt.core import donazioni
from scripts.build_docs_site import prepare_site_docs


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


def test_build_docs_site_donazioni_empty(monkeypatch, tmp_path):
    target = tmp_path / "site_docs"
    with patch("scripts.build_docs_site.DONAZIONI_URL", ""):
        prepare_site_docs(str(target))
    index_md = (target / "index.md").read_text(encoding="utf-8")
    assert "Sostieni RT" not in index_md


def test_build_docs_site_donazioni_configured(monkeypatch, tmp_path):
    target = tmp_path / "site_docs"
    with patch("scripts.build_docs_site.DONAZIONI_URL", "https://ko-fi.com/example"):
        prepare_site_docs(str(target))
    index_md = (target / "index.md").read_text(encoding="utf-8")
    assert "[Sostieni RT](https://ko-fi.com/example)" in index_md
