"""
rt.telegram.audio_sent
Tracciamento e deduplica dei clip audio già inviati via Telegram per ciascun range/unità.
Persistito in modo atomico in <lesson_dir>/telegram_audio_sent.json.
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any
from rt.core.lesson_paths import lesson_path


def _get_audio_sent_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "telegram_audio_sent.json")


def _load_all_sent(lesson_dir: str) -> Dict[str, Any]:
    path = _get_audio_sent_path(lesson_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all_sent(lesson_dir: str, data: Dict[str, Any]) -> None:
    path = _get_audio_sent_path(lesson_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def get_sent_audio(lesson_dir: str, start_segment_id: str, end_segment_id: str) -> Optional[Dict[str, Any]]:
    """
    Verifica se per il range indicato (start_segment_id - end_segment_id) è già stato inviato
    un audio su Telegram per questa lezione. Ritorna il dizionario registrato (con message_id) o None.
    """
    key = f"{start_segment_id}-{end_segment_id}"
    all_sent = _load_all_sent(lesson_dir)
    return all_sent.get(key)


def record_sent_audio(lesson_dir: str, start_segment_id: str, end_segment_id: str, message_id: int) -> None:
    """
    Registra l'invio di un clip audio per il range specificato, associandolo al message_id di Telegram.
    Scrittura atomica su disco.
    """
    key = f"{start_segment_id}-{end_segment_id}"
    all_sent = _load_all_sent(lesson_dir)
    all_sent[key] = {
        "message_id": message_id,
        "recorded_at": datetime.now().isoformat(),
    }
    _save_all_sent(lesson_dir, all_sent)
