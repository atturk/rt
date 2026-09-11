"""
rt.telegram.config
Credenziali Telegram lette esclusivamente da environment variables / .env,
mai da RTConfig (che contiene solo parametri non segreti).
"""
import os
from dataclasses import dataclass
from typing import Optional


class TelegramConfigError(Exception):
    pass


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_config() -> TelegramConfig:
    token = os.environ.get("RT_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("RT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise TelegramConfigError(
            "RT_TELEGRAM_BOT_TOKEN e/o RT_TELEGRAM_CHAT_ID mancanti nell'ambiente/.env"
        )
    return TelegramConfig(bot_token=token, chat_id=chat_id)


def _clean_topic_id(val) -> Optional[int]:
    if val is None or hasattr(val, "_mock_name"):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def resolve_topic_id(lesson_dir: str, topics: dict, misc_topic_id: Optional[int] = None) -> Optional[int]:
    """Risolve il message_thread_id del topic dedicato alla materia della lezione,
    leggendo 'materia' da info.yaml. Ritorna misc_topic_id (o None) se la materia
    non è mappata o info.yaml non è leggibile."""
    from rt.core.state import read_info_yaml
    from rt.core.lesson_paths import lesson_path
    try:
        info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    except Exception:
        return _clean_topic_id(misc_topic_id)
    materia = str(info.get("materia", "")).strip().upper()
    if not materia or not isinstance(topics, dict):
        return _clean_topic_id(misc_topic_id)
    return _clean_topic_id(topics.get(materia, misc_topic_id))


def reverse_resolve_materia(thread_id: Optional[int], topics: dict) -> Optional[str]:
    """Inversa di resolve_topic_id: la materia mappata su questo thread_id, o None se
    thread_id è il topic Generale o non corrisponde a nessuna voce di 'topics'."""
    if thread_id is None or not isinstance(topics, dict):
        return None
    return next((m for m, tid in topics.items() if tid == thread_id), None)

