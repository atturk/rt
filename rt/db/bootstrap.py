"""
rt.db.bootstrap
Avvio del database per ogni comando rt: l'utente non lancia mai comandi di database a mano.

ensure_database() crea il DB se manca, applica le migrazioni pendenti (sotto lock) e, la
prima volta, importa le lezioni già presenti in lessons_root. Se il DB è illeggibile solleva
DatabaseUnavailable con le istruzioni per ripristinarlo: dalla fase D RT non ha più il
ripiego "solo file", perché la coda dei job vive nel database.
"""
import logging
import os
from typing import Callable, Optional

from rt.db.engine import Database, current_database_url, require_database

logger = logging.getLogger(__name__)

INITIAL_IMPORT_KEY = "db.initial_import_done"


def ensure_database(
    auto_import: bool = True,
    lessons_root: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Optional[Database]:
    """DB pronto e migrato, oppure None se disattivato in modo esplicito (RT_DATABASE_URL=off
    o database_url: off: solo per sviluppo e test). Solleva DatabaseUnavailable se il DB
    esiste ma non si apre o non si migra."""
    if not current_database_url():
        return None
    db = require_database()
    if auto_import:
        initial_import(db, lessons_root=lessons_root, on_progress=on_progress)
    return db


def _configured_lessons_root() -> Optional[str]:
    try:
        from rt.core.config import load_config
        root = load_config().telegram.lessons_root
    except Exception:
        return None
    return root or None


def initial_import(
    db: Database,
    lessons_root: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """Importa una volta sola le lezioni di lessons_root (come 'rt db sync'). Si segna come
    fatto in settings solo a scansione conclusa, così un'importazione interrotta riparte al
    comando successivo (le lezioni con errori restano nei log). None se non c'era nulla da fare."""
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope

    with session_scope(db) as s:
        if SettingRepository(s).get(INITIAL_IMPORT_KEY):
            return None
    root = lessons_root or _configured_lessons_root()
    if not root:
        return None  # nessuna cartella lezioni ancora: si riprova quando viene configurata
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return None

    from rt.db.sync import lesson_dirs, sync_all
    count = len(lesson_dirs(root))
    if count and on_progress:
        on_progress(f"📚 Primo avvio con il database: importo {count} lezioni da {root}...")
    result = sync_all(db, root)
    for err in result["errors"]:
        logger.warning("Import iniziale: %s", err)
    with session_scope(db) as s:
        SettingRepository(s).set(INITIAL_IMPORT_KEY, {"lessons_root": root, "synced": result["synced"]})
    if count and on_progress:
        on_progress(f"✅ Lezioni importate nel database: {result['synced']}")
    return result
