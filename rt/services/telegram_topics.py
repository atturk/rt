"""
rt.services.telegram_topics
Rilevamento dei topic del gruppo Telegram (come "Ascolta topic per 20 secondi" della web
Gradio): legge i messaggi in arrivo al bot con getUpdates e restituisce chat e topic visti,
con il nome del topic quando il Bot API lo include (RT4-FA6). Usato dal job API
telegram_listen_topics (RT4-F5). Qui anche il messaggio di prova in un topic e la
cancellazione dei soli messaggi ricevuti durante un ascolto. Il token non compare mai nei
messaggi. Se il demone del bot è attivo l'endpoint risponde 409 prima di accodare (qui niente
rt.telegram: i servizi restano indipendenti dall'interfaccia, vedi tests/test_layering.py).
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional

TELEGRAM_API = "https://api.telegram.org"

# Telegram non permette di cancellare messaggi più vecchi di 48 ore.
DELETE_MAX_AGE_SECONDS = 48 * 3600

# Messaggi di servizio: non si cancellano mai (quello di creazione è la radice del topic).
SERVICE_KEYS = frozenset({
    "forum_topic_created", "forum_topic_edited", "forum_topic_closed", "forum_topic_reopened",
    "general_forum_topic_hidden", "general_forum_topic_unhidden", "new_chat_members", "left_chat_member",
    "new_chat_title", "new_chat_photo", "delete_chat_photo", "group_chat_created", "supergroup_chat_created",
    "pinned_message", "migrate_to_chat_id", "migrate_from_chat_id", "message_auto_delete_timer_changed",
    "video_chat_scheduled", "video_chat_started", "video_chat_ended", "write_access_allowed",
})


class TopicListenError(Exception):
    """Errore leggibile per l'utente (mai il token)."""


def _token(token: Optional[str] = None) -> str:
    from rt.core.config import load_env_file
    load_env_file()
    token = (token or os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")).strip()
    if not token or token == "test-disabled-token":
        raise TopicListenError("Salva prima il token del bot.")
    return token


def _chat_id() -> str:
    from rt.core.config import load_env_file
    load_env_file()
    chat_id = (os.environ.get("RT_TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        raise TopicListenError("Salva prima il Chat ID del gruppo.")
    return chat_id


def _base() -> str:
    return os.environ.get("RT_TELEGRAM_API_URL", TELEGRAM_API).rstrip("/")


def _post(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Chiamata al Bot API: {"ok": bool, "description": str, "result": ...}; mai eccezioni col token."""
    import requests
    try:
        response = requests.post(f"{_base()}/bot{token}/{method}", json=payload, timeout=15)
        data = response.json()
    except (requests.RequestException, ValueError):
        return {"ok": False, "description": "Impossibile contattare Telegram."}
    if not isinstance(data, dict):
        return {"ok": False, "description": "Risposta di Telegram non valida."}
    if not data.get("ok"):
        description = str(data.get("description") or "richiesta rifiutata").replace(token, "***")
        return {"ok": False, "description": description[:200]}
    return data


def topic_names(messages: Iterable[Dict[str, Any]]) -> Dict[int, str]:
    """Nome di ogni topic visto nei messaggi: dal messaggio di servizio forum_topic_created (o
    forum_topic_edited, che vince perché più recente) e dal reply_to_message dei messaggi nel
    topic, che per un messaggio non in risposta è proprio quello di creazione."""
    created: Dict[int, str] = {}
    edited: Dict[int, str] = {}
    for m in messages:
        thread = m.get("message_thread_id")
        for source in (m, m.get("reply_to_message") or {}):
            if not isinstance(source, dict):
                continue
            topic = thread if thread is not None else source.get("message_id")
            if topic is None:
                continue
            name = ((source.get("forum_topic_created") or {}).get("name") or "").strip()
            if name and (source is m or source.get("message_id") == thread):
                created[topic] = name
            renamed = ((source.get("forum_topic_edited") or {}).get("name") or "").strip()
            if renamed and source is m:
                edited[topic] = renamed
    return {**created, **edited}


def _is_service(message: Dict[str, Any]) -> bool:
    return any(key in message for key in SERVICE_KEYS)


def listen_topics(token: Optional[str] = None, seconds: int = 20) -> Dict[str, Any]:
    """Ascolta per `seconds` secondi: {"chat_id": str|None, "chats": int, "topics": [int],
    "names": {topic: nome}, "messages": [{chat_id, message_id, date, topic_id}]}.
    In "messages" solo i messaggi degli utenti (niente messaggi di servizio): sono quelli che
    "Cancella i messaggi di rilevamento" può eliminare."""
    import requests
    token = _token(token)
    try:
        response = requests.get(f"{_base()}/bot{token}/getUpdates",
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
    names = topic_names(messages)
    received = [{"chat_id": str(m["chat"]["id"]), "message_id": int(m["message_id"]),
                 "date": int(m.get("date") or 0), "topic_id": m.get("message_thread_id")}
                for m in messages
                if not _is_service(m) and m.get("message_id") is not None and (m.get("chat") or {}).get("id") is not None]
    return {"chat_id": str(next(iter(chats))) if len(chats) == 1 else None,
            "chats": len(chats), "topics": topics,
            "names": {str(t): names[t] for t in topics if t in names},
            "messages": received}


def _normalize(text: str) -> str:
    import unicodedata
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def known_materie() -> List[str]:
    """Materie note a RT: quelle dei topic salvati e quelle delle lezioni nel database."""
    from rt.core.config import load_config
    found = {str(k).strip().upper() for k in (load_config().telegram.topics or {})}
    try:
        from sqlalchemy import select
        from rt.db.engine import get_database
        from rt.db.models import Lesson
        from rt.db.session import session_scope
        db = get_database()
        if db is not None:
            with session_scope(db) as s:
                found |= {str(m).strip().upper() for m in s.scalars(select(Lesson.materia).distinct())}
    except Exception:  # noqa: BLE001 - senza DB bastano i topic salvati
        pass
    return sorted(m for m in found if m)


def match_materia(name: str, materie: Iterable[str]) -> Optional[str]:
    """La materia che coincide con il nome del topic (maiuscole e accenti non contano)."""
    target = _normalize(name)
    return next((m for m in materie if target and _normalize(m) == target), None)


def send_topic_test(topic_id: int, materia: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Invia 'Questo è il topic di <materia>' nel topic del gruppo salvato: {"ok", "message", "text"}."""
    token = _token(token)
    chat_id = _chat_id()
    label = materia.strip().upper() or f"{topic_id}"
    text = f"Questo è il topic di {label}"
    data = _post(token, "sendMessage", {"chat_id": chat_id, "text": text, "message_thread_id": int(topic_id)})
    if not data.get("ok"):
        return {"ok": False, "text": text, "message": f"Messaggio non inviato: {data['description']}"}
    return {"ok": True, "text": text, "message": f"Messaggio inviato nel topic {topic_id}."}


def _delete_reason(description: str) -> str:
    text = description.lower()
    if "not found" in text:
        return "non trovato (già cancellato?)"
    if "can't be deleted" in text or "not enough rights" in text:
        return "Telegram non ne permette la cancellazione: il bot deve essere amministratore del gruppo"
    return description


def delete_listen_messages(messages: List[Dict[str, Any]], token: Optional[str] = None,
                           now: Optional[float] = None) -> Dict[str, Any]:
    """Cancella (deleteMessage) esattamente i messaggi indicati, cioè quelli ricevuti durante un
    ascolto. {"deleted": [message_id], "failed": [{"message_id", "reason"}]}. I messaggi più
    vecchi di 48 ore non si tentano nemmeno: Telegram li rifiuterebbe."""
    token = _token(token)
    now = time.time() if now is None else now
    deleted: List[int] = []
    failed: List[Dict[str, Any]] = []
    for item in messages:
        message_id = int(item["message_id"])
        date = int(item.get("date") or 0)
        if date and now - date > DELETE_MAX_AGE_SECONDS:
            failed.append({"message_id": message_id, "reason": "più vecchio di 48 ore (limite di Telegram)"})
            continue
        data = _post(token, "deleteMessage", {"chat_id": item["chat_id"], "message_id": message_id})
        if data.get("ok"):
            deleted.append(message_id)
        else:
            failed.append({"message_id": message_id, "reason": _delete_reason(data["description"])})
    return {"deleted": deleted, "failed": failed}
