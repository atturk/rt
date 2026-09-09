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


def send_poll(
    cfg: TelegramConfig,
    question: str,
    options: list,
    correct_option_id: int,
    message_thread_id: Optional[int] = None,
    is_anonymous: bool = False,
    reply_markup: Optional[dict] = None,
) -> Dict[str, Any]:
    """Invia un quiz nativo Telegram (sendPoll, type=quiz): feedback visivo corretto/sbagliato
    gestito dalla piattaforma. is_anonymous=False è necessario per ricevere gli update
    poll_answer con l'identità di chi ha risposto (altrimenti Telegram non li invia).
    reply_markup opzionale: permette di allegare una tastiera inline al messaggio del poll."""
    payload = {
        "chat_id": cfg.chat_id,
        "question": question,
        "options": options,
        "type": "quiz",
        "correct_option_id": correct_option_id,
        "is_anonymous": is_anonymous,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call(cfg, "sendPoll", payload)


def stop_poll(cfg: TelegramConfig, message_id: int) -> Dict[str, Any]:
    payload = {"chat_id": cfg.chat_id, "message_id": message_id}
    return _call(cfg, "stopPoll", payload)


def delete_message(cfg: TelegramConfig, message_id: int) -> bool:
    """Elimina un messaggio dal chat/gruppo (deleteMessage). Pensata per gli script di
    verifica live contro il bot reale: ogni messaggio di test inviato deve essere ripulito
    a fine script per non riempire il gruppo di traffico di prova. Non solleva se il
    messaggio è già stato eliminato o è troppo vecchio per l'API (>48h): ritorna False
    invece di far fallire lo script di pulizia per un singolo messaggio non cancellabile."""
    payload = {"chat_id": cfg.chat_id, "message_id": message_id}
    try:
        return bool(_call(cfg, "deleteMessage", payload))
    except TelegramAPIError:
        return False


_FILE_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"


def download_voice(cfg: TelegramConfig, file_id: str, dest_path: str, timeout: float = 30.0, max_retries: int = 1) -> None:
    """Scarica un file vocale Telegram (getFile + download binario) e lo scrive in dest_path."""
    file_info = _call(cfg, "getFile", {"file_id": file_id}, timeout=timeout, max_retries=max_retries)
    remote_path = file_info.get("file_path")
    if not remote_path:
        raise TelegramAPIError(f"getFile non ha restituito un file_path valido per file_id='{file_id}'.")

    url = _FILE_BASE.format(token=cfg.bot_token, file_path=remote_path)
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise TelegramAPIError(f"Errore di rete nel download del vocale: {e}") from e
    if resp.status_code != 200:
        raise TelegramAPIError(f"Download del vocale fallito (HTTP {resp.status_code}).")

    with open(dest_path, "wb") as f:
        f.write(resp.content)


def send_audio(
    cfg: TelegramConfig,
    audio_path: str,
    title: str,
    performer: Optional[str] = None,
    message_thread_id: Optional[int] = None,
    timeout: float = 60.0,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """Invia un file audio tramite sendAudio (mostra titolo/artista, player stile playlist,
    si accoda alla coda musicale Telegram — a differenza di sendVoice che mostra una bolla
    vocale con forma d'onda). Usato per l'audio delle unità didattiche su richiesta esplicita."""
    url = _API_BASE.format(token=cfg.bot_token, method="sendAudio")
    data: Dict[str, Any] = {"chat_id": cfg.chat_id, "title": title}
    if performer:
        data["performer"] = performer
    if message_thread_id is not None:
        data["message_thread_id"] = message_thread_id

    with open(audio_path, "rb") as f:
        return _execute_request(
            "sendAudio",
            url,
            {"data": data, "files": {"audio": f}, "timeout": timeout},
            max_retries=max_retries,
        )
