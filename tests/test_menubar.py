"""Test per rt/menubar.py e per l'endpoint /api/v1/jobs?state=active."""
import json
import os
import sys
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image

from rt import menubar


def test_menubar_template_assets_exist_and_are_monochrome():
    expected_sizes = {
        "rt-template.png": (16, 16),
        "rt-template@2x.png": (32, 32),
        "rt-active-template.png": (16, 16),
        "rt-active-template@2x.png": (32, 32),
    }
    for fname, size in expected_sizes.items():
        path = os.path.join(menubar._ASSETS_DIR, fname)
        assert os.path.isfile(path), f"manca {path}"
        img = Image.open(path).convert("RGBA")
        assert img.size == size
        pixels = list(img.get_flattened_data()) if hasattr(img, "get_flattened_data") else list(img.getdata())
        # Solo nero (0, 0, 0) sui pixel non trasparenti
        assert any(a > 0 for _, _, _, a in pixels)
        assert all((r, g, b) == (0, 0, 0) for r, g, b, a in pixels if a > 0)
        assert any(a == 0 for _, _, _, a in pixels)


def test_menu_model_no_jobs():
    items = menubar.menu_model([], start_at_login=True)
    assert items[0] == menubar.MenuItem(kind="action", title="Apri RT", action_id="open", enabled=True, bold=True)
    assert items[1].kind == "separator"
    assert items[2] == menubar.MenuItem(kind="status", title="Nessuna elaborazione in corso", enabled=False)
    assert items[3].kind == "separator"
    assert items[4] == menubar.MenuItem(
        kind="toggle", title="Avvia RT all'accesso", action_id="toggle_login", enabled=True, checked=True
    )
    assert items[5] == menubar.MenuItem(kind="action", title="Esci da RT", action_id="quit", enabled=True)


def test_menu_model_api_unreachable():
    items = menubar.menu_model(None, start_at_login=False, api_reachable=False)
    status_titles = [i.title for i in items if i.kind == "status"]
    assert status_titles == ["RT si sta avviando…"]
    toggle = next(i for i in items if i.kind == "toggle")
    assert toggle.checked is False


def test_menu_model_one_job_with_phase_and_percentage():
    jobs = [
        {
            "id": "j1",
            "type": "run_pipeline",
            "state": "running",
            "lesson_title": "Anatomia del rene",
            "progress": {"phase": "review", "current": 3, "total": 4},
        },
        {"id": "j2", "type": "run_pipeline", "state": "succeeded", "lesson_title": "Finita"},
    ]
    items = menubar.menu_model(jobs)
    statuses = [i for i in items if i.kind == "status"]
    assert len(statuses) == 1
    assert statuses[0].enabled is False
    assert statuses[0].title == "Anatomia del rene — Revisione 75%"


def test_menu_model_five_jobs_caps_at_three_and_shows_overflow():
    jobs = [
        {
            "id": f"j{i}",
            "type": "run_pipeline",
            "state": "running",
            "lesson_path": f"/tmp/lessons/[2026-10-1{i}] Lezione {i}",
            "progress": {"phase": "rewrite", "current": i, "total": 10},
        }
        for i in range(1, 6)
    ]
    items = menubar.menu_model(jobs)
    statuses = [i for i in items if i.kind == "status"]
    assert all(not s.enabled for s in statuses)
    assert [s.title for s in statuses] == [
        "Lezione 1 — Rielaborazione 10%",
        "Lezione 2 — Rielaborazione 20%",
        "Lezione 3 — Rielaborazione 30%",
        "e altre 2…",
    ]


def test_poll_interval_changes_with_active_jobs():
    assert menubar.poll_interval([], api_reachable=True) == 15.0
    assert menubar.poll_interval([{"state": "succeeded"}], api_reachable=True) == 15.0
    assert menubar.poll_interval([{"state": "running"}], api_reachable=True) == 3.0
    assert menubar.poll_interval(None, api_reachable=False) == 15.0


def test_fetch_active_jobs_success_and_error(monkeypatch):
    from rt.api import auth

    monkeypatch.setattr(auth, "create_session", lambda: "sess-1")
    dropped = []
    monkeypatch.setattr(auth, "drop_session", dropped.append)

    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps([{"id": "1", "state": "running"}]).encode("utf-8")
    fake_resp.__enter__.return_value = fake_resp
    monkeypatch.setattr(menubar.urllib.request, "urlopen", lambda req, timeout=2.0: fake_resp)

    jobs, reachable = menubar.fetch_active_jobs("http://127.0.0.1:8765")
    assert reachable is True and jobs == [{"id": "1", "state": "running"}]
    assert dropped == ["sess-1"]

    monkeypatch.setattr(menubar.urllib.request, "urlopen", Mock(side_effect=OSError("down")))
    jobs2, reachable2 = menubar.fetch_active_jobs("http://127.0.0.1:8765")
    assert reachable2 is False and jobs2 is None
    assert dropped == ["sess-1", "sess-1"]


def test_quit_rt_without_active_jobs_stops_closes_and_terminates():
    stop_mock = Mock()
    close_mock = Mock()
    term_mock = Mock()
    confirm_mock = Mock()

    ok = menubar.quit_rt(
        "http://127.0.0.1:8765",
        jobs=[],
        confirm_fn=confirm_mock,
        stop_fn=stop_mock,
        close_window_fn=close_mock,
        terminate_fn=term_mock,
    )
    assert ok is True
    confirm_mock.assert_not_called()
    stop_mock.assert_called_once_with("http://127.0.0.1:8765")
    close_mock.assert_called_once_with()
    term_mock.assert_called_once_with()


def test_quit_rt_with_active_jobs_confirms_and_respects_cancel():
    stop_mock = Mock()
    close_mock = Mock()
    term_mock = Mock()
    confirm_mock = Mock(return_value=False)

    jobs = [{"id": "1", "state": "running"}, {"id": "2", "state": "queued"}]
    cancelled = menubar.quit_rt(
        "http://127.0.0.1:8765",
        jobs=jobs,
        confirm_fn=confirm_mock,
        stop_fn=stop_mock,
        close_window_fn=close_mock,
        terminate_fn=term_mock,
    )
    assert cancelled is False
    confirm_mock.assert_called_once_with(
        "Ci sono 2 lavori in corso. Uscendo si interrompono e riprendono alla prossima apertura di RT."
    )
    stop_mock.assert_not_called()
    close_mock.assert_not_called()
    term_mock.assert_not_called()

    confirm_mock.return_value = True
    confirmed = menubar.quit_rt(
        "http://127.0.0.1:8765",
        jobs=jobs,
        confirm_fn=confirm_mock,
        stop_fn=stop_mock,
        close_window_fn=close_mock,
        terminate_fn=term_mock,
    )
    assert confirmed is True
    stop_mock.assert_called_once_with("http://127.0.0.1:8765")
    close_mock.assert_called_once_with()
    term_mock.assert_called_once_with()


def test_open_rt_app_and_non_macos_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(menubar.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Mock(returncode=0))
    menubar.open_rt_app()
    assert calls == [["open", "-b", "com.atturk.rt"]]

    monkeypatch.setattr(sys, "platform", "win32")
    assert menubar.run_menubar() == 0


def test_toggle_start_at_login_persists_via_api(api_client, tmp_path, rt_db, monkeypatch):
    from rt.api import auth
    from rt.core.config import load_config
    from tests.api_support import workspace_with_example_config

    workspace_with_example_config(tmp_path, monkeypatch)
    assert load_config().ui.start_at_login is True
    monkeypatch.setattr(auth, "create_session", lambda: "sess-x")
    monkeypatch.setattr(auth, "drop_session", lambda _s: None)

    captured = {}

    def fake_urlopen(req, timeout=3.0):
        body = json.loads(req.data.decode("utf-8"))
        res = api_client.put("/api/v1/settings/preferences", json=body)
        captured["status"] = res.status_code
        resp = MagicMock()
        resp.status = res.status_code
        resp.__enter__.return_value = resp
        return resp

    monkeypatch.setattr(menubar.urllib.request, "urlopen", fake_urlopen)
    val = menubar.toggle_start_at_login("http://127.0.0.1:8765")
    assert val is False
    assert captured["status"] == 200
    assert load_config().ui.start_at_login is False


def test_api_jobs_state_active_returns_only_active_jobs_with_lesson_title(api_client, tmp_path, rt_db, monkeypatch):
    from rt.api.jobs import queue
    from rt.services.jobs import JobState
    from tests.api_support import make_lesson, workspace_with_example_config

    root = workspace_with_example_config(tmp_path, monkeypatch)
    lesson = make_lesson(root)

    q = queue()
    j_done = q.enqueue("run_pipeline", lesson, {})
    claimed = q.claim("w1", ["run_pipeline"])
    assert claimed is not None and claimed.id == j_done
    assert q.finish(j_done, "w1", JobState.SUCCEEDED)
    j_active = q.enqueue("run_pipeline", lesson, {})

    active = api_client.get("/api/v1/jobs", params={"state": "active"}).json()
    ids = [j["id"] for j in active]
    assert j_active in ids and j_done not in ids
    mine = next(j for j in active if j["id"] == j_active)
    assert mine["lesson_title"]


def test_install_macos_dock_menu_registers_selector_and_builds_menu(monkeypatch):
    import types
    from rt import window as rt_window

    added = []
    fake_delegate_cls = type("AppDelegate", (), {})
    fake_cocoa = types.SimpleNamespace(BrowserView=types.SimpleNamespace(AppDelegate=fake_delegate_cls))
    fake_webview_platforms = types.SimpleNamespace(cocoa=fake_cocoa)
    fake_webview = types.SimpleNamespace(platforms=fake_webview_platforms)
    fake_objc = types.SimpleNamespace(
        selector=lambda fn, selector, signature: (fn, selector, signature),
        classAddMethods=lambda cls, methods: added.append((cls, methods)),
    )
    fake_foundation = types.SimpleNamespace(
        NSObject=object,
        NSAttributedString=MagicMock(),
    )
    fake_appkit = MagicMock()
    monkeypatch.setitem(sys.modules, "objc", fake_objc)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "webview.platforms", fake_webview_platforms)
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", fake_cocoa)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr(menubar, "fetch_active_jobs", lambda url, timeout=0.5: ([], True))
    monkeypatch.setattr(menubar, "read_start_at_login", lambda: True)

    rt_window.install_macos_dock_menu(window=Mock(), base_url="http://127.0.0.1:8765")
    assert len(added) == 1
    cls, methods = added[0]
    assert cls is fake_delegate_cls
    fn, sel, sig = methods[0]
    assert sel == b"applicationDockMenu:" and sig == b"@@:@"
    result_menu = fn(None, None)
    assert result_menu is not None
    fake_appkit.NSMenu.alloc.return_value.init.return_value.setAutoenablesItems_.assert_called_with(False)
