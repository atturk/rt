"""
rt.desktop
'rt desktop': quello che parte facendo doppio clic su RT (RT.app sul Mac, il collegamento
nel menu Start su Windows).

- La prima volta, e dopo ogni aggiornamento dell'app, prepara cartella dati, database e
  archivio dei segreti (come l'ultimo passo di install.sh e di 'rt -u').
- Sul Mac installa (o riallinea all'app) i servizi in background di launchd, aspetta l'API e
  apre il browser già autenticato; poi esce: RT resta acceso anche senza finestre.
- Su Windows avvia API e worker in questa finestra (come 'rt web'): chiuderla spegne RT.
  Se RT è già acceso apre solo il browser.
- Usa la porta 8765; se la occupa un altro programma ne sceglie una libera e la ricorda.
- Scarica in background il browser per le catture delle visualizzazioni, se manca.
"""
import argparse
import os
import plistlib
import subprocess
import sys
import time
from typing import Callable, Optional

from rt.core import bundle, paths

STAMP_FILE = "app-version"
API_WAIT_SECONDS = 90


def _log_path() -> str:
    return os.path.join(paths.default_data_dir(), "logs", "desktop.log")


def _sayer() -> Callable[[str], None]:
    def say(message: str) -> None:
        print(message, flush=True)
        try:
            os.makedirs(os.path.dirname(_log_path()), exist_ok=True)
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass
    return say


def _stamp() -> str:
    return os.path.join(paths.default_data_dir(), STAMP_FILE)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def needs_setup(version: str) -> bool:
    """Prima apertura o app aggiornata: dati, database e servizi vanno (ri)preparati."""
    return not paths.is_initialized() or _read(_stamp()) != version


def prepare(version: str, say: Callable[[str], None]) -> bool:
    """Cartella dati, database (migrazioni comprese), lezioni da importare, segreti."""
    from rt.services import data_service
    say("⚙️  Preparo RT (solo alla prima apertura e dopo un aggiornamento)...")
    os.environ["RT_NONINTERACTIVE"] = "1"
    ok = data_service.post_update(say=say)
    ensure_secrets(say)
    if ok:
        try:
            with open(_stamp(), "w", encoding="utf-8") as f:
                f.write(version + "\n")
        except OSError as exc:
            say(f"⚠️  {exc}")
    return ok


def ensure_secrets(say: Callable[[str], None]) -> None:
    """Archivio cifrato con la chiave master nel portachiavi (Portachiavi del Mac, Gestione
    credenziali di Windows). Senza portachiavi non si crea: una chiave da trascrivere a mano
    non ha senso in un'app, e le chiavi restano nel file .env della cartella dati."""
    from rt.security.secrets import default_store_path
    from rt.services import secrets_service
    path = default_store_path()
    if path.is_file():
        return
    try:
        result = secrets_service.init_store()
    except Exception as exc:  # noqa: BLE001 - l'app parte comunque
        say(f"⚠️  Archivio dei segreti non creato: {exc}")
        return
    if result.master_key_to_show:
        try:
            os.remove(result.path)
        except OSError:
            pass
        say("ℹ️  Portachiavi non disponibile: le chiavi API restano nel file .env della cartella dati.")
        return
    say("🔐 Archivio cifrato per chiavi API e token pronto.")


def _browsers_dir() -> Optional[str]:
    return os.environ.get("PLAYWRIGHT_BROWSERS_PATH") if bundle.kind() else None


def ensure_capture_browser(say: Callable[[str], None]) -> None:
    """Chromium per le catture delle visualizzazioni: si scarica in background la prima volta."""
    target = _browsers_dir()
    if not target:
        return
    if os.path.isdir(target) and any(name.startswith("chromium") for name in os.listdir(target)):
        return
    os.makedirs(target, exist_ok=True)
    log = open(os.path.join(paths.default_data_dir(), "logs", "browser-install.log"), "a", encoding="utf-8")
    kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
    try:
        subprocess.Popen([sys.executable, "-m", "playwright", "install", "chromium"],
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
        say("🌐 Scarico in background il browser per le catture delle visualizzazioni.")
    except OSError as exc:
        say(f"⚠️  Browser per le catture non scaricato: {exc}")
    finally:
        log.close()


def _services_match_app() -> bool:
    """I servizi launchd usano il Python di questa app (non quello di un'altra installazione)."""
    from rt.services import service_manager as sm
    for name in sm.SERVICES:
        try:
            with open(sm.plist_path(name), "rb") as f:
                program = plistlib.load(f)["ProgramArguments"][0]
        except (OSError, KeyError, IndexError, plistlib.InvalidFileException):
            return False
        if os.path.realpath(program) != os.path.realpath(sys.executable):
            return False
    return True


def _service_port() -> Optional[int]:
    """La porta scritta nel servizio api di launchd."""
    from rt.services import service_manager as sm
    try:
        with open(sm.plist_path("api"), "rb") as f:
            args = plistlib.load(f)["ProgramArguments"]
        return int(args[args.index("--port") + 1])
    except (OSError, KeyError, ValueError, IndexError, plistlib.InvalidFileException):
        return None


def _wait_for_api(port: int, seconds: float = API_WAIT_SECONDS) -> bool:
    from rt.services.service_manager import api_is_up
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if api_is_up(port):
            return True
        time.sleep(0.5)
    return False


def _alert(message: str) -> None:
    """Sul Mac l'app non ha una finestra: gli errori si mostrano in un avviso."""
    if sys.platform == "darwin":
        script = f'display alert "RT" message {_applescript_string(message)} as critical'
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_macos(port: int, open_browser: bool, say: Callable[[str], None]) -> int:
    from rt.api.launcher import run_spa
    from rt.services import service_manager as sm
    try:
        if not sm.installed() or not _services_match_app() or _service_port() != port:
            sm.install(port=port, say=say)
    except sm.ServiceError as exc:
        say(f"❌ {exc}")
        _alert(f"Non riesco ad avviare RT in background: {exc}")
        return 1
    if not _wait_for_api(port):
        log = os.path.join(paths.data_dir(), "logs", "api.log")
        say(f"❌ RT non risponde: controlla {log}.")
        _alert(f"RT non risponde. Il registro è in {log}.")
        return 1
    # print, non say: il token API mostrato alla prima apertura non va nel registro
    return run_spa(port=port, open_browser=open_browser, worker=False, say=print)


def run_foreground(port: int, open_browser: bool, say: Callable[[str], None]) -> int:
    """Windows (e Linux): API e worker in questo processo, come 'rt web'."""
    from rt.api.launcher import run_spa
    from rt.services.service_manager import api_is_up
    if sys.platform == "win32":
        os.system("title RT")
    if not api_is_up(port):
        say("💡 RT resta acceso finché questa finestra è aperta: chiudila per spegnerlo.")
    return run_spa(port=port, open_browser=open_browser, say=print)


def run(port: Optional[int] = None, open_browser: bool = True) -> int:
    from rt.core.version import get_current_version
    from rt.services.service_manager import choose_port
    say = _sayer()
    version = get_current_version(paths.project_root())
    if needs_setup(version) and not prepare(version, say):
        say("⚠️  Preparazione incompleta: RT parte lo stesso, i dettagli sono qui sopra.")
    ensure_capture_browser(say)
    # la 8765, o un'altra libera (ricordata) se la occupa un altro programma
    port = port or choose_port(say)
    from rt.services import service_manager as sm
    if sm.supported() and os.environ.get("RT_NO_SERVICES") != "1":
        return run_macos(port, open_browser, say)
    return run_foreground(port, open_browser, say)


def configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", type=int, default=None, help="Porta locale (default: 8765)")
    p.add_argument("--no-browser", action="store_true", help="Non aprire il browser")
    p.add_argument("--after-update", action="store_true",
                   help="Riavvio dopo un aggiornamento: la pagina già aperta si ricarica da sola")


def cmd_desktop(args: argparse.Namespace) -> None:
    code = run(port=args.port, open_browser=not (args.no_browser or args.after_update))
    if code and sys.platform == "win32" and sys.stdin and sys.stdin.isatty():
        input("\nPremi Invio per chiudere questa finestra.")
    if code:
        sys.exit(code)
