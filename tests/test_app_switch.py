"""
tests/test_app_switch.py
Dalla RT da terminale all'app per il Mac: i dati (~/.rt) restano, la vecchia cartella si
ritira e 'rt' passa i comandi all'app.
"""
import json
import os

import pytest

from rt.core import app_switch, app_update, bundle


def make_app(folder, version="4.3.1"):
    app = os.path.join(folder, "RT.app")
    root = app_switch.app_cli_root(app)
    os.makedirs(os.path.join(root, "python", "bin"))
    os.makedirs(os.path.join(root, "bin"))
    for path in app_switch.app_cli(app):
        open(path, "w").close()
    with open(os.path.join(root, bundle.MARKER), "w") as f:
        f.write("macos\n")
    with open(os.path.join(root, "VERSION"), "w") as f:
        f.write(version + "\n")
    return app


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "rt"
    root.mkdir()
    (root / "VERSION").write_text("4.3.0\n")
    monkeypatch.setattr(app_switch.sys, "platform", "darwin")
    monkeypatch.setattr(app_switch, "_apple_silicon", lambda: True)
    monkeypatch.delenv("RT_DATA_DIR", raising=False)
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(app_switch, "candidate_dirs", lambda: [str(apps), str(tmp_path / "home-apps")])
    monkeypatch.setattr(app_switch, "retire", _retire_without_services)
    return str(root)


def _retire_without_services(project_root, app, say=print):
    with open(os.path.join(project_root, app_switch.RETIRED_MARKER), "w") as f:
        json.dump({"app": app}, f)


@pytest.mark.parametrize("setup, reason", [
    (lambda root, mp: mp.setattr(app_switch.sys, "platform", "linux"), "Mac"),
    (lambda root, mp: os.mkdir(os.path.join(root, ".git")), "Git"),
    (lambda root, mp: mp.setenv("RT_DATA_DIR", "/tmp/x"), "RT_DATA_DIR"),
    (lambda root, mp: mp.setattr(app_switch, "_apple_silicon", lambda: False), "Apple Silicon"),
])
def test_unsupported(source, monkeypatch, setup, reason):
    setup(source, monkeypatch)
    assert reason in app_switch.unsupported_reason(source)


def test_supported(source):
    assert app_switch.unsupported_reason(source) is None


def test_beta_newer_than_app_is_refused():
    with pytest.raises(app_switch.AppSwitchError, match="beta 4.3.1b1"):
        app_switch.check_versions("4.3.1b1", "4.3.0")
    app_switch.check_versions("4.3.0", "4.3.0")
    app_switch.check_versions("4.2.6b5", "4.3.0")


def test_switch_downloads_installs_retires_and_opens(source, tmp_path, monkeypatch):
    info = app_update.UpdateCheck(supported=True, current="0", latest="4.3.1", available=True)
    monkeypatch.setattr(app_switch, "find_release", lambda: info)
    dmg = tmp_path / "RT.dmg"
    dmg.write_text("x")
    monkeypatch.setattr(app_update, "download", lambda i: str(dmg))
    monkeypatch.setattr(app_update, "copy_app_from_dmg",
                        lambda d, target: make_app(os.path.dirname(target)))
    opened = []
    app = app_switch.switch(source, say=lambda _m: None, open_app=opened.append)
    assert app == str(tmp_path / "Applications" / "RT.app")
    assert opened == [app]
    assert app_switch.retired_to(source) == app
    assert not dmg.exists()


def test_switch_reuses_app_installed_by_hand(source, tmp_path, monkeypatch):
    app = make_app(str(tmp_path / "Applications"))
    monkeypatch.setattr(app_switch, "find_release", lambda: pytest.fail("niente download"))
    assert app_switch.switch(source, say=lambda _m: None, open_app=lambda _a: None) == app
    assert app_switch.retired_to(source) == app


def test_switch_refuses_older_app(source, tmp_path):
    make_app(str(tmp_path / "Applications"), version="4.2.6")
    with pytest.raises(app_switch.AppSwitchError):
        app_switch.switch(source, say=lambda _m: None, open_app=lambda _a: None)
    assert app_switch.retired_to(source) is None


def test_retired_folder_forwards_to_app(source, tmp_path):
    app = make_app(str(tmp_path / "Applications"))
    _retire_without_services(source, app)
    calls = []
    app_switch.forward_to_app(source, ["-u", "--beta"], execv=lambda *a: calls.append(a))
    python, script = app_switch.app_cli(app)
    assert calls == [(python, [python, script, "-u", "--beta"])]


def test_forward_falls_back_when_app_is_gone(source, tmp_path, capsys):
    _retire_without_services(source, str(tmp_path / "Applications" / "RT.app"))
    app_switch.forward_to_app(source, ["web"], execv=lambda *a: pytest.fail("non deve inoltrare"))
    assert "rt app install" in capsys.readouterr().err


def test_folder_in_use_does_not_forward(source):
    app_switch.forward_to_app(source, ["web"], execv=lambda *a: pytest.fail("non deve inoltrare"))


def test_offer_declined_or_failing_leaves_terminal_rt(source, monkeypatch):
    said = []
    assert not app_switch.offer(source, confirm=lambda _q: False, say=said.append)
    assert "rt app install" in said[-1]

    def broken():
        raise app_switch.AppSwitchError("non riesco a contattare GitHub")
    monkeypatch.setattr(app_switch, "find_release", broken)
    assert not app_switch.offer(source, confirm=lambda _q: True, say=said.append)
    assert "GitHub" in said[-1] and app_switch.retired_to(source) is None


def test_offer_skipped_where_unsupported(source, monkeypatch):
    monkeypatch.setattr(app_switch.sys, "platform", "linux")
    assert not app_switch.offer(source, confirm=lambda _q: pytest.fail("non deve chiedere"))


def test_retire_removes_old_services_and_marks_folder(tmp_path, monkeypatch):
    from rt.services import service_manager as sm
    root = tmp_path / "rt"
    root.mkdir()
    removed = []
    monkeypatch.setattr(sm, "supported", lambda: True)
    monkeypatch.setattr(sm, "uninstall", lambda say=print: removed.append(True))
    app_switch.retire(str(root), "/Applications/RT.app", say=lambda _m: None)
    assert removed and app_switch.retired_to(str(root)) == "/Applications/RT.app"
