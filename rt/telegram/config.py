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


def resolve_topic_id(lesson_dir: str, topics: dict) -> Optional[int]:
    """Risolve il message_thread_id del topic dedicato alla materia della lezione,
    leggendo 'materia' da info.yaml. Ritorna None (topic 'Generale') se la materia
    non è mappata o info.yaml non è leggibile."""
    import os
    from rt.core.state import read_info_yaml
    try:
        info = read_info_yaml(os.path.join(lesson_dir, "info.yaml"))
    except Exception:
        return None
    materia = str(info.get("materia", "")).strip().upper()
    if not materia or not isinstance(topics, dict):
        return None
    return topics.get(materia)

