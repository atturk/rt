"""
rt.db.llm_calls
Chiamate LLM nel DB (RT4-B3): ogni riga di llm_debug.log diventa un LlmCall della lezione,
e 'rt cost' legge dal DB quando c'è. La prima scrittura per una lezione importa l'intero
log esistente, così il DB non ha mai meno chiamate del file.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

from rt.db.engine import get_database
from rt.db.repositories import LessonRepository, LlmCallRepository
from rt.db.session import session_scope

logger = logging.getLogger(__name__)
_warned = False


def read_log_entries(lesson_dir: str) -> Optional[List[Dict[str, Any]]]:
    """Righe valide di llm_debug.log (None se il file non esiste o non si legge)."""
    from rt.core.lesson_paths import lesson_path
    path = lesson_path(lesson_dir, "llm_debug.log")
    if not os.path.isfile(path):
        return None
    entries: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue  # righe corrotte ignorate, come in rt cost
                if isinstance(record, dict):
                    entries.append(record)
    except Exception:
        return None
    return entries


def import_log_if_empty(session, lesson) -> bool:
    repo = LlmCallRepository(session)
    if repo.count_for_lesson(lesson):
        return False
    for entry in read_log_entries(lesson.path) or []:
        repo.add(lesson, entry)
    return True


def record_llm_call(lesson_dir: Optional[str], entry: Dict[str, Any]) -> None:
    """Chiamato dopo aver scritto la riga su llm_debug.log. Mai bloccante."""
    global _warned
    if not lesson_dir:
        return
    try:
        db = get_database()
        if db is None:
            return
        with session_scope(db) as session:
            lesson = LessonRepository(session).get_or_create(lesson_dir)
            if not import_log_if_empty(session, lesson):  # il log importato contiene già entry
                LlmCallRepository(session).add(lesson, entry)
    except Exception as exc:
        if not _warned:
            _warned = True
            logger.warning("Registrazione della chiamata LLM nel database non riuscita: %s", exc)


def load_entries(lesson_dir: str) -> Optional[List[Dict[str, Any]]]:
    """Chiamate della lezione dal DB, oppure None (nessun DB, lezione assente, errore)."""
    try:
        db = get_database()
        if db is None:
            return None
        with session_scope(db) as session:
            lesson = LessonRepository(session).get_by_path(lesson_dir)
            if lesson is None:
                return None
            entries = LlmCallRepository(session).entries_for_lesson(lesson)
            return entries or None
    except Exception as exc:
        logger.warning("Lettura dei costi dal database non riuscita, uso llm_debug.log: %s", exc)
        return None
