"""
rt.telegram.recall_lessons
Override esplicito e opzionale per /recall da Telegram: mappa materia (stessa chiave
usata in 'topics' di config/general.yaml) -> cartella lezione da usare, al posto del
tracking automatico dell'ultima build completata (rt.telegram.last_lesson).

Letto da config/telegram/recall_lessons.yaml se esiste. Il file NON è un job di
routing LLM: find_job_yaml_paths() lo esclude esplicitamente (vedi rt.core.config).
Se il file manca, o non ha una entry per la materia richiesta, il chiamante deve
ricadere sul comportamento automatico esistente — nessuna rottura per chi non lo usa.
"""
import os
from typing import Optional

import yaml


def _find_recall_lessons_yaml() -> Optional[str]:
    from rt.core.config import _default_project_root

    for config_dir in (
        os.path.join(os.getcwd(), "config"),
        os.path.join(_default_project_root(), "config"),
    ):
        candidate = os.path.join(config_dir, "telegram", "recall_lessons.yaml")
        if os.path.isfile(candidate):
            return candidate
    return None


def get_lesson_override(materia: str) -> Optional[str]:
    """Ritorna la cartella lezione configurata esplicitamente per `materia` (stessa
    normalizzazione case-insensitive di resolve_topic_id), o None se il file di
    override non esiste o non ha una entry per questa materia."""
    path = _find_recall_lessons_yaml()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f.read())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    materia_key = str(materia).strip().upper()
    for key, value in data.items():
        if str(key).strip().upper() == materia_key and isinstance(value, str) and value.strip():
            return value
    return None
