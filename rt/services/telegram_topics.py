"""
rt.services.telegram_topics
Rilevamento dei topic del gruppo Telegram (come "Ascolta topic per 20 secondi" della web
Gradio): legge i messaggi in arrivo al bot con getUpdates e restituisce chat e topic visti.
Usato dal job API telegram_listen_topics (RT4-F5). Il token non compare mai nei messaggi.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

TELEGRAM_API = "https://api.telegram.org"


class TopicListenError(Exception):
    """Errore leggibile per l'utente (mai il token)."""


def listen_topics(token: Optional[str] = None, seconds: int = 20) -> Dict[str, Any]:
    """Ascolta per `seconds` secondi: {"chat_id": str|None, "chats": int, "topics": [int]}."""
    import requests
    from rt.core.config import load_env_file
    from rt.telegram.daemon_status import is_daemon_running
    if is_daemon_running():
        raise TopicListenError("Il bot è già in ascolto. Ferma il demone prima di cercare nuovi topic.")
    load_env_file()
    token = (token or os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")).strip()
    if not token or token == "test-disabled-token":
        raise TopicListenError("Salva prima il token del bot.")
    base = os.environ.get("RT_TELEGRAM_API_URL", TELEGRAM_API).rstrip("/")
    try:
        response = requests.get(f"{base}/bot{token}/getUpdates",
                                params={"timeout": seconds, "limit": 50}, timeout=seconds + 5)
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise TopicListenError("Impossibile contattare Telegram per il rilevamento dei topic.") from None
    if response.status_code == 409:
        raise TopicListenError("Un altro processo sta già ascoltando questo bot.")
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise TopicListenError("Telegram non ha accettato la richiesta. Verifica token e permessi del bot.")
    messages = [item.get("message") or item.get("channel_post") for item in payload.get("result", [])
                if isinstance(item, dict)]
    messages = [m for m in messages if isinstance(m, dict)]
    chats = {m.get("chat", {}).get("id") for m in messages} - {None}
    topics = sorted({m.get("message_thread_id") for m in messages} - {None})
    return {"chat_id": str(next(iter(chats))) if len(chats) == 1 else None,
            "chats": len(chats), "topics": topics}
