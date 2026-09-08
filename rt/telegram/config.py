"""
rt.telegram.config
Credenziali Telegram lette esclusivamente da environment variables / .env,
mai da RTConfig (che contiene solo parametri non segreti).
"""
import os
from dataclasses import dataclass


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
