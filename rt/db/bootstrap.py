"""
rt.db.bootstrap
Avvio del database per ogni comando rt.

ensure_database() crea il DB se manca e applica le migrazioni pendenti (sotto lock), senza
scansionare o importare implicitamente l'archivio a cartelle. La conversione dei dati esistenti
resta un'azione esplicita. Se il DB è illeggibile solleva DatabaseUnavailable con le istruzioni
per ripristinarlo: dalla fase D RT non ha più il ripiego "solo file", perché la coda dei job
vive nel database.
"""
from typing import Optional

from rt.db.engine import Database, current_database_url, require_database

def ensure_database() -> Optional[Database]:
    """DB pronto e migrato, oppure None se disattivato in modo esplicito.

    Per impostazione predefinita non importa né scandisce le cartelle delle lezioni.
    Solleva DatabaseUnavailable se il DB esiste ma non si apre o non si migra.
    """
    if not current_database_url():
        return None
    return require_database()
