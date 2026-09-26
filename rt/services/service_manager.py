"""
rt.services.service_manager
Servizi di RT in background (RT4-G1): su macOS sono LaunchAgent di launchd (il default),
uno per processo, che partono al login e ripartono se cadono:

    api     'rt api --service'              API + web app su 127.0.0.1:<porta>
    worker  'rt worker'                     esegue i job in coda
    bot     'rt telegram-daemon --service'  bot Telegram (esce subito se non è configurato)

I file .plist stanno in ~/Library/LaunchAgents (RT_LAUNCH_AGENTS_DIR per i test), i log in
<cartella dati>/logs. Ogni servizio riceve RT_DATA_DIR, così usa la stessa cartella dati di
chi lo installa. Su Linux (Docker) i servizi sono i container di docker-compose.yml.
"""
import os
import plistlib
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from rt.core import paths

LABEL_PREFIX = "com.atturk.rt."
SERVICES: Dict[str, List[str]] = {
    "api": ["api", "--service"],
    "worker": ["worker"],
    "bot": ["telegram-daemon", "--service"],
}
DESCRIPTIONS = {"api": "API e web app", "worker": "worker dei job", "bot": "bot Telegram"}
AGENTS_DIR_ENV = "RT_LAUNCH_AGENTS_DIR"
PORT_ENV = "RT_API_PORT"
DEFAULT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


class ServiceError(RuntimeError):
    pass


@dataclass
class ServiceStatus:
    name: str
    installed: bool
    loaded: bool
    running: bool
    pid: Optional[int] = None
    last_exit: Optional[str] = None


def supported() -> bool:
    return sys.platform == "darwin"


def label(name: str) -> str:
    return LABEL_PREFIX + name


def agents_dir() -> str:
    return os.path.expanduser(os.environ.get(AGENTS_DIR_ENV) or "~/Library/LaunchAgents")


def plist_path(name: str) -> str:
    return os.path.join(agents_dir(), label(name) + ".plist")


def api_port() -> int:
    try:
        return int(os.environ.get(PORT_ENV) or 8765)
    except ValueError:
        return 8765


def _python() -> str:
    venv = os.path.join(paths.project_root(), ".venv", "bin", "python3")
    return venv if os.path.isfile(venv) else sys.executable


def render_plist(name: str, data_dir: Optional[str] = None, port: Optional[int] = None) -> bytes:
    """Il .plist del servizio: comando, cartella dati, log, riavvio se cade."""
    if name not in SERVICES:
        raise ServiceError(f"Servizio sconosciuto: {name} (disponibili: {', '.join(SERVICES)})")
    data = data_dir or paths.default_data_dir()
    args = [_python(), os.path.join(paths.project_root(), "bin", "rt")] + SERVICES[name]
    if name == "api":
        args += ["--port", str(port or api_port())]
    log = os.path.join(data, "logs", f"{name}.log")
    env = {"RT_DATA_DIR": data, "PATH": DEFAULT_PATH, "PYTHONUNBUFFERED": "1", "LANG": "it_IT.UTF-8"}
    spec = {
        "Label": label(name),
        "ProgramArguments": args,
        "WorkingDirectory": data,
        "EnvironmentVariables": env,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "RunAtLoad": True,
        # riparte se esce con errore; un'uscita pulita (bot non configurato, 'rt service stop') no
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Background" if name == "worker" else "Standard",
    }
    return plistlib.dumps(spec)


def _launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    try:
        res = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"launchctl non disponibile: {exc}") from exc
    if check and res.returncode != 0:
        raise ServiceError(f"launchctl {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
    return res


def _bootstrap(path: str, attempts: int = 10) -> None:
    """launchctl bootstrap, riprovando: subito dopo un bootout launchd può rispondere
    "Input/output error" finché il servizio vecchio non è del tutto scaricato."""
    import time
    for attempt in range(attempts):
        res = _launchctl("bootstrap", _domain(), path)
        if res.returncode == 0:
            return
        if attempt == attempts - 1:
            raise ServiceError(f"launchctl bootstrap {path}: {(res.stderr or res.stdout).strip()}")
        time.sleep(0.5)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _target(name: str) -> str:
    return f"{_domain()}/{label(name)}"


def _require_supported() -> None:
    if not supported():
        raise ServiceError("I servizi in background con launchd esistono solo su macOS. Su Linux usa "
                           "docker compose (docs/SELF_HOSTING.md) o avvia 'rt api' e 'rt worker' a mano.")


def installed(names: Optional[Sequence[str]] = None) -> List[str]:
    return [n for n in (names or SERVICES) if os.path.isfile(plist_path(n))]


def install(names: Optional[Sequence[str]] = None, start: bool = True, data_dir: Optional[str] = None,
            port: Optional[int] = None, say: Callable[[str], None] = print) -> List[str]:
    """Scrive (o riscrive) i .plist e li carica. Idempotente: reinstallare aggiorna comando e
    percorsi, per esempio dopo aver spostato la cartella di RT."""
    _require_supported()
    names = list(names or SERVICES)
    data = data_dir or paths.default_data_dir()
    os.makedirs(os.path.join(data, "logs"), exist_ok=True)
    os.makedirs(agents_dir(), exist_ok=True)
    for name in names:
        content = render_plist(name, data, port)
        path = plist_path(name)
        with open(path, "wb") as f:
            f.write(content)
        if start:
            _launchctl("bootout", _target(name))  # se era già caricato con il plist vecchio
            _bootstrap(path)
        say(f"✅ Servizio {name} ({DESCRIPTIONS[name]}) installato" + (" e avviato." if start else "."))
    return names


def uninstall(names: Optional[Sequence[str]] = None, say: Callable[[str], None] = print) -> List[str]:
    removed = []
    for name in (names or SERVICES):
        path = plist_path(name)
        if supported():
            _launchctl("bootout", _target(name))
        if os.path.isfile(path):
            os.remove(path)
            removed.append(name)
            say(f"🗑  Servizio {name} rimosso.")
    return removed


def start(names: Optional[Sequence[str]] = None) -> List[str]:
    _require_supported()
    out = []
    for name in installed(names):
        if not status(name).loaded:
            _bootstrap(plist_path(name))
        else:
            _launchctl("kickstart", _target(name), check=True)
        out.append(name)
    return out


def stop(names: Optional[Sequence[str]] = None) -> List[str]:
    """Ferma e scarica i servizi (ripartono al prossimo login o con 'rt service start')."""
    _require_supported()
    out = []
    for name in installed(names):
        if status(name).loaded:
            _launchctl("bootout", _target(name))
            out.append(name)
    return out


def restart(names: Optional[Sequence[str]] = None) -> List[str]:
    _require_supported()
    out = []
    for name in installed(names):
        if status(name).loaded:
            _launchctl("kickstart", "-k", _target(name), check=True)
        else:
            _bootstrap(plist_path(name))
        out.append(name)
    return out


def status(name: str) -> ServiceStatus:
    is_installed = os.path.isfile(plist_path(name))
    if not supported():
        return ServiceStatus(name, is_installed, False, False)
    res = _launchctl("print", _target(name))
    if res.returncode != 0:
        return ServiceStatus(name, is_installed, False, False)
    info = parse_launchctl_print(res.stdout)
    pid = int(info["pid"]) if info.get("pid", "").isdigit() else None
    return ServiceStatus(name, is_installed, True, info.get("state") == "running" or pid is not None,
                         pid, info.get("last exit code"))


def parse_launchctl_print(text: str) -> Dict[str, str]:
    """Le righe 'chiave = valore' di primo livello di 'launchctl print'."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("\t") and not line.startswith("\t\t") and " = " in line:
            key, _, value = line.strip().partition(" = ")
            out.setdefault(key.strip(), value.strip())
    return out


def api_is_up(port: Optional[int] = None, timeout: float = 1.0) -> bool:
    """L'API di RT risponde su 127.0.0.1:<porta> (servizio, 'rt web' o 'rt api')."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port or api_port()}/api/v1/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False
