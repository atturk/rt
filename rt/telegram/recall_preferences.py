"""
rt.telegram.recall_preferences
Stile di domanda attivo globale per l'active recall (quiz | mirata | vasta),
persistito in <state_dir>/recall_preferences.json. Stato dinamico mutabile
via comando bot (/recall_style), non config statica.
"""
import os
import json
from typing import Optional

from rt.db.state_documents import MISSING, NO_DATABASE, read_document, write_document

DEFAULT_STYLE = "quiz"
VALID_STYLES = ("quiz", "mirata", "vasta")


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, "recall_preferences.json")


def get_active_style(state_dir: str) -> str:
    path = _path(state_dir)
    try:
        data = read_document(path)
        if data is MISSING:
            return DEFAULT_STYLE
        if data is NO_DATABASE:
            if not os.path.isfile(path):
                return DEFAULT_STYLE
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        style = data.get("active_style")
        return style if style in VALID_STYLES else DEFAULT_STYLE
    except Exception:
        return DEFAULT_STYLE


def set_active_style(state_dir: str, style: str) -> None:
    if style not in VALID_STYLES:
        raise ValueError(f"Stile non valido: '{style}'. Valori ammessi: {', '.join(VALID_STYLES)}.")
    path = _path(state_dir)
    if write_document(path, {"active_style": style}):
        return
    os.makedirs(state_dir, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"active_style": style}, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
