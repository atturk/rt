"""Permessi nella finestra dell'app: microfono, controllo permessi su /permessi e whitelist impostazioni."""
import sys
from unittest.mock import Mock

import pytest

from rt import window, window_permissions as wp
from tests.test_desktop_window import webview  # noqa: F401  (fixture)


@pytest.mark.parametrize("host,status,expected,asked", [
    ("127.0.0.1", "authorized", wp.GRANT, False),
    ("localhost", "denied", wp.DENY, False),
    ("127.0.0.1", "undetermined", None, True),
    ("example.com", "authorized", wp.DENY, False),
])
def test_decide(host, status, expected, asked):
    ask = Mock()
    assert wp.decide(host, status, ask) == expected
    assert ask.called is asked


@pytest.mark.parametrize("platform,listed", [("darwin", True), ("win32", True), ("linux", False)])
def test_menu_has_check_permissions(monkeypatch, webview, platform, listed):  # noqa: F811
    monkeypatch.setattr(sys, "platform", platform)
    items = window._menu(webview.create_window.return_value, "http://127.0.0.1:8765")[0].items
    item = next((i for i in items if getattr(i, "title", None) == "Controlla permessi"), None)
    assert (item is not None) is listed
    if item is not None:
        item.function()
        webview.create_window.return_value.evaluate_js  # window exists
        webview.create_window.return_value.load_url.assert_called_with("http://127.0.0.1:8765/permessi")


def test_check_loads_permissions_page():
    win = Mock()
    wp.check(win, "http://127.0.0.1:8765")
    win.load_url.assert_called_once_with("http://127.0.0.1:8765/permessi")


def test_open_system_settings_whitelist(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(wp.subprocess, "Popen", popen)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert wp.open_system_settings("microfono") == {"ok": True}
    popen.assert_called_with(["open", wp.MAC_SETTINGS])
    assert wp.open_system_settings("elementi_background") == {"ok": True}
    popen.assert_called_with(["open", wp.MAC_SETTINGS_BACKGROUND])

    # Chiavi arbitrarie o URL non in whitelist vengono rifiutate
    bad = wp.open_system_settings("https://evil.example")
    assert bad["ok"] is False
    bad_win_only = wp.open_system_settings("firewall")
    assert bad_win_only["ok"] is False

    # Windows
    monkeypatch.setattr(sys, "platform", "win32")
    started = []
    monkeypatch.setattr(wp.os, "startfile", lambda target: started.append(target), raising=False)
    assert wp.open_system_settings("firewall") == {"ok": True}
    assert started == [wp.WINDOWS_SETTINGS_FIREWALL]


def test_request_mic_sync_and_desktop_api(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wp, "mic_status", lambda: "undetermined")
    monkeypatch.setattr(wp, "request_mic", lambda callback: callback(True))
    api = window.DesktopApi(Mock(), base_url="http://127.0.0.1:8765")
    assert api.stato_microfono() == "undetermined"
    assert api.richiedi_microfono() == {"status": "authorized"}


def test_permissions_status_non_blocking(tmp_path, monkeypatch):
    from rt import desktop
    from rt.core import lan, materials
    from rt.services import service_manager as sm

    desktop_dir = tmp_path / "Desktop" / "Lezioni"
    desktop_dir.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wp.os.path, "expanduser", lambda p: str(tmp_path / p[2:]) if p.startswith("~/") else p)
    monkeypatch.setattr(desktop, "_lessons_root", lambda: str(desktop_dir))
    monkeypatch.setattr(wp.os, "listdir", Mock(side_effect=PermissionError("denied")))
    monkeypatch.setattr(wp, "mic_status", lambda: "authorized")
    monkeypatch.setattr(materials, "_soffice", lambda: None)
    monkeypatch.setattr(sm, "background_disabled", lambda: True)
    monkeypatch.setattr(lan, "lan_enabled", lambda: True)
    alert_mock = Mock(side_effect=AssertionError("non deve mostrare alert"))
    monkeypatch.setattr(desktop, "_permission_alert", alert_mock)

    res = wp.permissions_status()
    assert res["platform"] == "darwin"
    assert res["microfono"] == "authorized"
    assert res["file_e_cartelle"]["rilevante"] is True
    assert res["file_e_cartelle"]["stato"] == "denied"
    assert res["automazione_keynote"]["rilevante"] is True
    assert res["elementi_background"]["stato"] == "denied"
    assert res["rete_locale"]["attivo"] is True
