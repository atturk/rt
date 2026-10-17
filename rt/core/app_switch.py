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
import re
import shutil
import subprocess
import sys
import tempfile
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
        return "il passaggio all'app è disponibile solo sul Mac"
    if bundle.kind(project_root):
        return "questa è già l'app"
    if os.path.exists(os.path.join(project_root, ".git")):
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
    return (bundle.kind(app_cli_root(path)) == bundle.MACOS
            and all(os.path.isfile(p) for p in app_cli(path)))


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
    if os.access(system, os.W_OK) and not os.path.lexists(os.path.join(system, APP_NAME)):
        return system
    os.makedirs(user, exist_ok=True)
    if os.path.lexists(os.path.join(user, APP_NAME)):
        raise AppSwitchError(f"{os.path.join(user, APP_NAME)} esiste già ma non è un'app RT valida: "
                             "scegli dove conservarla prima di riprovare")
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
    # Verifica prima di fermare i servizi che sia possibile scrivere il segnale di ritiro.
    fd, pending = tempfile.mkstemp(prefix=".rt-moved-", dir=project_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"app": app, "version": get_current_version(project_root)}, f, indent=2)
            f.write("\n")
        if sm.supported():
            try:
                sm.uninstall(say=lambda _m: None)
                if any(sm.status(name).loaded for name in sm.SERVICES):
                    raise sm.ServiceError("i servizi precedenti sono ancora caricati")
            except sm.ServiceError as exc:
                raise AppSwitchError(f"non riesco a fermare i servizi: {exc}") from None
        os.replace(pending, os.path.join(project_root, RETIRED_MARKER))
    finally:
        app_update._remove(pending)
    say(f"📦 La cartella {project_root} non serve più: 'rt' nel terminale ora usa l'app.")


def forward_to_app(project_root: str, argv: List[str], execv: Optional[Callable] = None) -> None:
    """Inoltra ogni comando all'app, senza ripiegare sul codice vecchio o creare catene."""
    if bundle.kind(project_root) or not os.path.lexists(os.path.join(project_root, RETIRED_MARKER)):
        return
    app = retired_to(project_root)
    if (not app or not is_app(app)
            or os.path.realpath(app_cli_root(app)) == os.path.realpath(project_root)
            or os.path.lexists(os.path.join(app_cli_root(app), RETIRED_MARKER))):
        print("❌ Questa cartella RT è ritirata e non trovo un'app valida a cui passare i comandi. "
              f"Ripristina RT.app in {app or 'Applicazioni'} dal .dmg. "
              "I dati restano in ~/.rt.", file=sys.stderr)
        raise SystemExit(1)
    python, script = app_cli(app)
    try:
        (execv or os.execv)(python, [python, script, *argv])
    except OSError as exc:
        print(f"❌ Non riesco ad avviare {app}: {exc}. Ripristina l'app dal .dmg; "
              "i dati restano in ~/.rt.", file=sys.stderr)
        raise SystemExit(1) from None


def check_old_processes(project_root: str) -> None:
    """Un vecchio 'rt web' in primo piano non viene fermato da launchd: va chiuso con Ctrl+C."""
    from rt.services import service_manager as sm
    try:
        managed = {sm.status(name).pid for name in sm.SERVICES} if sm.supported() else set()
        result = subprocess.run(["ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,command="],
                                capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError, sm.ServiceError) as exc:
        raise AppSwitchError(f"non riesco a verificare i processi RT ancora accesi: {exc}") from None
    scripts = (os.path.join(project_root, "bin", "rt"), os.path.join(os.path.realpath(project_root), "bin", "rt"))
    pattern = re.compile(r"(?:^|\s)(?:" + "|".join(re.escape(s) for s in scripts)
                         + r"|(?:\S*/)?bin/rt)\s+(web|api|worker)(?:\s|$)")
    active = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid = int(fields[0])
        match = pattern.search(fields[1])
        if pid != os.getpid() and pid not in managed and match:
            active.append(f"rt {match[1]} (PID {pid})")
    if active:
        raise AppSwitchError("sono ancora accesi " + ", ".join(active) + ". "
                             "Fermali con Ctrl+C nei loro terminali, poi riprova con 'rt app install'")


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
    if cur is None or app is None:
        raise AppSwitchError("non riesco a confrontare le versioni di RT: passaggio annullato")
    if cur > app:
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
    check_old_processes(project_root)
    app = installed_app()
    if app is None:
        info = find_release()
        check_versions(get_current_version(project_root), info.latest)
        folder = target_dir()
        app = os.path.join(folder, APP_NAME)
        staging = tempfile.mkdtemp(prefix=".rt-install-", dir=folder)
        dmg = None
        try:
            say(f"⬇️  Scarico RT {info.latest} per il Mac...")
            dmg = app_update.download(info)
            staged_app = os.path.join(staging, APP_NAME)
            app_update.copy_app_from_dmg(dmg, staged_app)
            if not is_app(staged_app):
                raise AppSwitchError("il .dmg non contiene un'app di RT valida")
            check_versions(get_current_version(project_root), get_current_version(app_cli_root(staged_app)))
            if os.path.lexists(app):
                raise AppSwitchError(f"{app} esiste già: non la sostituisco")
            os.rename(staged_app, app)
        except app_update.AppUpdateError as exc:
            raise AppSwitchError(str(exc)) from None
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if dmg:
                app_update._remove(dmg)
        say(f"✅ RT installata in {app}")
    else:
        check_versions(get_current_version(project_root), get_current_version(app_cli_root(app)))
        say(f"✅ Uso RT già installata in {app}")
    # Il download può essere lungo: ricontrolla prima di ritirare la cartella.
    check_old_processes(project_root)
    retire(project_root, app, say)
    (open_app or _open)(app)
    say("🚀 Apro RT: usa i dati già presenti e prepara i servizi. Da ora si apre da Applicazioni.")
    return app


def _open(app: str) -> None:
    try:
        subprocess.run(["open", app], check=True, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AppSwitchError(f"non riesco ad aprire {app}: {exc}") from None


OFFER = ("📱 RT ora è anche un'app per il Mac: si apre da Applicazioni, installa gli aggiornamenti stabili e i tuoi "
         "dati restano dove sono. Passo all'app adesso?")


def offer(project_root: str, confirm: Callable[[str], bool], say: Callable[[str], None] = print) -> bool:
    """Alla fine di 'rt -u' propone il passaggio, senza far fallire l'aggiornamento.
    Il rifiuto non viene salvato: si ripropone al prossimo aggiornamento."""
    if unsupported_reason(project_root) or retired_to(project_root):
        return False
    try:
        accepted = confirm(OFFER)
    except (EOFError, KeyboardInterrupt):
        say("Passaggio all'app annullato; l'aggiornamento è completato.")
        return False
    if not accepted:
        say("Va bene: quando vuoi, passa all'app con 'rt app install'.")
        return False
    try:
        switch(project_root, say=say)
    except (AppSwitchError, app_update.AppUpdateError, OSError) as exc:
        if retired_to(project_root):
            say(f"⚠️  {exc}. La cartella è già ritirata: apri RT da Applicazioni. I dati restano in ~/.rt.")
        else:
            say(f"⚠️  Passaggio all'app non riuscito: {exc}. I dati restano al loro posto; "
                "riprova con 'rt app install'.")
        return False
    return True
