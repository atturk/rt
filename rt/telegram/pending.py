"""
rt.telegram.pending
Stato di conferma outline per singola lezione (telegram_pending.json dentro
lesson_dir). Scritto dal daemon quando arriva una risposta, letto in polling dal
processo 'rt run' che sta aspettando.
"""
import os
import json
from datetime import datetime
from typing import Optional
from rt.core.models import TelegramPendingState, TelegramPendingStatus
from rt.core.lesson_paths import lesson_path


def get_pending_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "telegram_pending.json")


def load_pending(lesson_dir: str) -> Optional[TelegramPendingState]:
    path = get_pending_path(lesson_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return TelegramPendingState.model_validate(data)


def _save(state: TelegramPendingState, lesson_dir: str) -> None:
    path = get_pending_path(lesson_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def create_pending(lesson_dir: str, round_: int, short_id: str, outline_summary_text: str) -> TelegramPendingState:
    state = TelegramPendingState(
        round=round_,
        short_id=short_id,
        created_at=datetime.now().isoformat(),
        status=TelegramPendingStatus.PENDING,
        outline_summary_text=outline_summary_text,
    )
    _save(state, lesson_dir)
    return state


def mark_responded(
    lesson_dir: str,
    status: str,
    responded_via: str,
    feedback_text: Optional[str] = None,
) -> TelegramPendingState:
    state = load_pending(lesson_dir)
    if state is None:
        raise FileNotFoundError(f"telegram_pending.json non trovato in '{lesson_dir}'")
    state.status = TelegramPendingStatus(status)
    state.responded_via = responded_via
    state.responded_at = datetime.now().isoformat()
    if feedback_text is not None:
        state.feedback_text = feedback_text
    _save(state, lesson_dir)
    return state
