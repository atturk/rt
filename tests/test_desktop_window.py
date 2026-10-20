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
    fake.FileDialog = SimpleNamespace(OPEN=10, FOLDER=20, SAVE=30)
    fake_window = Mock()
    fake_window.events = SimpleNamespace(loaded=Event(), shown=Event(), initialized=Event(), closed=Event())
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
            "Diagnostica", "Apri nel browser", "Ricarica",
            "Ingrandisci", "Riduci", "Dimensioni reali", "Esci da RT"]
        items[0].function()
        webview.create_window.assert_called_with(
            "Aggiornamento di RT", "http://127.0.0.1:8765/app/aggiornamento",
            width=420, height=240, resizable=False, on_top=True)
        # Azioni di zoom
        zoom_in = next(x for x in items if getattr(x, "title", None) == "Ingrandisci")
        zoom_in.function()
        webview.create_window.return_value.evaluate_js.assert_called_with("window.rtZoom && window.rtZoom('in')")
    webview.start.side_effect = start
    assert window.open_window("http://127.0.0.1:8765") == 0
    assert "code=monouso&app=1" in webview.create_window.call_args_list[0].args[1]
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
    login = Mock(side_effect=AssertionError("Non deve creare un altro codice"))
    monkeypatch.setattr(auth, "create_login_code", login)
    monkeypatch.setattr(window, "_activate_existing", lambda: True)
    assert window.open_window("http://127.0.0.1:8765") == 0
    webview.create_window.assert_not_called()
    webview.start.assert_not_called()
    login.assert_not_called()


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
    monkeypatch.setattr("rt._window_smoke.macos_menu", lambda: ["Esci da RT", "Modifica"])
    fake = Mock()
    fake.evaluate_js.side_effect = ["RT", True]
    fake.get_current_url.return_value = "http://127.0.0.1:8765/"
    window._smoke(fake)
    result = json.loads((data / "logs" / "window-smoke.json").read_text())
    assert result["page"] == "RT" and result["authenticated"] is True
    fake.destroy.assert_called_once()


@pytest.mark.parametrize('owner,expected', [(1234, True), (9876, False)])
def test_activate_existing_checks_window_owner(data, monkeypatch, owner, expected):
    (data / 'run').mkdir(exist_ok=True)
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
    (data / 'run').mkdir(exist_ok=True)
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


def test_windows_maintenance_command_has_no_console(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='diagnostica', stderr=''))
    monkeypatch.setattr(window.subprocess, 'run', run)
    window._command('doctor')
    assert run.call_args.args[0][-1] == 'doctor'
    assert run.call_args.kwargs['capture_output'] is True
    assert run.call_args.kwargs['creationflags'] == 0x08000000


def test_pythonw_error_shows_native_alert_without_stdin(data, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'stdin', None)
    message = Mock()
    monkeypatch.setattr(window.ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(MessageBoxW=message)), raising=False)
    monkeypatch.setattr(desktop, 'run', Mock(side_effect=RuntimeError('errore di prova')))
    ask = Mock(side_effect=AssertionError('Non deve chiedere Invio'))
    monkeypatch.setattr('builtins.input', ask)
    parser = argparse.ArgumentParser()
    desktop.configure_parser(parser)
    with pytest.raises(SystemExit) as exc:
        desktop.cmd_desktop(parser.parse_args([]))
    assert exc.value.code == 1
    message.assert_called_once_with(None, 'RT non si è avviato: errore di prova', 'RT', 0x10)
    assert 'errore di prova' in (data / 'logs' / 'desktop.log').read_text()
    ask.assert_not_called()


def test_two_windows_launches_start_only_one_server(data, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(desktop.os.path, 'isfile', lambda path: True)
    running = threading.Event()
    monkeypatch.setattr(sm, 'api_is_up', lambda port: running.is_set())
    monkeypatch.setattr(sm, 'choose_port', lambda say: 8765)
    monkeypatch.setattr(desktop, '_wait_for_api', lambda port: running.is_set())
    calls = []
    def popen(*args, **kwargs):
        time.sleep(0.1)
        calls.append(args[0])
        running.set()
        return SimpleNamespace(pid=1234)
    monkeypatch.setattr(desktop.subprocess, 'Popen', popen)
    results, errors = [], []
    barrier = threading.Barrier(2)
    def launch():
        try:
            barrier.wait(timeout=5)
            results.append(desktop.run_windows(None, False, lambda message: None))
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=launch) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors and results == [0, 0]
    assert len(calls) == 1


def test_windows_start_lock_is_released_before_window(data, monkeypatch):
    from rt.core.portable import lock_file
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sm, 'api_is_up', lambda port: True)
    monkeypatch.setattr(desktop, '_wait_for_api', lambda port: True)
    monkeypatch.setattr(window, 'available', lambda: True)
    def opened(base):
        with open(data / 'run' / 'server-start.lock', 'a+b') as lock:
            assert lock_file(lock, blocking=False)
        return 0
    monkeypatch.setattr(window, 'open_window', opened)
    assert desktop.run_windows(8765, True, lambda message: None) == 0


def test_mac_cmd_q_replaces_localized_default_quit(monkeypatch):
    class Item:
        def __init__(self, key, target):
            self.key, self.owner = key, target
        def title(self):
            return 'Esci da RT'
        def keyEquivalent(self):
            return self.key
        def target(self):
            return self.owner
        def setKeyEquivalent_(self, value):
            self.key = value
    custom, default = Item('', object()), Item('q', None)
    items = [custom, default]
    app_menu = SimpleNamespace(itemArray=lambda: items, removeItem_=items.remove)
    main = SimpleNamespace(itemAtIndex_=lambda index: SimpleNamespace(submenu=lambda: app_menu))
    appkit = ModuleType('AppKit')
    appkit.NSApplication = SimpleNamespace(sharedApplication=lambda: SimpleNamespace(mainMenu=lambda: main))
    objc_tools = ModuleType('PyObjCTools')
    objc_tools.AppHelper = SimpleNamespace(callAfter=lambda callback: callback())
    monkeypatch.setitem(sys.modules, 'AppKit', appkit)
    monkeypatch.setitem(sys.modules, 'PyObjCTools', objc_tools)
    window._macos_menu()
    assert items == [custom]
    assert custom.key == 'q' and custom.target() is not None


def test_mac_smoke_reads_the_submenu_title(monkeypatch):
    from rt._window_smoke import macos_menu
    about_item = SimpleNamespace(title=lambda: 'Informazioni su RT', target=lambda: object(), keyEquivalent=lambda: '')
    exit_item = SimpleNamespace(title=lambda: 'Esci da RT', target=lambda: object(), keyEquivalent=lambda: 'q')
    app_menu = SimpleNamespace(title=lambda: 'RT', itemArray=lambda: [about_item, exit_item])
    roots = [SimpleNamespace(title=lambda: '', submenu=lambda: app_menu),
             SimpleNamespace(title=lambda: '', submenu=lambda: SimpleNamespace(title=lambda: 'Modifica'))]
    main = SimpleNamespace(itemArray=lambda: roots, itemAtIndex_=lambda index: roots[index])
    appkit = ModuleType('AppKit')
    appkit.NSApplication = SimpleNamespace(sharedApplication=lambda: SimpleNamespace(mainMenu=lambda: main))
    objc_tools = ModuleType('PyObjCTools')
    objc_tools.AppHelper = SimpleNamespace(callAfter=lambda callback: callback())
    monkeypatch.setitem(sys.modules, 'AppKit', appkit)
    monkeypatch.setitem(sys.modules, 'PyObjCTools', objc_tools)
    assert macos_menu() == ['Esci da RT', 'Modifica']


def test_about_options():
    # Con run e commit
    info = {
        "version": "4.3.2b1",
        "run": "812",
        "commit": "a1b2c3d",
        "built_at": "2026-10-19T12:00:00Z",
    }
    versions = {
        "channel": "beta",
        "python": "3.12.3",
        "webview": "6.2.1",
        "macos": "15.1",
        "arch": "arm64",
    }
    opts = window.about_options(info, versions)
    assert opts["ApplicationName"] == "RT"
    assert opts["ApplicationVersion"] == "4.3.2b1"
    assert opts["Version"] == "build 812 · a1b2c3d"
    assert "Canale aggiornamenti: beta" in opts["credits_lines"]
    assert "Compilata il 19/10/2026" in opts["credits_lines"]
    assert "Python 3.12.3 · pywebview 6.2.1" in opts["credits_lines"]
    assert "macOS 15.1 · arm64" in opts["credits_lines"]

    # Senza run (solo commit)
    opts_commit_only = window.about_options({"version": "4.3.2b1", "commit": "a1b2c3d"}, versions)
    assert opts_commit_only["Version"] == "a1b2c3d"

    # Senza né run né commit: chiave Version omessa
    opts_no_build = window.about_options({"version": "4.3.2b1"}, versions)
    assert "Version" not in opts_no_build


def test_windows_menu_has_about(monkeypatch, webview):
    monkeypatch.setattr(sys, "platform", "win32")
    menu = window._menu(webview.create_window.return_value, "http://127.0.0.1:8765")
    items = menu[0].items
    assert items[0].title == "Informazioni su RT"


def test_backup_stream_events_in_order(monkeypatch):
    import io
    import time
    fake_window = Mock()
    fake_window.evaluate_js = Mock(return_value=True)

    lines = [
        json.dumps({"fase": "database", "fatto": 0, "totale": 1}) + "\n",
        json.dumps({"fase": "media", "fatto": 1, "totale": 1}) + "\n",
        json.dumps({"fine": True, "percorso": "/backups/rt-backup-1", "riepilogo": ["ok"]}) + "\n",
    ]

    class FakeStdout:
        def __init__(self, items):
            self.items = list(items)
        def readline(self):
            if not self.items:
                return ""
            item = self.items.pop(0)
            time.sleep(0.12)  # simula intervallo > 0.1s tra eventi
            return item

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = FakeStdout(lines)
            self.returncode = 0
        def wait(self):
            return 0

    monkeypatch.setattr(window.subprocess, "Popen", FakeProc)
    window._stream_backup(fake_window, ["backup", "--progress-json"], tipo="backup")
    time.sleep(0.5)

    calls = [c.args[0] for c in fake_window.evaluate_js.call_args_list]
    # Inizio, database, media, fine
    assert any("inizio" in c for c in calls)
    assert any("database" in c for c in calls)
    assert any("fine" in c and "rt-backup-1" in c for c in calls)


def test_backup_stream_reports_error(monkeypatch):
    import io
    import time
    fake_window = Mock()
    fake_window.evaluate_js = Mock(return_value=True)

    stdout_stream = io.StringIO(json.dumps({"errore": "errore disco"}) + "\n")

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = stdout_stream
            self.returncode = 1
        def wait(self):
            return 1

    monkeypatch.setattr(window.subprocess, "Popen", FakeProc)
    window._stream_backup(fake_window, ["backup", "--progress-json"], tipo="backup")
    time.sleep(0.3)

    calls = [c.args[0] for c in fake_window.evaluate_js.call_args_list]
    assert any("errore disco" in c for c in calls)


def test_backup_stream_fallback_notice_without_handler(monkeypatch):
    import io
    import time
    fake_window = Mock()
    fake_window.evaluate_js = Mock(return_value=False)
    notice = Mock()
    monkeypatch.setattr(window, "_notice", notice)

    lines = [
        json.dumps({"fine": True, "percorso": "/backups/b1", "riepilogo": ["linea 1", "linea 2"]}) + "\n",
    ]
    stdout_stream = io.StringIO("".join(lines))

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = stdout_stream
            self.returncode = 0
        def wait(self):
            return 0

    monkeypatch.setattr(window.subprocess, "Popen", FakeProc)
    window._stream_backup(fake_window, ["backup", "--progress-json"], tipo="backup")
    time.sleep(0.3)

    notice.assert_called_once_with(fake_window, "linea 1\nlinea 2")


def test_desktop_api_salva_copia_backup_rejects_foreign_path(data, webview):
    fake_window = Mock()
    api = window.DesktopApi(fake_window)
    res = api.salva_copia_backup("/tmp/non-rt-backup")
    assert res == {"errore": "Percorso snapshot non valido."}
    assert fake_window.create_file_dialog.call_count == 0


def test_desktop_api_salva_copia_backup_cancellation(data, monkeypatch, webview):
    backup_dir = data / "backups" / "rt-backup-20261019-120000"
    backup_dir.mkdir(parents=True)
    fake_window = Mock()
    fake_window.create_file_dialog = Mock(return_value=None)
    stream = Mock()
    monkeypatch.setattr(window, "_stream_backup", stream)

    api = window.DesktopApi(fake_window)
    res = api.salva_copia_backup(str(backup_dir))
    assert res == {"annullato": True}
    assert stream.call_count == 0


def test_desktop_api_salva_copia_backup_starts_stream(data, monkeypatch, webview):
    backup_dir = data / "backups" / "rt-backup-20261019-120000"
    backup_dir.mkdir(parents=True)
    fake_window = Mock()
    fake_window.create_file_dialog = Mock(return_value=["/chiavetta/copia"])
    stream = Mock()
    monkeypatch.setattr(window, "_stream_backup", stream)

    api = window.DesktopApi(fake_window)
    res = api.salva_copia_backup(str(backup_dir))
    assert res == {"avviato": True}
    assert stream.call_count == 1
    args, kwargs = stream.call_args
    assert kwargs.get("tipo") == "copia"
    assert "/chiavetta/copia.zip" in args[1]


def test_desktop_api_apri_aggiornamento_creates_single_window(webview):
    popup = Mock()
    popup.events = SimpleNamespace(closed=Event())
    popup.show = Mock()
    webview.create_window.return_value = popup

    api = window.DesktopApi(Mock(), base_url="http://127.0.0.1:8765")
    win1 = api.apri_aggiornamento()
    assert win1 is popup
    assert webview.create_window.call_count == 1
    assert webview.create_window.call_args.args[0] == "Aggiornamento di RT"
    assert webview.create_window.call_args.args[1] == "http://127.0.0.1:8765/app/aggiornamento"
    assert webview.create_window.call_args.kwargs == {"width": 420, "height": 240, "resizable": False, "on_top": True}

    # Seconda chiamata: non crea un'altra finestra, chiama show()
    win2 = api.apri_aggiornamento()
    assert win2 is popup
    assert webview.create_window.call_count == 1
    popup.show.assert_called_once()

    # Chiusura della finestra: azzera il riferimento
    for cb in popup.events.closed.callbacks:
        cb()
    win3 = api.apri_aggiornamento()
    assert webview.create_window.call_count == 2


def test_menu_calls_apri_aggiornamento(webview):
    api = Mock()
    menu = window._menu(webview.create_window.return_value, "http://127.0.0.1:8765", api=api)
    item = next(x for x in menu[0].items if getattr(x, "title", None) == "Controlla aggiornamenti…")
    item.function()
    api.apri_aggiornamento.assert_called_once()


def test_desktop_open_argument_registers_and_activates_existing(data, monkeypatch):
    test_file = data / "test.pdf"
    test_file.write_text("dummy")

    registered = []
    from rt.core import opened_files
    orig_reg = opened_files.register_file

    def fake_reg(p):
        registered.append(p)
        return orig_reg(p)
    monkeypatch.setattr(opened_files, "register_file", fake_reg)

    activate_mock = Mock(return_value=True)
    monkeypatch.setattr(window, "_activate_existing", activate_mock)

    run_mock = Mock()
    monkeypatch.setattr(desktop, "run", run_mock)

    args = argparse.Namespace(open=[str(test_file)], after_update=False, port=None, no_browser=False, browser=False, serve=False)
    desktop.cmd_desktop(args)

    assert registered == [str(test_file)]
    activate_mock.assert_called_once()
    run_mock.assert_not_called()


def test_desktop_api_file_in_attesa(data, monkeypatch):
    test_file = data / "test.pdf"
    test_file.write_text("dummy")

    from rt.core import opened_files
    reg = opened_files.register_file(str(test_file))
    assert reg is not None

    fake_win = Mock()
    api = window.DesktopApi(fake_win)
    res = api.file_in_attesa()
    assert len(res) >= 1
    item = next(it for it in res if it["token"] == reg["token"])
    assert item["name"] == "test.pdf"

    # Second call returns empty because it's marked announced
    res2 = api.file_in_attesa()
    assert not any(it["token"] == reg["token"] for it in res2)


def test_install_macos_open_files(data, webview, monkeypatch):
    test_file = data / "test.docx"
    test_file.write_text("dummy")

    fake_objc = ModuleType("objc")
    injected_methods = {}

    def fake_selector(fn, selector, signature):
        injected_methods[selector] = fn
        return fn
    fake_objc.selector = fake_selector

    def fake_class_add_methods(cls, methods):
        pass
    fake_objc.classAddMethods = fake_class_add_methods
    monkeypatch.setitem(sys.modules, "objc", fake_objc)

    cocoa_mod = ModuleType("webview.platforms.cocoa")

    class AppDelegate:
        pass
    cocoa_mod.BrowserView = SimpleNamespace(AppDelegate=AppDelegate)

    webview.__path__ = []
    platforms_mod = ModuleType("webview.platforms")
    platforms_mod.__path__ = []
    platforms_mod.cocoa = cocoa_mod
    monkeypatch.setitem(sys.modules, "webview.platforms", platforms_mod)
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", cocoa_mod)
    webview.platforms = platforms_mod

    fake_window = Mock()
    window.install_macos_open_files(fake_window)

    open_files_fn = injected_methods.get(b"application:openFiles:")
    assert open_files_fn is not None

    fake_app = Mock()
    open_files_fn(AppDelegate(), fake_app, [str(test_file)])
    assert fake_window.evaluate_js.call_count == 1
    call_str = fake_window.evaluate_js.call_args[0][0]
    assert "window.rtOpenedFiles" in call_str
    assert "test.docx" in call_str
    fake_app.replyToOpenOrPrint_.assert_called_once_with(0)



