"""
rt.telegram.client
Client HTTP minimale per l'invio di messaggi e clip audio (usa `requests`, già dipendenza del
progetto). Deliberatamente NON usa python-telegram-bot: questo lato è invocato da
processi effimeri (rt run) che devono solo mandare 1-2 messaggi, non gestire un
intero Application asyncio.
"""
import time
from typing import Optional, Dict, Any
import requests
from rt.telegram.config import TelegramConfig

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramAPIError(Exception):
    pass


def _execute_request(method: str, url: str, request_kwargs: Dict[str, Any], max_retries: int = 1) -> Dict[str, Any]:
    """Esegue la richiesta HTTP con gestione centralizzata del rate limit (429) e retry."""
    attempts = 0
    while True:
        try:
            resp = requests.post(url, **request_kwargs)
        except requests.RequestException as e:
            raise TelegramAPIError(f"Errore di rete verso Telegram ({method}): {e}") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise TelegramAPIError(f"Risposta non JSON da Telegram ({method}): {resp.text[:200]}") from e
        if not data.get("ok"):
            error_code = data.get("error_code") or resp.status_code
            if error_code == 429 and attempts < max_retries:
                attempts += 1
                retry_after = data.get("parameters", {}).get("retry_after", 1)
                try:
                    retry_sec = float(retry_after)
                except (ValueError, TypeError):
                    retry_sec = 1.0
                time.sleep(retry_sec)
                # Se sono stati passati file aperti, ripristina la posizione iniziale del puntatore
                if "files" in request_kwargs and isinstance(request_kwargs["files"], dict):
                    for f in request_kwargs["files"].values():
                        if hasattr(f, "seek"):
                            f.seek(0)
                        elif isinstance(f, tuple) and len(f) > 1 and hasattr(f[1], "seek"):
                            f[1].seek(0)
                continue
            raise TelegramAPIError(f"Telegram API error ({method}): {data.get('description', data)}")
        return data["result"]


def _call(cfg: TelegramConfig, method: str, payload: Dict[str, Any], timeout: float = 15.0, max_retries: int = 1) -> Dict[str, Any]:
    url = _API_BASE.format(token=cfg.bot_token, method=method)
    return _execute_request(method, url, {"json": payload, "timeout": timeout}, max_retries=max_retries)


def send_message(
    cfg: TelegramConfig,
    text: str,
    reply_markup: Optional[dict] = None,
    message_thread_id: Optional[int] = None,
    reply_to_message_id: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": cfg.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    return _call(cfg, "sendMessage", payload)


def send_voice(
    cfg: TelegramConfig,
    voice_path: str,
    caption: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
    timeout: float = 30.0,
    max_retries: int = 1
) -> Dict[str, Any]:
    """Invia un file audio vocale multipart tramite il metodo sendVoice dell'API Telegram."""
    url = _API_BASE.format(token=cfg.bot_token, method="sendVoice")
    data: Dict[str, Any] = {
        "chat_id": cfg.chat_id,
    }
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    if reply_to_message_id is not None:
        data["reply_to_message_id"] = reply_to_message_id
    if message_thread_id is not None:
        data["message_thread_id"] = message_thread_id

    with open(voice_path, "rb") as f:
        return _execute_request(
            "sendVoice",
            url,
            {"data": data, "files": {"voice": f}, "timeout": timeout},
            max_retries=max_retries
        )


def edit_message_reply_markup(cfg: TelegramConfig, message_id: int, reply_markup: Optional[dict] = None) -> Dict[str, Any]:
    payload = {
        "chat_id": cfg.chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup or {"inline_keyboard": []},
    }
    return _call(cfg, "editMessageReplyMarkup", payload)
