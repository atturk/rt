"""
tests/test_app_switch.py
Dalla RT da terminale all'app per il Mac: i dati (~/.rt) restano, la vecchia cartella si
ritira e 'rt' passa i comandi all'app.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rt.core import app_switch, app_update, bundle

CHECK_OLD_PROCESSES = app_switch.check_old_processes
# ps, launchd ed execv sul Python dell'app: solo Mac (e Linux in CI), non Windows
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="passaggio all'app solo sul Mac")


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
    monkeypatch.setattr(app_switch, "check_old_processes", lambda _root: None)
    return str(root)


def _retire_without_services(project_root, app, say=print):
    with open(os.path.join(project_root, app_switch.RETIRED_MARKER), "w") as f:
        json.dump({"app": app}, f)


@pytest.mark.parametrize("setup, reason", [
    (lambda root, mp: mp.setattr(app_switch.sys, "platform", "linux"), "Mac"),
    (lambda root, mp: os.mkdir(os.path.join(root, ".git")), "Git"),
    (lambda root, mp: Path(root, ".git").write_text("gitdir: /tmp/worktree"), "Git"),
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


@pytest.mark.parametrize("args", [[], ["-v"], ["--version"], ["-u"], ["-u", "--beta"],
                                  ["web"], ["export", "lezione con spazi", "--all"]])
def test_retired_folder_forwards_to_app(source, tmp_path, args):
    app = make_app(str(tmp_path / "Applications"))
    _retire_without_services(source, app)
    calls = []
    app_switch.forward_to_app(source, args, execv=lambda *a: calls.append(a))
    python, script = app_switch.app_cli(app)
    assert calls == [(python, [python, script, *args])]


def test_forward_stops_when_app_is_gone(source, tmp_path, capsys):
    _retire_without_services(source, str(tmp_path / "Applications" / "RT.app"))
    with pytest.raises(SystemExit) as exc:
        app_switch.forward_to_app(source, ["web"], execv=lambda *a: pytest.fail("non deve inoltrare"))
    assert exc.value.code == 1
    assert "Ripristina RT.app" in capsys.readouterr().err


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
    monkeypatch.setattr(sm, "status", lambda name: SimpleNamespace(loaded=False))
    app_switch.retire(str(root), "/Applications/RT.app", say=lambda _m: None)
    assert removed and app_switch.retired_to(str(root)) == "/Applications/RT.app"


@pytest.mark.parametrize("contents", ['{"app": 42}', '[]', 'non è JSON'])
def test_invalid_marker_never_runs_old_code(source, contents):
    Path(source, app_switch.RETIRED_MARKER).write_text(contents)
    with pytest.raises(SystemExit):
        app_switch.forward_to_app(source, ["-u"])


def test_forward_rejects_chains_and_app_never_forwards(source, tmp_path):
    app = make_app(str(tmp_path / "Applications"))
    _retire_without_services(source, app)
    app_root = app_switch.app_cli_root(app)
    _retire_without_services(app_root, source)
    with pytest.raises(SystemExit):
        app_switch.forward_to_app(source, ["-v"])
    app_switch.forward_to_app(app_root, ["-v"], execv=lambda *a: pytest.fail("ciclo"))


def test_forward_handles_unexecutable_python(source, tmp_path, capsys):
    app = make_app(str(tmp_path / "Applications"))
    _retire_without_services(source, app)
    def broken(*args):
        raise PermissionError("accesso negato")
    with pytest.raises(SystemExit):
        app_switch.forward_to_app(source, ["web"], execv=broken)
    assert "Ripristina l'app" in capsys.readouterr().err


@posix_only
@pytest.mark.parametrize("args", [["-v"], ["-u", "--beta"], ["web", "--no-browser"]])
def test_wrapper_forwards_before_old_venv_and_dependencies(source, tmp_path, args):
    # Una cartella ritirata deve funzionare anche con venv e dipendenze non più usabili.
    repo = Path(__file__).resolve().parents[1]
    root = Path(source)
    (root / "bin").mkdir()
    shutil.copy2(repo / "bin" / "rt", root / "bin" / "rt")
    (root / "rt" / "core").mkdir(parents=True)
    (root / "rt" / "__init__.py").touch()
    for name in ("__init__", "app_switch", "app_update", "bundle", "paths", "version", "spa_release"):
        shutil.copy2(repo / "rt" / "core" / f"{name}.py", root / "rt" / "core" / f"{name}.py")
    venv = root / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").write_text("#!/bin/sh\nexit 91\n")
    (venv / "python3").chmod(0o755)
    app = make_app(str(tmp_path / "Applications"))
    python, script = map(Path, app_switch.app_cli(app))
    python.unlink()
    python.symlink_to(sys.executable)
    script.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    _retire_without_services(source, app)
    result = subprocess.run([sys.executable, str(root / "bin" / "rt"), *args],
                            capture_output=True, text=True, timeout=10, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == args


@pytest.mark.parametrize("current, target", [("sconosciuta", "4.3.0"), ("4.3.0", "non valida")])
def test_unreadable_version_refuses_switch(current, target):
    with pytest.raises(app_switch.AppSwitchError, match="confrontare"):
        app_switch.check_versions(current, target)


def test_switch_checks_version_before_download(source, monkeypatch):
    Path(source, "VERSION").write_text("4.3.1b1")
    monkeypatch.setattr(app_switch, "find_release", lambda: app_update.UpdateCheck(
        supported=True, current="0", latest="4.3.0", available=True))
    monkeypatch.setattr(app_update, "download", lambda _i: pytest.fail("non deve scaricare"))
    with pytest.raises(app_switch.AppSwitchError, match="beta"):
        app_switch.switch(source)
    assert app_switch.retired_to(source) is None


def test_downloaded_app_is_checked_before_retirement(source, tmp_path, monkeypatch):
    monkeypatch.setattr(app_switch, "find_release", lambda: app_update.UpdateCheck(
        supported=True, current="0", latest="4.3.1", available=True))
    dmg = tmp_path / "RT.dmg"
    dmg.touch()
    monkeypatch.setattr(app_update, "download", lambda _i: str(dmg))
    monkeypatch.setattr(app_update, "copy_app_from_dmg",
                        lambda d, target: make_app(os.path.dirname(target), version="4.2.6"))
    with pytest.raises(app_switch.AppSwitchError, match="più recente"):
        app_switch.switch(source, open_app=lambda _a: pytest.fail("non deve aprire"))
    assert not dmg.exists()
    assert not (tmp_path / "Applications" / "RT.app").exists()
    assert not list((tmp_path / "Applications").glob(".rt-install-*"))
    assert app_switch.retired_to(source) is None


def test_existing_unknown_app_is_preserved(source, tmp_path):
    for directory in app_switch.candidate_dirs():
        folder = Path(directory, "RT.app")
        folder.mkdir(parents=True)
        (folder / "personale.txt").write_text("da conservare")
    with pytest.raises(app_switch.AppSwitchError, match="esiste già"):
        app_switch.target_dir()
    assert all(Path(d, "RT.app", "personale.txt").read_text() == "da conservare"
               for d in app_switch.candidate_dirs())


def test_offer_decline_is_proposed_again(source):
    questions = []
    def decline(question):
        questions.append(question)
        return False
    for _ in range(2):
        assert not app_switch.offer(source, decline, say=lambda _m: None)
    assert len(questions) == 2


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_offer_cancellation_does_not_fail_update(source, error):
    def cancel(_question):
        raise error
    assert not app_switch.offer(source, cancel, say=lambda _m: None)


def test_open_failure_reports_retirement(source, tmp_path, capsys):
    make_app(str(tmp_path / "Applications"))
    def cannot_open(_app):
        raise app_switch.AppSwitchError("apertura fallita")
    original = app_switch.switch
    from unittest.mock import patch
    with patch.object(app_switch, "switch", side_effect=lambda root, say: original(root, say, cannot_open)):
        assert not app_switch.offer(source, lambda _q: True)
    assert app_switch.retired_to(source)
    assert "già ritirata" in capsys.readouterr().out


@posix_only
@pytest.mark.parametrize("script", ["{root}/bin/rt web --no-browser", "bin/rt web", "./bin/rt api", "rt/bin/rt web",
                                    "{root}/bin/rt worker --concurrency 2"])
def test_old_foreground_process_blocks_switch(source, monkeypatch, script):
    from rt.services import service_manager as sm
    monkeypatch.setattr(sm, "status", lambda name: SimpleNamespace(pid=101 if name == "api" else 102))
    output = f"101 {source}/bin/rt api --service\n103 python {script.format(root=source)}\n"
    monkeypatch.setattr(app_switch.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
    with pytest.raises(app_switch.AppSwitchError, match="Ctrl\\+C"):
        CHECK_OLD_PROCESSES(source)


@posix_only
def test_managed_services_and_update_do_not_block_switch(source, monkeypatch):
    from rt.services import service_manager as sm
    monkeypatch.setattr(sm, "status", lambda name: SimpleNamespace(pid=101 if name == "api" else 102))
    output = (f"101 python {source}/bin/rt api --service\n102 python {source}/bin/rt worker\n"
              f"103 python {source}/bin/rt -u --beta\n104 python {source}/bin/rt data post-update\n")
    monkeypatch.setattr(app_switch.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
    CHECK_OLD_PROCESSES(source)


def test_service_failure_prevents_marker_and_open(tmp_path, monkeypatch):
    from rt.services import service_manager as sm
    monkeypatch.setattr(sm, "supported", lambda: True)
    monkeypatch.setattr(sm, "uninstall", lambda **kw: [])
    monkeypatch.setattr(sm, "status", lambda name: SimpleNamespace(loaded=True))
    with pytest.raises(app_switch.AppSwitchError, match="servizi"):
        app_switch.retire(str(tmp_path), "/Applications/RT.app")
    assert not (tmp_path / app_switch.RETIRED_MARKER).exists()
    assert not list(tmp_path.glob(".rt-moved-*"))


@pytest.mark.parametrize("stdin_tty, stdout_tty, noninteractive, ok, offers", [
    (True, True, "0", True, 1),
    (True, False, "0", True, 0),  # install.sh: stdout passa da tee
    (False, True, "0", True, 0),
    (True, True, "1", True, 0),
    (True, True, "0", False, 0),
])
def test_post_update_offer_only_in_interactive_terminal(monkeypatch, stdin_tty, stdout_tty,
                                                       noninteractive, ok, offers):
    from rt import cli_system
    from rt.services import data_service
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_tty)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_tty)
    monkeypatch.setenv("RT_NONINTERACTIVE", noninteractive)
    monkeypatch.setattr(data_service, "post_update", lambda **kw: ok)
    proposed = []
    monkeypatch.setattr(app_switch, "offer", lambda *a: proposed.append(a))
    with pytest.raises(SystemExit) as exc:
        cli_system.cmd_data(SimpleNamespace(data_command="post-update"))
    assert exc.value.code == (0 if ok else 1)
    assert len(proposed) == offers


def test_find_release_only_accepts_stable_with_checksums(source, monkeypatch):
    monkeypatch.delenv("RT_UPDATE_OFFLINE", raising=False)
    from tests.test_app_update import release
    monkeypatch.setattr(app_update, "_get_json", lambda url, timeout: release())
    assert app_switch.find_release().asset_name.endswith("macos-arm64.dmg")
    for invalid in (release(prerelease=True), release(names=("RT-4.3.0-macos-arm64.dmg",))):
        monkeypatch.setattr(app_update, "_get_json", lambda url, timeout: invalid)
        with pytest.raises(app_switch.AppSwitchError, match="stabile"):
            app_switch.find_release()
