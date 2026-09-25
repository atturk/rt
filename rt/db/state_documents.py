"""
rt.db.state_documents
Documenti JSON di stato nel DB (RT4-B3), al posto dei file dello stato Telegram
(active_sessions.json, registry.json, awaiting_feedback.json, ...).

Con il DB attivo la prima lettura importa il file esistente e lo rinomina in
<nome>.migrated (mai cancellato); da lì in poi legge e scrive solo il DB. Senza DB i moduli
chiamanti usano i file esattamente come prima (read_document restituisce NO_DATABASE,
write_document False).
"""
import json
import logging
import os
from typing import Any

from rt.db.engine import get_database
from rt.db.models import StateDocument
from rt.db.session import session_scope

logger = logging.getLogger(__name__)

NO_DATABASE = object()
MISSING = object()
MIGRATED_SUFFIX = ".migrated"


def document_key(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def read_document(path: str) -> Any:
    """Contenuto del documento, MISSING se non esiste, NO_DATABASE senza DB."""
    db = get_database()
    if db is None:
        return NO_DATABASE
    key = document_key(path)
    imported = False
    with session_scope(db) as session:
        row = session.get(StateDocument, key)
        if row is not None:
            return row.payload
        if not os.path.isfile(path):
            return MISSING
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            # file illeggibile: resta dov'è e il chiamante lo tratta come prima
            logger.warning("Stato non importato nel database (%s): %s", os.path.basename(path), exc)
            return NO_DATABASE
        session.add(StateDocument(key=key, payload=payload))
        imported = True
    if imported:
        try:
            os.replace(path, path + MIGRATED_SUFFIX)
        except OSError as exc:
            logger.warning("Impossibile rinominare %s dopo l'import: %s", path, exc)
    return payload


def write_document(path: str, payload: Any) -> bool:
    """Salva il documento nel DB. False senza DB (il chiamante scrive il file)."""
    db = get_database()
    if db is None:
        return False
    with session_scope(db) as session:
        row = session.get(StateDocument, document_key(path))
        if row is None:
            session.add(StateDocument(key=document_key(path), payload=payload))
        else:
            row.payload = payload
    return True
