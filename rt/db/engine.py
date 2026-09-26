"""
rt.db.engine
Risoluzione dell'URL del database, creazione dell'engine e migrazioni Alembic.

Ordine di risoluzione dell'URL:
1. variabile d'ambiente RT_DATABASE_URL ("off" disattiva il DB per il processo);
2. database_url in config/general.yaml;
3. SQLite in <lessons_root>/.rt/rt.db, oppure ~/.rt/rt.db se lessons_root non è impostato.

Dalla fase D il DB è sempre attivo: ogni comando rt chiama rt.db.bootstrap.ensure_database(),
che crea il file se manca e applica le migrazioni pendenti sotto un file lock (e importa le
lezioni esistenti al primo avvio). Se il DB è illeggibile quel comando si ferma con
DatabaseUnavailable e le istruzioni per ripristinarlo. get_database() resta la via tollerante
per il codice di libreria: None se il DB è disattivato, assente (senza create=True) o rotto.
"""
import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

ENV_VAR = "RT_DATABASE_URL"
DISABLED_VALUES = {"off", "none", "disabled", "0", "false"}
SQLITE_BUSY_TIMEOUT_MS = 30000
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


@dataclass
class Database:
    url: str
    engine: Engine
    sessions: sessionmaker


_cache: Dict[str, Optional[Database]] = {}
_url_cache: Dict[tuple, Optional[str]] = {}
_cache_lock = threading.RLock()
_warned: set = set()


def default_sqlite_path(lessons_root: Optional[str]) -> str:
    base = os.path.expanduser(lessons_root) if lessons_root else os.path.expanduser("~")
    return os.path.join(os.path.abspath(base), ".rt", "rt.db")


def resolve_database_url(config=None) -> Optional[str]:
    """URL del database o None se disattivato."""
    env = os.environ.get(ENV_VAR)
    if env is not None and env.strip():
        return None if env.strip().lower() in DISABLED_VALUES else env.strip()
    if config is None:
        from rt.core.config import load_config
        config = load_config()
    url = getattr(config, "database_url", None)
    if url:
        return None if str(url).strip().lower() in DISABLED_VALUES else str(url).strip()
    return "sqlite:///" + default_sqlite_path(config.telegram.lessons_root)


def sqlite_file(url: str) -> Optional[str]:
    """Percorso del file per un URL SQLite su file, None per memoria o altri backend."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    db = parsed.database
    if not db or db == ":memory:" or db.startswith("file::memory:"):
        return None
    return db


def _enable_wal(cur) -> None:
    """PRAGMA journal_mode=WAL con i tentativi: se un altro processo sta aprendo lo stesso DB
    nuovo (es. 'rt web' avvia API e worker insieme), SQLite può rispondere 'database is locked'
    subito, senza passare dal busy_timeout. Si riprova fino allo stesso limite."""
    import sqlite3
    import time
    deadline = time.monotonic() + SQLITE_BUSY_TIMEOUT_MS / 1000
    while True:
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _configure_sqlite(engine: Engine) -> None:
    """WAL, foreign key e busy_timeout per ogni connessione; transazioni BEGIN IMMEDIATE
    così CLI, daemon e web che scrivono insieme si mettono in coda invece di fallire."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        try:
            # busy_timeout prima di tutto: il passaggio a WAL chiede un lock e, con più processi
            # che aprono insieme un DB nuovo, senza attesa fallirebbe subito con 'database is locked'
            cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            if sqlite_file(str(engine.url)):
                _enable_wal(cur)
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        if conn.get_execution_options().get("rt_read_only"):
            conn.exec_driver_sql("BEGIN")
        else:
            conn.exec_driver_sql("BEGIN IMMEDIATE")


def create_db_engine(url: str) -> Engine:
    kwargs = {}
    if make_url(url).get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}
        if not sqlite_file(url):
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _configure_sqlite(engine)
    return engine


def alembic_config(url: str, engine: Optional[Engine] = None):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if engine is not None:
        cfg.attributes["engine"] = engine
    return cfg


def upgrade_database(url: str, engine: Optional[Engine] = None) -> None:
    """Applica tutte le migrazioni Alembic (crea la cartella del file SQLite se manca)."""
    from alembic import command
    path = sqlite_file(url)
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    own_engine = engine is None
    engine = engine or create_db_engine(url)
    try:
        command.upgrade(alembic_config(url, engine), "head")
    finally:
        if own_engine:
            engine.dispose()


def current_revision(engine: Engine) -> Optional[str]:
    from alembic.runtime.migration import MigrationContext
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision() -> str:
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


class DatabaseUnavailable(RuntimeError):
    """Il database non si apre o non si migra: RT non può proseguire (la coda dei job ci vive
    dentro). Il messaggio spiega come ripristinarlo."""

    def __init__(self, url: str, cause: BaseException):
        self.url = url
        self.cause = cause
        super().__init__(restore_instructions(url, cause))


def restore_instructions(url: str, cause: BaseException) -> str:
    path = sqlite_file(url)
    if not path:
        where = url.split("@")[-1]
        return (f"Database di RT non raggiungibile ({where}): {cause}\n"
                "Controlla che il server del database sia attivo e che database_url sia corretto, "
                "poi rilancia il comando.")
    return (f"Database di RT illeggibile: {path}\n"
            f"Causa: {cause}\n"
            "Le lezioni sono al sicuro nelle loro cartelle. Per ripristinare il database:\n"
            f"  - da un backup:       cp /percorso/del/backup/rt.db \"{path}\"\n"
            f"  - oppure dai file:    mv \"{path}\" \"{path}.rotto\"   e rilancia il comando:\n"
            "    RT ricrea il database e reimporta da solo lezioni, decisioni e costi.")


def migration_lock_path(url: str) -> Optional[str]:
    path = sqlite_file(url)
    return os.path.abspath(path) + ".migrate.lock" if path else None


def open_database(url: str, create: bool = True) -> Database:
    """Apre il DB applicando le migrazioni pendenti; solleva DatabaseUnavailable se non riesce.
    Le migrazioni girano sotto un file lock accanto al file SQLite, così due processi rt
    avviati insieme non migrano in parallelo; se è già tutto aggiornato il lock non si prende
    (costo: la sola lettura della revisione corrente)."""
    engine = None
    try:
        path = sqlite_file(url)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        engine = create_db_engine(url)
        head = head_revision()
        if current_revision(engine) != head:
            lock = migration_lock_path(url)
            if lock:
                from rt.core.filelock import file_lock
                os.makedirs(os.path.dirname(lock), exist_ok=True)
                with file_lock(lock, retries=600, backoff=0.05, stale_sec=300):
                    if current_revision(engine) != head:
                        upgrade_database(url, engine)
            else:
                upgrade_database(url, engine)
        return Database(url=url, engine=engine, sessions=sessionmaker(bind=engine, expire_on_commit=False))
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        raise DatabaseUnavailable(url, exc) from exc


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def current_database_url() -> Optional[str]:
    """URL del DB per questo processo (in cache per variabile d'ambiente e cwd: load_config
    legge i YAML). None se disattivato."""
    key = (os.environ.get(ENV_VAR), os.getcwd())
    if key not in _url_cache:
        _url_cache[key] = resolve_database_url()
    return _url_cache[key]


def get_database(create: bool = False, url: Optional[str] = None) -> Optional[Database]:
    """Database pronto all'uso, oppure None se disattivato, assente (e create=False) o rotto.

    create=True applica le migrazioni (e crea il file SQLite); senza, un DB con migrazioni
    arretrate viene aggiornato solo se esiste già. Il risultato è in cache per processo."""
    try:
        url = url or current_database_url()
    except Exception as exc:  # config illeggibile: il chiamante decide cosa fare senza DB
        _warn_once("resolve", f"Database non disponibile (configurazione): {exc}")
        return None
    if not url:
        return None
    with _cache_lock:
        cached = _cache.get(url)
        if cached is not None:
            return cached
        path = sqlite_file(url)
        if path and not os.path.isfile(path) and not create:
            return None
        try:
            db = open_database(url)
        except DatabaseUnavailable as exc:
            _warn_once(url, f"Database non disponibile: {exc.cause}")
            return None
        _cache[url] = db
        return db


def require_database(url: Optional[str] = None) -> Database:
    """Come get_database(create=True) ma senza ripiego: solleva DatabaseUnavailable (o
    RuntimeError se il DB è disattivato). Per chi non può funzionare senza DB (coda job)."""
    url = url or current_database_url()
    if not url:
        raise RuntimeError("Database disattivato (RT_DATABASE_URL=off o database_url: off): "
                           "la coda dei job richiede il database.")
    with _cache_lock:
        cached = _cache.get(url)
        if cached is not None:
            return cached
        db = open_database(url)
        _cache[url] = db
        return db


def reset_database_cache() -> None:
    """Chiude gli engine in cache (test, cambio di configurazione)."""
    with _cache_lock:
        for db in _cache.values():
            if db is not None:
                db.engine.dispose()
        _cache.clear()
        _url_cache.clear()
        _warned.clear()
    from rt.storage import fs
    fs.reset_cache()
