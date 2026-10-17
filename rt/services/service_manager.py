"""
rt.services.service_manager
Servizi di RT in background (RT4-G1): su macOS sono LaunchAgent di launchd (il default),
uno per processo, che partono al login e ripartono se cadono:

    api     'rt api --service'  API + web app su 127.0.0.1:<porta>
    worker  'rt worker'         esegue i job in coda (e manda le notifiche Telegram)

I file .plist stanno in ~/Library/LaunchAgents (RT_LAUNCH_AGENTS_DIR per i test), i log in
<cartella dati>/logs. Ogni servizio riceve RT_DATA_DIR, così usa la stessa cartella dati di
chi lo installa. Su Linux (Docker) i servizi sono i container di docker-compose.yml.
"""
import os
import plistlib
import socket
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
}
DESCRIPTIONS = {"api": "API e web app", "worker": "worker dei job"}
AGENTS_DIR_ENV = "RT_LAUNCH_AGENTS_DIR"
PORT_ENV = "RT_API_PORT"
DEFAULT_PORT = 8765
PORT_FILE = "api-port"  # nella cartella dati: la porta scelta dall'app quando la 8765 è occupata
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


def _port_file() -> str:
    return os.path.join(paths.default_data_dir(), PORT_FILE)


def _valid_port(value) -> Optional[int]:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def api_port() -> int:
    """RT_API_PORT, altrimenti la porta ricordata dall'app (vedi choose_port), altrimenti 8765."""
    from_env = _valid_port(os.environ.get(PORT_ENV))
    if from_env:
        return from_env
    try:
        with open(_port_file(), encoding="utf-8") as f:
            return _valid_port(f.read()) or DEFAULT_PORT
    except OSError:
        return DEFAULT_PORT


def port_busy(port: int) -> bool:
    """Qualcuno ascolta su 127.0.0.1:<porta> (RT o un altro programma)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_port(after: int) -> int:
    """La prima porta libera dopo <after> (fino a 50 tentativi), altrimenti una scelta dal sistema."""
    for candidate in range(after + 1, min(after + 51, 65536)):
        if port_busy(candidate):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
            except OSError:
                continue
        return candidate
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def choose_port(say: Callable[[str], None] = print) -> int:
    """La porta per l'app: quella solita se è libera o c'è già RT; se la occupa un altro
    programma ne sceglie una libera e la ricorda, così 'rt web' e i servizi la ritrovano.
    Con RT_API_PORT decide l'utente e non si cambia niente."""
    port = api_port()
    if _valid_port(os.environ.get(PORT_ENV)) or not port_busy(port) or api_is_up(port):
        return port
    chosen = _free_port(port)
    try:
        os.makedirs(os.path.dirname(_port_file()), exist_ok=True)
        with open(_port_file(), "w", encoding="utf-8") as f:
            f.write(f"{chosen}\n")
    except OSError as exc:
        say(f"⚠️  Porta {chosen} non ricordata: {exc}")
    say(f"ℹ️  La porta {port} è occupata da un altro programma: RT usa la {chosen}.")
    return chosen


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
        # riparte se esce con errore; un'uscita pulita ('rt service stop') no
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


# LaunchAgent del bot Telegram sempre acceso, che non esiste più (Telegram manda solo
# notifiche, dal worker): quello scritto a mano con la 3.x e il servizio 'bot' della 4.x.
# Lanciano un comando che non c'è più, quindi si tolgono.
LEGACY_AGENT_LABELS = ("com.rt.telegram-daemon", LABEL_PREFIX + "bot")


def legacy_agents() -> List[str]:
    """I .plist del vecchio bot ancora presenti."""
    return [p for p in (os.path.join(agents_dir(), f"{name}.plist") for name in LEGACY_AGENT_LABELS)
            if os.path.isfile(p)]


def remove_legacy_agents(say: Callable[[str], None] = print) -> List[str]:
    """Scarica e cancella i .plist del vecchio bot (vedi LEGACY_AGENT_LABELS)."""
    removed = []
    for path in legacy_agents():
        if supported():
            _launchctl("bootout", f"{_domain()}/{os.path.basename(path)[:-len('.plist')]}")
        try:
            os.remove(path)
        except OSError as exc:
            say(f"⚠️  Non riesco a rimuovere il vecchio bot Telegram ({path}): {exc}")
            continue
        removed.append(path)
        say(f"🗑  Vecchio servizio del bot Telegram rimosso ({os.path.basename(path)}).")
    return removed


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
    remove_legacy_agents(say)
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
