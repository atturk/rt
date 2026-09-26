"""
RT4-G1: servizi launchd (rt.services.service_manager) e comandi pensati per girare come
servizio ('rt api --service', 'rt telegram-daemon --service', 'rt web' con API già attiva).
"""
import plistlib
import subprocess

import pytest

from rt.services import service_manager as sm


@pytest.fixture
def launchd(tmp_path, monkeypatch):
    """launchctl finto: registra le chiamate e simula quali servizi sono caricati."""
    calls, loaded = [], set()
    monkeypatch.setenv("RT_LAUNCH_AGENTS_DIR", str(tmp_path / "LaunchAgents"))
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sm, "supported", lambda: True)
    monkeypatch.setattr(sm.os, "getuid", lambda: 501, raising=False)

    def fake_run(cmd, capture_output=True, text=True, timeout=30):
        calls.append(cmd[1:])
        verb, rc, out = cmd[1], 0, ""
        if verb == "bootstrap":
            loaded.add(cmd[3].rsplit("/", 1)[-1].replace(".plist", ""))
        elif verb == "bootout":
            label = cmd[2].rsplit("/", 1)[-1]
            rc = 0 if label in loaded else 3
            loaded.discard(label)
        elif verb == "print":
            label = cmd[2].rsplit("/", 1)[-1]
            if label in loaded:
                out = "gui/501/x = {\n\tstate = running\n\tpid = 4242\n\tlast exit code = 0\n\t\tnested = 1\n}\n"
            else:
                rc = 113
        return subprocess.CompletedProcess(cmd, rc, out, "")
    monkeypatch.setattr(sm.subprocess, "run", fake_run)
    return calls, loaded


def test_render_plist(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path / "data"))
    spec = plistlib.loads(sm.render_plist("api", port=9000))
    assert spec["Label"] == "com.atturk.rt.api"
    assert spec["ProgramArguments"][-4:] == ["api", "--service", "--port", "9000"]
    assert spec["EnvironmentVariables"]["RT_DATA_DIR"] == str(tmp_path / "data")
    assert spec["StandardOutPath"] == str(tmp_path / "data" / "logs" / "api.log")
    assert spec["KeepAlive"] == {"SuccessfulExit": False} and spec["RunAtLoad"] is True
    bot = plistlib.loads(sm.render_plist("bot"))
    assert bot["ProgramArguments"][-2:] == ["telegram-daemon", "--service"]
    with pytest.raises(sm.ServiceError):
        sm.render_plist("nope")


def test_install_status_stop_uninstall(launchd, tmp_path):
    calls, loaded = launchd
    assert sm.install(["api", "worker"], say=lambda _m: None) == ["api", "worker"]
    assert sm.installed() == ["api", "worker"]
    assert loaded == {"com.atturk.rt.api", "com.atturk.rt.worker"}
    st = sm.status("api")
    assert (st.installed, st.loaded, st.running, st.pid) == (True, True, True, 4242)
    assert sm.stop(["worker"]) == ["worker"] and "com.atturk.rt.worker" not in loaded
    assert sm.start(["worker"]) == ["worker"] and "com.atturk.rt.worker" in loaded
    assert sm.restart(["api"]) == ["api"] and ["kickstart", "-k", "gui/501/com.atturk.rt.api"] in calls
    # reinstallare riscrive il plist e ricarica senza errori (idempotente)
    sm.install(["api"], say=lambda _m: None)
    assert sm.uninstall(say=lambda _m: None) == ["api", "worker"]
    assert sm.installed() == [] and not loaded


def test_parse_launchctl_print():
    text = "gui/501/com.atturk.rt.api = {\n\tactive count = 1\n\tstate = running\n\tpid = 12\n\t\tstate = nested\n}"
    info = sm.parse_launchctl_print(text)
    assert info["state"] == "running" and info["pid"] == "12"


def test_services_unsupported_outside_macos(monkeypatch):
    monkeypatch.setattr(sm, "supported", lambda: False)
    with pytest.raises(sm.ServiceError, match="solo su macOS"):
        sm.install(["api"])


def test_cli_service_status(launchd, capsys):
    from rt.cli import main
    main(["service", "install", "--no-bot"])
    main(["service", "status"])
    out = capsys.readouterr().out
    assert "api" in out and "attivo, pid 4242" in out and "non installato" in out  # bot


def test_api_service_mode_hides_token():
    from rt.api.server import _without_token
    lines = []
    say = _without_token(lines.append)
    for line in ("🔑 Token API (mostrato una sola volta, conservalo):", "   segreto123",
                 "   Nella pagina /docs premi 'Authorize'", "🚀 API RT su http://127.0.0.1:8765"):
        say(line)
    assert not any("segreto123" in line for line in lines)
    assert lines[-1].startswith("🚀")


def test_telegram_service_exits_cleanly_when_not_configured(monkeypatch, capsys):
    from rt import cli
    monkeypatch.setattr("rt.services.settings_service.telegram_configured", lambda: False)
    monkeypatch.setattr("rt.telegram.daemon.run_daemon", lambda **_k: pytest.fail("non doveva partire"))
    cli.cmd_telegram_daemon(type("A", (), {"service": True, "state_dir": None})())
    assert "non configurato" in capsys.readouterr().err


def test_rt_web_opens_browser_when_services_run(monkeypatch, rt_db):
    from rt.api import launcher
    monkeypatch.setattr(launcher, "_already_running", lambda port: True)
    opened = []
    monkeypatch.setattr(launcher, "_open_when_ready", lambda base, url, say, ob: opened.append(url))
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("non doveva avviare un'altra API"))
    assert launcher.run_spa(say=lambda _m: None, open_browser=False) == 0
    assert opened and "/login?code=" in opened[0]
