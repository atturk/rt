"""
rt.core.paths
La cartella dati di RT (RT4-G1): un solo posto per config/, .env, secrets.enc, DB, media/,
stato del bot, PID, log e backup, al posto della cartella d'installazione e di ~/.rt.

- RT_DATA_DIR (es. /data nel container) la sceglie in modo esplicito e vince sempre.
- Altrimenti è ~/.rt, ma solo quando è "attiva": contiene il file DATA_MARKER, scritto da
  'rt data init' (installer) o da 'rt data migrate' (aggiornamento da una 3.x).
- Senza cartella dati attiva tutto resta come prima (config/ nella cwd o nella cartella
  d'installazione, DB in <lessons_root>/.rt/rt.db): le installazioni vecchie funzionano
  finché la migrazione non le sposta.

config_home() è la cartella che contiene config/ e .env, con questa precedenza:
RT_DATA_DIR > config/ nella cwd (sviluppo e test) > cartella dati attiva > cartella del codice.
"""
import json
import os
from typing import Optional

DATA_DIR_ENV = "RT_DATA_DIR"
DATA_MARKER = "rt-data.json"
DEFAULT_DATA_DIR = os.path.join("~", ".rt")


def project_root() -> str:
    """Cartella del codice di RT (quella che contiene il pacchetto rt/)."""
    import rt
    return os.path.dirname(os.path.dirname(os.path.abspath(rt.__file__)))


def explicit_data_dir() -> Optional[str]:
    value = os.environ.get(DATA_DIR_ENV, "").strip()
    return os.path.abspath(os.path.expanduser(value)) if value else None


def default_data_dir() -> str:
    """Dove sta (o starà) la cartella dati: RT_DATA_DIR, altrimenti ~/.rt."""
    return explicit_data_dir() or os.path.abspath(os.path.expanduser(DEFAULT_DATA_DIR))


def is_initialized(path: Optional[str] = None) -> bool:
    return os.path.isfile(os.path.join(path or default_data_dir(), DATA_MARKER))


def active_data_dir() -> Optional[str]:
    """La cartella dati in uso, o None per un'installazione con la disposizione vecchia.
    ~/.rt/rt-data.json può rimandare altrove ("location"): è il caso di una 3.x migrata con
    DB e media in <lessons_root>/.rt, lasciati dove sono (magari su un disco esterno)."""
    explicit = explicit_data_dir()
    if explicit:
        return explicit
    path = default_data_dir()
    if not is_initialized(path):
        return None
    location = read_marker(path).get("location")
    return os.path.abspath(os.path.expanduser(location)) if location else path


def data_dir() -> str:
    """Cartella per i dati propri di RT (PID, stato, log): quella attiva, altrimenti ~/.rt
    come prima."""
    return active_data_dir() or os.path.abspath(os.path.expanduser(DEFAULT_DATA_DIR))


def config_home(fallback: Optional[str] = None) -> str:
    """Cartella che contiene config/ e .env (vedi la precedenza nel docstring del modulo)."""
    explicit = explicit_data_dir()
    if explicit:
        return explicit
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "config")):
        return cwd
    active = active_data_dir()
    if active:
        return active
    return os.fspath(fallback) if fallback else project_root()


def config_dir(fallback: Optional[str] = None) -> str:
    return os.path.join(config_home(fallback), "config")


def env_file(fallback: Optional[str] = None) -> str:
    """Il .env in uso: RT_DATA_DIR, poi quello della cwd (comportamento storico di
    load_env_file), poi la cartella dati attiva, poi la cartella del codice."""
    explicit = explicit_data_dir()
    if explicit:
        return os.path.join(explicit, ".env")
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(cwd_env):
        return cwd_env
    return os.path.join(active_data_dir() or os.fspath(fallback or project_root()), ".env")


def sub_dir(name: str, create: bool = False) -> str:
    """<cartella dati>/<name> (logs, run, backups, uploads...)."""
    path = os.path.join(data_dir(), name)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def read_marker(path: Optional[str] = None) -> dict:
    try:
        with open(os.path.join(path or default_data_dir(), DATA_MARKER), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_marker(path: str, **info) -> None:
    os.makedirs(path, exist_ok=True)
    data = {**read_marker(path), "layout": 1, **info}
    tmp = os.path.join(path, f"{DATA_MARKER}.{os.getpid()}.tmp")  # più processi all'avvio (docker)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, os.path.join(path, DATA_MARKER))


SPA_DIR_ENV = "RT_SPA_DIR"


def find_spa_dir() -> Optional[str]:
    """Build della web app: RT_SPA_DIR, poi rt/spa (release), poi frontend/dist (sviluppo).
    Qui e non in rt.api.spa perché serve anche alla diagnostica (rt doctor)."""
    root = project_root()
    candidates = [os.environ.get(SPA_DIR_ENV, "").strip(),
                  os.path.join(root, "rt", "spa"),
                  os.path.join(root, "frontend", "dist")]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "index.html")):
            return os.path.abspath(candidate)
    return None
