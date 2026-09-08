"""
rt.telegram.conversation_state
Stato "sto aspettando il feedback testuale di questa chat per questo short_id",
persistito su disco per sopravvivere a un riavvio del daemon.
"""
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, "awaiting_feedback.json")


def _load(state_dir: str) -> Dict[str, Any]:
    path = _path(state_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(state_dir: str, data: Dict[str, Any]) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def set_awaiting_feedback(state_dir: str, chat_id: int, short_id: str, lesson_dir: str,
                           kind: str = "outline_feedback", extra: Optional[Dict[str, Any]] = None) -> None:
    data = _load(state_dir)
    entry = {"short_id": short_id, "lesson_dir": lesson_dir, "kind": kind, "since": datetime.now().isoformat()}
    if extra:
        entry["extra"] = extra
    data[str(chat_id)] = entry
    _save(state_dir, data)



def get_awaiting_feedback(state_dir: str, chat_id: int) -> Optional[Dict[str, Any]]:
    return _load(state_dir).get(str(chat_id))


def clear_awaiting_feedback(state_dir: str, chat_id: int) -> None:
    data = _load(state_dir)
    data.pop(str(chat_id), None)
    _save(state_dir, data)
