"""
RT4-G1: servizi launchd (rt.services.service_manager) e comandi pensati per girare come
servizio ('rt api --service', 'rt web' con API già attiva).
"""
import os
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
    with pytest.raises(sm.ServiceError):
        sm.render_plist("bot")  # il bot sempre acceso non c'è più


@pytest.mark.skipif(os.name == "nt", reason="launchd esiste solo sul Mac")
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


def test_old_bot_agents_are_removed_on_install(launchd, tmp_path):
    """I LaunchAgent del vecchio bot (scritto a mano con la 3.x, servizio 'bot' della 4.x)
    lanciano un comando che non esiste più: doctor li segnala e install li toglie."""
    from rt.services import doctor_service
    calls, loaded = launchd
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    old = [agents / "com.rt.telegram-daemon.plist", agents / "com.atturk.rt.bot.plist"]
    for path in old:
        path.write_bytes(plistlib.dumps({"Label": path.stem}))
    loaded.add("com.atturk.rt.bot")
    checks = [c for c in doctor_service.check_services() if c.name == "Vecchio bot Telegram"]
    assert len(checks) == 2 and checks[0].status == doctor_service.WARN
    said = []
    sm.install(["api"], start=False, say=said.append)
    assert not any(path.exists() for path in old)
    assert "com.atturk.rt.bot" not in loaded
    assert sum("Vecchio servizio del bot Telegram rimosso" in line for line in said) == 2
    assert sm.legacy_agents() == []


def test_parse_launchctl_print():
    text = "gui/501/com.atturk.rt.api = {\n\tactive count = 1\n\tstate = running\n\tpid = 12\n\t\tstate = nested\n}"
    info = sm.parse_launchctl_print(text)
    assert info["state"] == "running" and info["pid"] == "12"


def test_services_unsupported_outside_macos(monkeypatch):
    monkeypatch.setattr(sm, "supported", lambda: False)
    with pytest.raises(sm.ServiceError, match="solo su macOS"):
        sm.install(["api"])


@pytest.mark.skipif(os.name == "nt", reason="launchd esiste solo sul Mac")
def test_cli_service_status(launchd, capsys):
    from rt.cli import main
    main(["service", "install", "api"])
    main(["service", "status"])
    out = capsys.readouterr().out
    assert "api" in out and "attivo, pid 4242" in out and "non installato" in out  # worker
    assert "bot" not in out


def test_api_service_mode_hides_token():
    from rt.api.server import _without_token
    lines = []
    say = _without_token(lines.append)
    for line in ("🔑 Token API (mostrato una sola volta, conservalo):", "   segreto123",
                 "   Nella pagina /docs premi 'Authorize'", "🚀 API RT su http://127.0.0.1:8765"):
        say(line)
    assert not any("segreto123" in line for line in lines)
    assert lines[-1].startswith("🚀")


def test_rt_web_opens_browser_when_services_run(monkeypatch, rt_db):
    from rt.api import launcher
    monkeypatch.setattr(launcher, "_already_running", lambda port: True)
    opened = []
    monkeypatch.setattr(launcher, "_open_when_ready", lambda base, url, say, ob: opened.append(url))
    monkeypatch.setattr("uvicorn.Server.run", lambda *a, **k: pytest.fail("non doveva avviare un'altra API"))
    assert launcher.run_spa(say=lambda _m: None, open_browser=False) == 0
    assert opened and "/login?code=" in opened[0]
