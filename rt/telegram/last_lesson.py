"""
rt.telegram.last_lesson
Traccia l'ultima lezione con build completata per ciascun topic Telegram, così
/recall lanciato da Telegram senza argomenti sa su quale cartella operare.
Non è un indice/browser di lezioni: solo "l'ultima" per topic, aggiornato ad
ogni notifica di build completata (vedi rt.telegram.notify.notify_build_completed).
"""
import os
import json
from datetime import datetime
from typing import Optional, Union


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, "last_lesson_per_topic.json")


def _key(chat_id: Union[int, str], thread_id: Optional[Union[int, str]]) -> str:
    t_key = "general" if thread_id is None else str(thread_id)
    return f"{chat_id}:{t_key}"


def _load(state_dir: str) -> dict:
    path = _path(state_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def record_last_lesson(state_dir: str, chat_id: Union[int, str], thread_id: Optional[Union[int, str]], lesson_dir: str) -> None:
    os.makedirs(state_dir, exist_ok=True)
    data = _load(state_dir)
    data[_key(chat_id, thread_id)] = {
        "lesson_dir": os.path.abspath(lesson_dir),
        "updated_at": datetime.now().isoformat(),
    }
    path = _path(state_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def get_last_lesson(state_dir: str, chat_id: Union[int, str], thread_id: Optional[Union[int, str]]) -> Optional[str]:
    entry = _load(state_dir).get(_key(chat_id, thread_id))
    return entry.get("lesson_dir") if entry else None
