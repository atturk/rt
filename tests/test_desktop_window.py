"""Finestra, avvio senza console e uscita dell'app, senza aprire finestre nei test."""
import argparse
import json
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from rt import desktop, window
from rt.api import auth, launcher
from rt.services import service_manager as sm


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def webview(monkeypatch):
    fake = ModuleType("webview")
    fake.settings = {}
    fake_window = Mock()
    fake_window.events = SimpleNamespace(loaded=Event(), shown=Event(), initialized=Event())
    fake.create_window = Mock(return_value=fake_window)
    fake.start = Mock()
    menu = ModuleType("webview.menu")

    class Menu:
        def __init__(self, title, items):
            self.title, self.items = title, items

    class MenuAction:
        def __init__(self, title, function):
            self.title, self.function = title, function

    menu.Menu, menu.MenuAction, menu.MenuSeparator = Menu, MenuAction, type("MenuSeparator", (), {})
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setitem(sys.modules, "webview.menu", menu)
    return fake


class Event:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self

    def is_set(self):
        return False


@pytest.mark.parametrize("reason", ["source", "disabled", "linux", "import"])
def test_available_falls_back(data, monkeypatch, webview, reason):
    monkeypatch.setattr(window.bundle, "kind", lambda: None if reason == "source" else "windows")
    monkeypatch.setattr(sys, "platform", "linux" if reason == "linux" else "win32")
    if reason == "disabled":
        monkeypatch.setenv("RT_NO_WINDOW", "1")
    if reason == "import":
        monkeypatch.setattr(window.importlib, "import_module", Mock(side_effect=ImportError("manca webview")))
    assert not window.available()
    assert (data / "logs" / "desktop.log").is_file()


def mac_ready(monkeypatch):
    monkeypatch.setattr(sm, "installed", lambda: ["api", "worker", "bot"])
    monkeypatch.setattr(sm, "api_is_up", lambda port: True)
    monkeypatch.setattr(desktop, "_services_match_app", lambda: True)
    monkeypatch.setattr(desktop, "_service_port", lambda: 8765)
    monkeypatch.setattr(desktop, "_wait_for_api", lambda port: True)


@pytest.mark.parametrize("browser, show, expected", [(False, True, "window"), (True, True, "browser"),
                                                    (False, False, "none")])
def test_macos_window_or_browser(monkeypatch, browser, show, expected):
    mac_ready(monkeypatch)
    opened = Mock(return_value=0)
    spa = Mock(return_value=0)
    monkeypatch.setattr(window, "available", lambda: True)
    monkeypatch.setattr(window, "open_window", opened)
    monkeypatch.setattr(launcher, "run_spa", spa)
    assert desktop.run_macos(8765, show, lambda s: None, browser=browser) == 0
    assert opened.call_count == (expected == "window")
    assert spa.call_count == (expected != "window")
    if expected != "window":
        assert spa.call_args.kwargs["open_browser"] is (expected == "browser")


def test_macos_starts_installed_but_stopped_services(monkeypatch):
    mac_ready(monkeypatch)
    start = Mock()
    monkeypatch.setattr(sm, "api_is_up", lambda port: False)
    monkeypatch.setattr(sm, "start", start)
    monkeypatch.setattr(launcher, "run_spa", Mock(return_value=0))
    assert desktop.run_macos(8765, False, lambda s: None) == 0
    start.assert_called_once_with()


@pytest.mark.parametrize("running", [False, True])
def test_windows_detaches_pythonw(data, monkeypatch, running):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sm, "api_is_up", lambda port: running)
    monkeypatch.setattr(desktop, "_wait_for_api", lambda port: True)
    monkeypatch.setattr(desktop.os.path, "isfile", lambda p: True)
    popen = Mock(return_value=SimpleNamespace(pid=1234))
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    assert desktop.run_windows(8765, False, lambda s: None) == 0
    assert popen.call_count == (not running)
    if not running:
        command = popen.call_args.args[0]
        assert command[0].endswith("pythonw.exe")
        assert command[-4:] == ["desktop", "--serve", "--port", "8765"]
        assert popen.call_args.kwargs["creationflags"] == 0x08000000 | 0x8 | 0x200
        assert popen.call_args.kwargs["stdin"] == desktop.subprocess.DEVNULL
        assert (data / "run" / "server.pid").read_text().strip() == "1234"


def test_internal_serve_cleans_pid(data, monkeypatch):
    spa = Mock(return_value=0)
    monkeypatch.setattr(launcher, "run_spa", spa)
    assert desktop._serve(8765) == 0
    assert spa.call_args.kwargs["open_browser"] is False
    assert not (data / "run" / "server.pid").exists()


@pytest.mark.parametrize("flags, show, browser, serve", [
    ([], True, False, False), (["--browser"], True, True, False),
    (["--no-browser"], False, False, False), (["--after-update"], True, False, False),
    (["--serve"], True, False, True),
])
def test_desktop_options(monkeypatch, flags, show, browser, serve):
    parser = argparse.ArgumentParser()
    desktop.configure_parser(parser)
    run = Mock(return_value=0)
    monkeypatch.setattr(desktop, "run", run)
    desktop.cmd_desktop(parser.parse_args(flags))
    run.assert_called_once_with(port=None, open_browser=show, browser=browser, serve=serve)
    assert "--serve" not in parser.format_help()


def test_window_settings_session_menu_and_pid(data, monkeypatch, webview):
    monkeypatch.setattr(auth, "create_login_code", lambda: "monouso")
    monkeypatch.setattr(sys, "platform", "linux")  # il backend è simulato, niente librerie native
    opened = Mock()
    monkeypatch.setattr(window.webbrowser, "open", opened)

    def start(**kwargs):
        assert (data / "run" / "window.pid").read_text().strip() == str(os.getpid())
        assert kwargs["private_mode"] is False
        assert kwargs["storage_path"] == str(data / "webview")
        items = kwargs["menu"][0].items
        assert [x.title for x in items if hasattr(x, "title")] == [
            "Controlla aggiornamenti…", "Apri cartella dati", "Mostra registri", "Backup…",
            "Diagnostica", "Apri nel browser", "Ricarica", "Esci da RT"]
    webview.start.side_effect = start
    assert window.open_window("http://127.0.0.1:8765") == 0
    assert "code=monouso" in webview.create_window.call_args.args[1]
    assert webview.settings == {"ALLOW_DOWNLOADS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True,
                               "OPEN_DEVTOOLS_IN_DEBUG": False}
    assert not (data / "run" / "window.pid").exists()
    opened.assert_not_called()


def test_failed_webview_uses_browser_and_logs(data, monkeypatch, webview):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(auth, "create_login_code", Mock(side_effect=["primo", "nuovo"]))
    webview.start.side_effect = RuntimeError("WebView2 assente")
    opened = Mock()
    monkeypatch.setattr(window.webbrowser, "open", opened)
    assert window.open_window("http://127.0.0.1:8765") == 0
    opened.assert_called_once_with("http://127.0.0.1:8765/login?code=nuovo")
    assert "WebView2 assente" in (data / "logs" / "desktop.log").read_text()
    assert not (data / "run" / "window.pid").exists()


def test_existing_windows_window_is_activated(data, monkeypatch, webview):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(auth, "create_login_code", lambda: "code")
    monkeypatch.setattr(window, "_activate_existing", lambda: True)
    assert window.open_window("http://127.0.0.1:8765") == 0
    webview.create_window.assert_not_called()
    webview.start.assert_not_called()


@pytest.mark.parametrize("host,status", [("192.168.1.20", 403), ("127.0.0.1", 204), ("::1", 204)])
def test_quit_requires_loopback(api_token, host, status):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    app = create_app()
    server = app.state.uvicorn_server = SimpleNamespace(should_exit=False)
    client = TestClient(app, client=(host, 1234), headers={"Authorization": f"Bearer {api_token}"})
    assert client.post("/api/v1/system/quit").status_code == status
    assert server.should_exit is (status == 204)


def test_quit_requires_authentication(api_token):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    app = create_app()
    server = app.state.uvicorn_server = SimpleNamespace(should_exit=False)
    assert TestClient(app, client=("127.0.0.1", 1234)).post("/api/v1/system/quit").status_code == 401
    assert not server.should_exit


def test_quit_rejects_forwarded_remote_user(api_token):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    app = create_app()
    app.state.uvicorn_server = SimpleNamespace(should_exit=False)
    client = TestClient(app, client=("127.0.0.1", 1234), headers={"Authorization": f"Bearer {api_token}"})
    assert client.post("/api/v1/system/quit", headers={"X-Forwarded-For": "100.64.0.2"}).status_code == 403


def test_window_smoke_does_not_hide_failure(data, monkeypatch, webview):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("RT_WINDOW_SMOKE", "1")
    monkeypatch.setattr(auth, "create_login_code", lambda: "code")
    webview.start.side_effect = RuntimeError("motore non disponibile")
    opened = Mock()
    monkeypatch.setattr(window.webbrowser, "open", opened)
    assert window.open_window("http://127.0.0.1:8765") == 1
    opened.assert_not_called()


def test_smoke_reads_the_native_page(data, monkeypatch):
    monkeypatch.setattr("rt._window_smoke.downloads", lambda window: ["lezione.zip", "nota.md", "domande.json"])
    fake = Mock()
    fake.evaluate_js.side_effect = ["RT", True]
    fake.get_current_url.return_value = "http://127.0.0.1:8765/"
    window._smoke(fake)
    result = json.loads((data / "logs" / "window-smoke.json").read_text())
    assert result["page"] == "RT" and result["authenticated"] is True
    fake.destroy.assert_called_once()


@pytest.mark.parametrize('owner,expected', [(1234, True), (9876, False)])
def test_activate_existing_checks_window_owner(data, monkeypatch, owner, expected):
    (data / 'run').mkdir()
    (data / 'run' / 'window.pid').write_text('1234\n')
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(window, '_pid_alive', lambda pid: pid == 1234)
    user = SimpleNamespace(FindWindowW=Mock(return_value=99),
                           GetWindowThreadProcessId=Mock(side_effect=lambda hwnd, ptr: setattr(ptr._obj, 'value', owner)),
                           ShowWindow=Mock(), SetForegroundWindow=Mock())
    monkeypatch.setattr(window.ctypes, 'windll', SimpleNamespace(user32=user), raising=False)
    assert window._activate_existing() is expected
    assert user.SetForegroundWindow.call_count == expected
    if expected:
        user.ShowWindow.assert_called_once_with(99, 9)


def test_windows_quit_falls_back_to_taskkill(data, rt_db, monkeypatch):
    (data / 'run').mkdir()
    (data / 'run' / 'server.pid').write_text('1234\n')
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(window, '_pid_alive', lambda pid: True)
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', Mock(side_effect=OSError('API non risponde')))
    monkeypatch.setattr(desktop.time, 'monotonic', Mock(side_effect=[0, 16]))
    run = Mock()
    monkeypatch.setattr(desktop.subprocess, 'run', run)
    desktop.stop_background('http://127.0.0.1:8765')
    assert run.call_args.args[0] == ['taskkill', '/PID', '1234', '/T', '/F']
    assert run.call_args.kwargs['creationflags'] == 0x08000000


def test_mac_quit_stops_services(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    stop = Mock()
    monkeypatch.setattr(sm, 'stop', stop)
    desktop.stop_background('http://127.0.0.1:8765')
    stop.assert_called_once_with()


def test_launcher_stops_worker_on_server_failure(monkeypatch):
    import uvicorn
    from rt.api import app as api_app, server, spa
    fake_app = SimpleNamespace(state=SimpleNamespace())
    fake_server = SimpleNamespace(should_exit=False, run=Mock(side_effect=RuntimeError('stop')))
    monkeypatch.setattr(launcher, '_already_running', lambda port: False)
    monkeypatch.setattr(launcher, '_legacy_layout_hint', lambda say: None)
    monkeypatch.setattr(launcher, 'worker_concurrency', lambda: 2)
    monkeypatch.setattr(server, 'prepare', lambda **kwargs: True)
    monkeypatch.setattr(spa, 'find_spa_dir', lambda: 'spa')
    monkeypatch.setattr(auth, 'create_login_code', lambda: 'code')
    monkeypatch.setattr(api_app, 'create_app', lambda **kwargs: fake_app)
    monkeypatch.setattr(uvicorn, 'Config', Mock())
    monkeypatch.setattr(uvicorn, 'Server', lambda config: fake_server)
    monkeypatch.setattr(launcher.threading, 'Thread', Mock())
    child = Mock(pid=12)
    child.poll.return_value = None
    monkeypatch.setattr(launcher.subprocess, 'Popen', Mock(return_value=child))
    with pytest.raises(RuntimeError, match='stop'):
        launcher.run_spa(open_browser=False, say=lambda message: None)
    assert fake_app.state.uvicorn_server is fake_server
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=15)


def test_native_download_fixture_can_be_exported(data, rt_db, api_client):
    import io
    import zipfile
    from rt._window_smoke import _lesson
    lesson_id = _lesson()
    response = api_client.get(f'/api/v1/lessons/{lesson_id}/export?format=zip&scope=all')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert any(name.endswith('/rielaborato.md') for name in archive.namelist())


def test_windows_missing_webview2_uses_browser(data, webview, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(auth, 'create_login_code', lambda: 'code')
    monkeypatch.setattr(window, '_activate_existing', lambda: False)
    monkeypatch.setattr(window.ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=Mock())), raising=False)
    def start(**kwargs):
        fake = webview.create_window.return_value
        assert fake.events.initialized.callbacks[0]('mshtml') is False
    webview.start.side_effect = start
    opened = Mock()
    monkeypatch.setattr(window.webbrowser, 'open', opened)
    assert window.open_window('http://127.0.0.1:8765') == 0
    opened.assert_called_once()
    assert 'WebView2 Runtime non disponibile' in (data / 'logs' / 'desktop.log').read_text()
