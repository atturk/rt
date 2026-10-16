"""
rt.telegram.client
Client HTTP minimale della Bot API (usa `requests`, già dipendenza del progetto): RT manda solo
messaggi di notifica e legge gli ultimi messaggi ricevuti per trovare la chat personale.
"""
import os
import time
from typing import Dict, Any
import requests
from rt.telegram.config import TelegramConfig

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api_url(token: str, method: str) -> str:
    """RT_TELEGRAM_API_URL sostituisce https://api.telegram.org (Bot API finta nei test)."""
    base = os.environ.get("RT_TELEGRAM_API_URL")
    if base:
        return f"{base.rstrip('/')}/bot{token}/{method}"
    return _API_BASE.format(token=token, method=method)


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
                continue
            raise TelegramAPIError(f"Telegram API error ({method}): {data.get('description', data)}")
        return data["result"]


def _call(cfg: TelegramConfig, method: str, payload: Dict[str, Any], timeout: float = 15.0, max_retries: int = 1) -> Dict[str, Any]:
    url = _api_url(cfg.bot_token, method)
    return _execute_request(method, url, {"json": payload, "timeout": timeout}, max_retries=max_retries)


def send_message(cfg: TelegramConfig, text: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": cfg.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    return _call(cfg, "sendMessage", payload)


def get_me(token: str) -> Dict[str, Any]:
    """Nome e username del bot: verifica che il token sia valido."""
    return _execute_request("getMe", _api_url(token, "getMe"), {"json": {}, "timeout": 15.0})


def get_updates(token: str) -> list:
    """Ultimi messaggi ricevuti dal bot (Telegram li tiene per 24 ore finché nessuno li legge)."""
    return _execute_request("getUpdates", _api_url(token, "getUpdates"),
                            {"json": {"allowed_updates": ["message"]}, "timeout": 15.0})
