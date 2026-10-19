"""Microfono nella finestra dell'app: decisione, voce di menu e richiamo dei permessi."""
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
    titles = [getattr(item, "title", None) for item in window._menu(webview.create_window.return_value, "http://127.0.0.1:8765")[0].items]
    assert ("Controlla permessi" in titles) is listed


@pytest.mark.parametrize("status,opened,message", [
    ("authorized", None, "Microfono consentito."),
    ("denied", wp.MAC_SETTINGS, "Attiva RT in Microfono, poi riapri RT."),
])
def test_check_on_mac(monkeypatch, status, opened, message):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wp, "mic_status", lambda: status)
    notice, open_path, win = Mock(), Mock(), Mock()
    wp.check(win, notice, open_path)
    notice.assert_called_once_with(win, message)
    assert (open_path.call_args.args[0] if open_path.called else None) == opened


def test_check_asks_again_when_undetermined(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wp, "mic_status", lambda: "undetermined")
    monkeypatch.setattr(wp, "request_mic", lambda callback: callback(True))
    notice, win = Mock(), Mock()
    wp.check(win, notice, Mock())
    notice.assert_called_once_with(win, "Microfono consentito.")
    win.evaluate_js.assert_called_once_with("location.reload()")


def test_check_on_windows_opens_settings(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    notice, open_path = Mock(), Mock()
    wp.check(Mock(), notice, open_path)
    open_path.assert_called_once_with(wp.WINDOWS_SETTINGS)
