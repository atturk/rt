"""
rt.db.engine
Risoluzione dell'URL del database, creazione dell'engine e migrazioni Alembic.

Ordine di risoluzione dell'URL:
1. variabile d'ambiente RT_DATABASE_URL ("off" disattiva il DB per il processo);
2. database_url in config/general.yaml;
3. SQLite in <lessons_root>/.rt/rt.db, oppure ~/.rt/rt.db se lessons_root non è impostato.

Il DB si crea solo in modo esplicito (rt db upgrade/sync, avvio di web e daemon Telegram):
get_database() senza create=True restituisce None finché il file SQLite non esiste, così un
'rt run' su una macchina senza DB si comporta esattamente come prima.
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


def _configure_sqlite(engine: Engine) -> None:
    """WAL, foreign key e busy_timeout per ogni connessione; transazioni BEGIN IMMEDIATE
    così CLI, daemon e web che scrivono insieme si mettono in coda invece di fallire."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        try:
            if sqlite_file(str(engine.url)):
                cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
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


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def get_database(create: bool = False, url: Optional[str] = None) -> Optional[Database]:
    """Database pronto all'uso, oppure None se disattivato, assente (e create=False) o rotto.

    create=True applica le migrazioni (e crea il file SQLite); senza, un DB con migrazioni
    arretrate viene aggiornato solo se esiste già. Il risultato è in cache per processo."""
    try:
        if not url:
            # load_config legge i YAML: l'URL si risolve una volta per processo (e cwd).
            key = (os.environ.get(ENV_VAR), os.getcwd())
            if key not in _url_cache:
                _url_cache[key] = resolve_database_url()
            url = _url_cache[key]
    except Exception as exc:  # config illeggibile: RT continua con i soli file
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
            engine = create_db_engine(url)
            if create or current_revision(engine) != head_revision():
                upgrade_database(url, engine)
            db = Database(url=url, engine=engine, sessions=sessionmaker(bind=engine, expire_on_commit=False))
        except Exception as exc:
            _warn_once(url, f"Database non disponibile, RT usa solo i file: {exc}")
            return None
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
