"""
rt.services.doctor_service
'rt doctor' (RT4-G2): controlla prerequisiti, cartella dati, database, chiave master, web app,
servizi e porta, e per ogni problema dice come sistemarlo. Nessun controllo modifica nulla.
"""
import os
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional

from rt.core import paths

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    message: str
    fix: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _safe(name: str, fn: Callable[[], Check]) -> Check:
    try:
        return fn()
    except Exception as exc:  # un controllo rotto non deve fermare gli altri
        return Check(name, FAIL, f"controllo non riuscito: {exc}")


def check_python() -> Check:
    v = sys.version_info
    if v < (3, 11):
        return Check("Python", FAIL, f"Python {v.major}.{v.minor}: serve 3.11 o successivo.",
                     "Rilancia il comando di installazione: installa Python 3.13 con Homebrew.")
    venv = os.path.join(paths.project_root(), ".venv")
    if os.path.realpath(sys.prefix) != os.path.realpath(venv) and os.path.isdir(venv):
        return Check("Python", WARN, f"Python {v.major}.{v.minor} fuori dall'ambiente di RT ({sys.prefix}).",
                     "Usa il comando 'rt' (bin/rt), che attiva da solo .venv.")
    return Check("Python", OK, f"Python {v.major}.{v.minor}.{v.micro}")


def check_ffmpeg() -> Check:
    if shutil.which("ffmpeg"):
        return Check("ffmpeg", OK, "installato")
    return Check("ffmpeg", FAIL, "non trovato: serve per audio e trascrizione.", "brew install ffmpeg")


def check_transcription() -> Check:
    from rt.core.config import load_config
    engine = load_config().transcription.engine
    if engine == "custom":
        return Check("Trascrizione", OK, "motore personalizzato (custom)")
    if sys.platform != "darwin":
        return Check("Trascrizione", WARN, "macparakeet funziona solo su macOS: su questa macchina i worker "
                     "non trascrivono (i job audio aspettano un worker sul Mac).",
                     "Configura un motore compatibile (docs/ALTERNATIVE_TRANSCRIPTION.md).")
    if shutil.which("macparakeet-cli"):
        return Check("Trascrizione", OK, "macparakeet-cli installato")
    return Check("Trascrizione", WARN, "macparakeet-cli non trovato: le lezioni da audio non si trascrivono.",
                 "brew install moona3k/tap/macparakeet-cli (serve un Mac Apple Silicon)")


def check_data_dir() -> Check:
    active = paths.active_data_dir()
    if not active:
        return Check("Cartella dati", WARN, "installazione con la disposizione 3.x (config nella cartella di RT).",
                     "Esegui 'rt data migrate' (o 'rt -u'): sposta tutto in ~/.rt, con copia di sicurezza.")
    if not os.access(active, os.W_OK):
        return Check("Cartella dati", FAIL, f"{active} non è scrivibile.", f"Controlla i permessi di {active}.")
    free = shutil.disk_usage(active).free
    if free < 1_000_000_000:
        return Check("Cartella dati", WARN, f"{active}: meno di 1 GB libero ({free // 1_048_576} MB).",
                     "Libera spazio: audio e immagini delle lezioni stanno qui.")
    return Check("Cartella dati", OK, active)


def check_config() -> Check:
    from rt.core.config import load_config
    config_dir = paths.config_dir()
    if not os.path.isfile(os.path.join(config_dir, "general.yaml")):
        return Check("Configurazione", FAIL, f"{config_dir}/general.yaml mancante.",
                     "Rilancia il comando di installazione (ricrea la configurazione senza toccare i dati).")
    cfg = load_config()
    root = cfg.telegram.lessons_root
    if not root:
        return Check("Configurazione", WARN, "cartella delle lezioni non ancora scelta.",
                     "Apri la web app (rt web) e completa la configurazione guidata.")
    if not os.path.isdir(os.path.expanduser(root)):
        return Check("Configurazione", WARN, f"la cartella delle lezioni {root} non esiste.",
                     "Sceglila di nuovo in Impostazioni > Generali.")
    return Check("Configurazione", OK, f"lezioni in {root}")


def check_database() -> Check:
    from rt.db.engine import current_database_url, current_revision, get_database, head_revision, sqlite_file
    url = current_database_url()
    if not url:
        return Check("Database", WARN, "disattivato (RT_DATABASE_URL=off): solo per sviluppo.")
    shown = sqlite_file(url) or url.split("@")[-1]
    if sqlite_file(url) and not os.path.isfile(sqlite_file(url)):
        return Check("Database", WARN, f"non ancora creato: {shown}.", "Esegui 'rt db upgrade' (lo fa anche l'installer).")
    db = get_database()
    if db is None:
        return Check("Database", FAIL, f"non si apre: {shown}.",
                     "Esegui 'rt db upgrade'; se è rotto ripristina un backup con 'rt restore'.")
    rev, head = current_revision(db.engine), head_revision()
    if rev != head:
        return Check("Database", FAIL, f"revisione {rev}, attesa {head}.", "Esegui 'rt db upgrade'.")
    return Check("Database", OK, f"{shown} (revisione {rev})")


def check_media() -> Check:
    from rt.db.engine import get_database
    from rt.services.backup_service import verify_media
    from rt.storage import fs
    db = get_database()
    if db is None:
        return Check("Media", WARN, "database non disponibile: controllo saltato.")
    problems = verify_media(db, fs.media_dir(db))
    if problems:
        return Check("Media", FAIL, f"{len(problems)} file referenziati mancano (es. {problems[0]}).",
                     "Ripristinali da un backup: 'rt restore <cartella del backup>'.")
    return Check("Media", OK, fs.media_dir(db))


def check_folder_lessons() -> Check:
    """Lezioni ancora nel vecchio formato a cartelle: RT non le mostra finché non si convertono."""
    from rt.core.config import load_config
    from rt.db.engine import get_database
    from rt.storage.migrate import folder_lessons
    db = get_database()
    if db is None:
        return Check("Lezioni a cartelle", WARN, "database non disponibile: controllo saltato.")
    pending = folder_lessons(db, load_config().telegram.lessons_root)
    if pending:
        return Check("Lezioni a cartelle", WARN,
                     f"{len(pending)} lezioni nel vecchio formato a cartelle, non visibili nella web app.",
                     "Esegui 'rt db migrate-storage' (fa prima un backup).")
    return Check("Lezioni a cartelle", OK, "nessuna lezione da convertire")


def check_secrets() -> Check:
    from rt.security.secrets import EncryptedFileSecretStore, default_store_path, resolve_master_key
    from rt.services.secrets_service import env_needs_migration
    store = default_store_path()
    if not store.is_file():
        return Check("Segreti", WARN, "archivio cifrato assente: le chiavi API restano in chiaro in .env.",
                     "Esegui 'rt secrets init' e poi 'rt secrets migrate'.")
    key = resolve_master_key()
    if not key:
        return Check("Segreti", FAIL, "chiave master non trovata (né portachiavi né RT_MASTER_KEY).",
                     "Reimposta RT_MASTER_KEY o ripristina la voce 'rt' del portachiavi.")
    EncryptedFileSecretStore(store, master_key=key).get_all()  # solleva se la chiave è sbagliata
    if env_needs_migration(paths.env_file(), os.path.join(paths.config_dir(), "general.yaml")):
        return Check("Segreti", WARN, "ci sono ancora chiavi in chiaro in .env.", "Esegui 'rt secrets migrate'.")
    return Check("Segreti", OK, f"archivio cifrato {store}, chiave master disponibile")


def check_spa() -> Check:
    from rt.core.paths import find_spa_dir
    found = find_spa_dir()
    if found:
        return Check("Web app", OK, found)
    return Check("Web app", FAIL, "interfaccia web non installata.", "Esegui 'rt -u' (scarica la web app della release).")


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_services() -> List[Check]:
    from rt.services import service_manager as sm
    port = sm.api_port()
    out = []
    api_up = sm.api_is_up(port)
    if sm.supported():
        for name in sm.SERVICES:
            st = sm.status(name)
            label = f"Servizio {name}"
            if not st.installed:
                level = WARN if name != "bot" else OK
                out.append(Check(label, level, "non installato" + ("" if name != "bot" else " (facoltativo)"),
                                 "" if name == "bot" else f"Esegui 'rt service install {name}'."))
            elif st.running:
                out.append(Check(label, OK, f"attivo (pid {st.pid})" if st.pid else "attivo"))
            elif name == "bot":
                out.append(Check(label, OK, "installato, fermo (parte quando configuri Telegram)"))
            else:
                out.append(Check(label, FAIL, "installato ma fermo" + (f" (ultima uscita {st.last_exit})" if st.last_exit else ""),
                                 f"Esegui 'rt service start {name}' e guarda {os.path.join(paths.data_dir(), 'logs', name + '.log')}."))
        for path in sm.legacy_agents():
            out.append(Check("Bot della 3.x", WARN, f"LaunchAgent scritto a mano ancora presente: {path} "
                             "(con il servizio bot girerebbero due bot sullo stesso token).",
                             f"Rimuovilo: {sm.legacy_agent_hint(path)}"))
    if api_up:
        out.append(Check("Porta", OK, f"RT risponde su http://127.0.0.1:{port}"))
    elif _port_busy(port):
        out.append(Check("Porta", FAIL, f"la porta {port} è occupata da un altro programma.",
                         f"Libera la porta o scegline un'altra: RT_API_PORT=<porta> rt service install api."))
    else:
        out.append(Check("Porta", OK if not sm.supported() or not sm.installed(["api"]) else WARN,
                         f"porta {port} libera" + (" ma l'API non risponde" if sm.installed(["api"]) else ""),
                         "" if not sm.installed(["api"]) else "Esegui 'rt service restart api'."))
    return out


def check_worker() -> Check:
    from rt.db.engine import get_database
    from rt.services.jobs import DbJobQueue
    db = get_database()
    if db is None:
        return Check("Worker", WARN, "database non disponibile: controllo saltato.")
    workers = DbJobQueue(db).live_workers()
    if not workers:
        return Check("Worker", WARN, "nessun worker attivo: i job in coda non partono.",
                     "Avvia il servizio ('rt service start worker') o 'rt web'.")
    stt = [w for w in workers if (w.get("capabilities") or {}).get("stt") or w.get("capabilities") is None]
    return Check("Worker", OK, f"{len(workers)} attivi" + ("" if stt else ", nessuno trascrive audio"))


def run_checks() -> List[Check]:
    checks = [
        _safe("Python", check_python),
        _safe("ffmpeg", check_ffmpeg),
        _safe("Cartella dati", check_data_dir),
        _safe("Configurazione", check_config),
        _safe("Trascrizione", check_transcription),
        _safe("Database", check_database),
        _safe("Media", check_media),
        _safe("Lezioni a cartelle", check_folder_lessons),
        _safe("Segreti", check_secrets),
        _safe("Web app", check_spa),
    ]
    try:
        checks += check_services()
    except Exception as exc:
        checks.append(Check("Servizi", FAIL, f"controllo non riuscito: {exc}"))
    checks.append(_safe("Worker", check_worker))
    return checks


def summary(checks: List[Check]) -> Optional[str]:
    """None se tutto ok, altrimenti il livello peggiore."""
    if any(c.status == FAIL for c in checks):
        return FAIL
    if any(c.status == WARN for c in checks):
        return WARN
    return None
