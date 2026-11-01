"""Server MCP di scripts/rt_mcp.py: protezioni, protocollo, log ed export prima di eliminare."""
import importlib.util
import json
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "rt_mcp.py")
_spec = importlib.util.spec_from_file_location("rt_mcp", _PATH)
rt_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt_mcp)


@pytest.mark.parametrize("method,path", [
    ("POST", "/system/quit"), ("POST", "/api/v1/system/update"), ("POST", "system/update/install"),
    ("POST", "/settings/telegram/reveal"), ("POST", "/system/choose-folder"), ("DELETE", "/auth/session"),
])
def test_always_blocked(method, path):
    assert "bloccato" in rt_mcp.check_policy(method, path, True, "full")


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/lessons/3"), ("POST", "/lessons/3/media/delete"), ("POST", "/lessons/3/update"),
    ("PATCH", "/lessons/3/metadata"), ("PUT", "/secrets/OPENAI_API_KEY"), ("POST", "/system/compact-audio"),
])
def test_destructive_needs_confirm(method, path):
    assert "confirm=true" in rt_mcp.check_policy(method, path, False, "full")
    assert rt_mcp.check_policy(method, path, True, "full") is None


def test_normal_calls_and_readonly_mode():
    assert rt_mcp.check_policy("GET", "/lessons", False, "full") is None
    assert rt_mcp.check_policy("POST", "/lessons/3/jobs", False, "full") is None
    assert rt_mcp.check_policy("GET", "/lessons?limit=5", False, "readonly") is None
    assert "sola lettura" in rt_mcp.check_policy("POST", "/lessons/3/jobs", False, "readonly")


def test_api_path_normalization():
    assert rt_mcp._api_path("lessons") == "/lessons"
    assert rt_mcp._api_path("/api/v1/lessons/2") == "/lessons/2"
    assert rt_mcp._api_path("/api/v1") == "/"


class FakeClient:
    base = "http://127.0.0.1:1"

    def __init__(self):
        self.calls = []
        self.export_status = 200

    def request(self, method, path, query=None, body=None, timeout=120):
        self.calls.append((method, path, query))
        if path.endswith("/export"):
            return self.export_status, {"Content-Disposition": "attachment; filename*=UTF-8''Lezione%20prova.zip"}, b"PK zip"
        return 200, {"Content-Type": "application/json"}, json.dumps({"ok": True}).encode()

    def auth_mode(self):
        return "token"


def test_delete_lesson_exports_first(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    client = FakeClient()
    tools = rt_mcp.Tools(client, "full")
    assert tools.call("rt_request", {"method": "DELETE", "path": "/lessons/7"}).startswith("RIFIUTATO")
    assert client.calls == []
    out = tools.call("rt_request", {"method": "DELETE", "path": "/lessons/7", "confirm": True})
    assert [c[0] for c in client.calls] == ["GET", "DELETE"]
    assert "Esportata la lezione 7" in out and "HTTP 200" in out
    saved = os.listdir(tmp_path / "mcp" / "exports")
    assert len(saved) == 1 and saved[0].endswith("Lezione prova.zip")


def test_delete_lesson_aborted_when_export_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    client = FakeClient()
    client.export_status = 404
    out = rt_mcp.Tools(client, "full").call("rt_request", {"method": "DELETE", "path": "/lessons/7", "confirm": True})
    assert "non eliminata" in out
    assert [c[0] for c in client.calls] == ["GET"]


def test_logs_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "worker.log").write_text(
        "2026-11-01 10:00:00.000 job a avviato\n2026-11-01 11:00:00.000 job b avviato\n"
        "2026-11-01 11:05:00.000 job b fallito\n", encoding="utf-8")
    out = rt_mcp.read_logs("worker", 10, since="2026-11-01 11")
    assert "job a" not in out and "job b avviato" in out
    assert "avviato" not in rt_mcp.read_logs("worker", 10, contains="FALLITO")
    assert "assente" in rt_mcp.read_logs("api")
    assert "sconosciuto" in rt_mcp.read_logs("nope")


def test_protocol_handshake_and_tools():
    tools = rt_mcp.Tools(FakeClient(), "full")
    init = rt_mcp.handle(tools, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-03-26"}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert rt_mcp.handle(tools, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = rt_mcp.handle(tools, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in listed}
    assert {"rt_status", "rt_request", "rt_upload", "rt_wait_job", "rt_logs", "rt_browser_login"} <= names
    bad = rt_mcp.handle(tools, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}})
    assert bad["result"]["isError"] is True
    assert rt_mcp.handle(tools, {"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"] == -32601
