"""
tests/test_review_436.py
Code review prima del rilascio pubblico (4.3.6b1): registro degli errori del frontend,
polling fuori da api.log, controllo "solo da questo computer" dietro Tailscale, ripristino
interrotto a metà, importazione fallita che lascia riavviare RT.
"""
import logging

import pytest
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def client(api_token):
    from rt.api.app import create_app
    from rt.api.routers import system
    system._client_log_seen.clear()
    c = TestClient(create_app(), client=LOCAL)
    c.headers["Authorization"] = f"Bearer {api_token}"
    return c


def test_client_log_writes_one_line_with_stack(client, capsys):
    res = client.post("/api/v1/system/client-log", json={
        "level": "error", "message": "TypeError: x is undefined\nseconda riga",
        "page": "/lezioni/3?panel=studio", "stack": "at Study (Study.tsx:10)\nat App"})
    assert res.status_code == 204
    out = capsys.readouterr().out
    assert "🔴 frontend error [/lezioni/3?panel=studio] TypeError: x is undefined ⏎ seconda riga" in out
    assert "    at Study (Study.tsx:10)" in out and "    at App" in out


def test_client_log_skips_repeats_within_a_minute(client, capsys):
    body = {"level": "warn", "message": "stesso avviso"}
    assert client.post("/api/v1/system/client-log", json=body).status_code == 204
    assert client.post("/api/v1/system/client-log", json=body).status_code == 204
    assert capsys.readouterr().out.count("stesso avviso") == 1


def test_client_log_requires_auth_and_valid_level(client):
    from rt.api.app import create_app
    anon = TestClient(create_app(), client=LOCAL)
    assert anon.post("/api/v1/system/client-log", json={"level": "error", "message": "x"}).status_code == 401
    assert client.post("/api/v1/system/client-log", json={"level": "info", "message": "x"}).status_code == 422
    too_long = {"level": "error", "message": "x" * 2001}
    assert client.post("/api/v1/system/client-log", json=too_long).status_code == 422


def _access(path, status=200, method="GET"):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:1", method, path, "1.1", status), None)


@pytest.mark.parametrize("path,status,method,kept", [
    ("/api/v1/jobs?limit=50", 200, "GET", False),
    ("/api/v1/workers", 200, "GET", False),
    ("/api/v1/lessons/12/classifier", 304, "GET", False),
    ("/api/v1/system/update", 200, "GET", False),
    ("/api/v1/jobs?limit=50", 500, "GET", True),
    ("/api/v1/jobs", 202, "POST", True),
    ("/api/v1/jobs/abc", 200, "GET", True),
    ("/api/v1/lessons/12", 200, "GET", True),
])
def test_polling_filter_keeps_only_useful_lines(path, status, method, kept):
    from rt.api.server import PollingAccessFilter
    assert PollingAccessFilter().filter(_access(path, status, method)) is kept


def test_log_config_attaches_filter_to_access_handler():
    from uvicorn.config import LOGGING_CONFIG
    from rt.api.server import log_config
    config = log_config()
    assert "polling" in config["handlers"]["access"]["filters"]
    assert "filters" not in LOGGING_CONFIG["handlers"]["access"]  # la copia di uvicorn resta intatta


def test_folders_refuse_requests_forwarded_by_tailscale(client):
    res = client.get("/api/v1/system/folders", headers={"Tailscale-User-Login": "io@example.com"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "loopback_only"
    res = client.post("/api/v1/system/choose-folder", json={}, headers={"X-Forwarded-For": "100.64.0.2"})
    assert res.status_code == 403


def test_import_failure_still_allows_restart(monkeypatch):
    """L'importazione ferma i servizi prima di partire: se fallisce, «Riavvia RT» deve funzionare."""
    from rt import window
    calls = {}

    def fake_stream(_window, args, tipo, *, before_start=None, on_success=None, on_failure=None):
        calls.update(tipo=tipo, on_success=on_success, on_failure=on_failure)
        return True

    monkeypatch.setattr(window, "_stream_backup", fake_stream)
    monkeypatch.setattr(window, "_chosen_file", lambda _w: "/tmp/collezione.zip")
    from rt.services import backup_service as bs
    monkeypatch.setattr(bs, "inspect_backup_zip", lambda _p: {"segreti": False, "created": "2026-11-01T10:00:00"})

    class FakeWindow:
        def create_confirmation_dialog(self, *_a):
            return True

    window._import_collection(FakeWindow(), "http://127.0.0.1:8765")
    assert calls["tipo"] == "importa" and calls["on_failure"] is not None
    monkeypatch.setattr(window, "_import_ready", False)
    calls["on_failure"]()
    assert window._import_ready is True
