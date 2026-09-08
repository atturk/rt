"""
rt.telegram.client
Client HTTP minimale per l'invio di messaggi (usa `requests`, già dipendenza del
progetto). Deliberatamente NON usa python-telegram-bot: questo lato è invocato da
processi effimeri (rt run) che devono solo mandare 1-2 messaggi, non gestire un
intero Application asyncio.
"""
from typing import Optional, Dict, Any
import requests
from rt.telegram.config import TelegramConfig

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramAPIError(Exception):
    pass


def _call(cfg: TelegramConfig, method: str, payload: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    url = _API_BASE.format(token=cfg.bot_token, method=method)
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise TelegramAPIError(f"Errore di rete verso Telegram ({method}): {e}") from e
    try:
        data = resp.json()
    except ValueError as e:
        raise TelegramAPIError(f"Risposta non JSON da Telegram ({method}): {resp.text[:200]}") from e
    if not data.get("ok"):
        raise TelegramAPIError(f"Telegram API error ({method}): {data.get('description', data)}")
    return data["result"]


def send_message(cfg: TelegramConfig, text: str, reply_markup: Optional[dict] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": cfg.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call(cfg, "sendMessage", payload)


def edit_message_reply_markup(cfg: TelegramConfig, message_id: int, reply_markup: Optional[dict] = None) -> Dict[str, Any]:
    payload = {
        "chat_id": cfg.chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup or {"inline_keyboard": []},
    }
    return _call(cfg, "editMessageReplyMarkup", payload)
