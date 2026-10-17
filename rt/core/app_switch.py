"""
rt.core.app_switch
Dalla RT da terminale (install.sh, 'rt -u') all'app per il Mac, tenendo i dati. La cartella
dati (~/.rt) è la stessa, quindi il passaggio è: scaricare e verificare il .dmg della release
stabile, copiare RT.app in Applicazioni, togliere i servizi launchd della vecchia cartella e
segnarla come ritirata, aprire l'app (che si prende servizi e database alla prima apertura).

Da lì 'rt' nella vecchia cartella passa i comandi all'app (forward_to_app): niente più due RT
diverse sugli stessi dati. Lo propone 'rt -u' alla fine dell'aggiornamento (con il codice
nuovo, in 'rt data post-update') e lo fa 'rt app install'.
"""
import json
import os
import platform
import subprocess
import sys
from typing import Callable, List, Optional

from rt.core import app_update, bundle, paths
from rt.core.version import (OFFLINE_ENV, RELEASES_API, get_current_version, is_prerelease,
                             parse_version)

RETIRED_MARKER = "MOVED_TO_APP"
APP_NAME = "RT.app"


class AppSwitchError(RuntimeError):
    pass


def _apple_silicon() -> bool:
    if platform.machine() == "arm64":
        return True
    try:  # Python x86_64 sotto Rosetta su un Mac Apple Silicon
        res = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True, timeout=5)
        return res.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def unsupported_reason(project_root: str) -> Optional[str]:
    """Perché questa installazione non può passare all'app; None se può."""
    if sys.platform != "darwin":
        return "l'app da terminale c'è solo per il Mac"
    if bundle.kind(project_root):
        return "questa è già l'app"
    if os.path.isdir(os.path.join(project_root, ".git")):
        return "questa è una copia di sviluppo (Git)"
    if paths.explicit_data_dir():
        return "la cartella dati è scelta con RT_DATA_DIR, che l'app non usa"
    if not _apple_silicon():
        return "l'app è solo per i Mac con Apple Silicon"
    return None


# ------------------------------------------------------------------ dove sta l'app

def app_cli_root(app: str) -> str:
    """La cartella del codice dentro RT.app."""
    return os.path.join(app, "Contents", "Resources", "app")


def app_cli(app: str) -> List[str]:
    """Python e script 'rt' dentro RT.app (lo stesso comando del doppio clic, rt/desktop.py)."""
    root = app_cli_root(app)
    return [os.path.join(root, "python", "bin", "python3"), os.path.join(root, "bin", "rt")]


def is_app(path: str) -> bool:
    return bundle.kind(app_cli_root(path)) == bundle.MACOS


def candidate_dirs() -> List[str]:
    return ["/Applications", os.path.expanduser("~/Applications")]


def installed_app() -> Optional[str]:
    """RT.app già installata (per esempio scaricata a mano dal browser)."""
    for folder in candidate_dirs():
        app = os.path.join(folder, APP_NAME)
        if is_app(app):
            return app
    return None


def target_dir() -> str:
    """/Applications se si può scrivere (utente amministratore), altrimenti ~/Applications."""
    system, user = candidate_dirs()
    if os.access(system, os.W_OK):
        return system
    os.makedirs(user, exist_ok=True)
    return user


# ------------------------------------------------------------------ la vecchia cartella

def retired_to(project_root: str) -> Optional[str]:
    """L'app a cui questa cartella è passata, o None se è ancora in uso."""
    try:
        with open(os.path.join(project_root, RETIRED_MARKER), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    app = data.get("app") if isinstance(data, dict) else None
    return app if isinstance(app, str) and app else None


def retire(project_root: str, app: str, say: Callable[[str], None] = print) -> None:
    """Toglie i servizi launchd della vecchia cartella (l'app scrive i suoi alla prima
    apertura) e la segna come ritirata. Non cancella nulla."""
    from rt.services import service_manager as sm
    if sm.supported():
        sm.uninstall(say=lambda _m: None)
    with open(os.path.join(project_root, RETIRED_MARKER), "w", encoding="utf-8") as f:
        json.dump({"app": app, "version": get_current_version(project_root)}, f, indent=2)
        f.write("\n")
    say(f"📦 La cartella {project_root} non serve più: 'rt' nel terminale ora usa l'app.")


def forward_to_app(project_root: str, argv: List[str], execv: Callable = os.execv) -> None:
    """Nella cartella ritirata 'rt' esegue il comando con l'app. Se l'app non c'è più
    (cancellata) avvisa e torna: il comando gira con questa cartella come prima."""
    app = retired_to(project_root)
    if not app:
        return
    python, script = app_cli(app)
    if not (os.path.isfile(python) and os.path.isfile(script)):
        print(f"⚠️  Non trovo {app}: uso la RT di questa cartella. Per tornare all'app: rt app install",
              file=sys.stderr)
        return
    execv(python, [python, script, *argv])


# ------------------------------------------------------------------ il passaggio

def find_release(timeout: float = 15.0) -> app_update.UpdateCheck:
    """Il .dmg dell'ultima release stabile (le beta non hanno un'app da installare da qui)."""
    if os.environ.get(OFFLINE_ENV) == "1":
        raise AppSwitchError("controllo degli aggiornamenti disattivato (RT_UPDATE_OFFLINE=1)")
    try:
        release = app_update._get_json(f"{RELEASES_API}/latest", timeout)
    except Exception as exc:  # noqa: BLE001 - rete, HTTP, JSON: si riprova dopo
        raise AppSwitchError(f"non riesco a contattare GitHub ({getattr(exc, 'reason', exc)})") from None
    info = app_update.evaluate(release, bundle.MACOS, "0")
    if not info.available:
        raise AppSwitchError("l'ultima release stabile non ha ancora l'app per il Mac")
    return info


def check_versions(current: str, app_version: str) -> None:
    """L'app non può essere più vecchia di questa RT: una beta può aver già portato il
    database a uno schema che l'ultima stabile non conosce."""
    cur, app = parse_version(current), parse_version(app_version)
    if cur is not None and app is not None and cur > app:
        kind = "la beta" if is_prerelease(current) else "la versione"
        raise AppSwitchError(f"hai {kind} {current}, più recente dell'app ({app_version}): "
                             "potrai passare all'app con la prossima versione stabile")


def switch(project_root: str, say: Callable[[str], None] = print,
           open_app: Optional[Callable[[str], None]] = None) -> str:
    """Installa (o ritrova) RT.app, ritira questa cartella e apre l'app. Restituisce il
    percorso dell'app."""
    reason = unsupported_reason(project_root)
    if reason:
        raise AppSwitchError(reason)
    app = installed_app()
    if app is None:
        info = find_release()
        check_versions(get_current_version(project_root), info.latest)
        say(f"⬇️  Scarico RT {info.latest} per il Mac...")
        dmg = app_update.download(info)
        app = os.path.join(target_dir(), APP_NAME)
        try:
            app_update.copy_app_from_dmg(dmg, app)
        except app_update.AppUpdateError as exc:
            raise AppSwitchError(str(exc)) from None
        finally:
            app_update._remove(dmg)
        if not is_app(app):
            raise AppSwitchError(f"{app} non è un'app di RT valida")
        say(f"✅ RT installata in {app}")
    else:
        check_versions(get_current_version(project_root), get_current_version(app_cli_root(app)))
        say(f"✅ Uso RT già installata in {app}")
    retire(project_root, app, say)
    (open_app or _open)(app)
    say("🚀 Apro RT: alla prima apertura si prende dati e servizi. Da ora si apre da Applicazioni.")
    return app


def _open(app: str) -> None:
    subprocess.run(["open", app], check=False)


OFFER = ("📱 RT ora è anche un'app per il Mac: si apre da Applicazioni, si aggiorna da sola e i tuoi "
         "dati restano dove sono. Passo all'app adesso?")


def offer(project_root: str, confirm: Callable[[str], bool], say: Callable[[str], None] = print) -> bool:
    """Alla fine di 'rt -u' (terminale interattivo): propone il passaggio. Mai bloccante:
    un errore lascia la RT da terminale com'è."""
    if unsupported_reason(project_root) or retired_to(project_root):
        return False
    if not confirm(OFFER):
        say("Va bene: quando vuoi, passa all'app con 'rt app install'.")
        return False
    try:
        switch(project_root, say=say)
    except (AppSwitchError, app_update.AppUpdateError, OSError) as exc:
        say(f"⚠️  Passaggio all'app non riuscito: {exc}. RT da terminale resta com'è; "
            "riprova con 'rt app install'.")
        return False
    return True
