"""
rt.telegram.session
Gestione della sessione attiva per topic Telegram.
Garantisce il vincolo 'una sola attività per topic alla volta' persistendo
lo stato in active_sessions.json dentro state_dir.
"""
import os
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, Union

from rt.db.state_documents import MISSING, NO_DATABASE, read_document, write_document


def _sessions_path(state_dir: str) -> str:
    return os.path.join(state_dir, "active_sessions.json")


def _lock_path(state_dir: str) -> str:
    return _sessions_path(state_dir) + ".lock"


def _acquire_lock(state_dir: str, retries: int = 5, backoff: float = 0.2) -> None:
    os.makedirs(state_dir, exist_ok=True)
    lock_path = _lock_path(state_dir)
    for attempt in range(retries):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 30:
                    os.remove(lock_path)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(backoff * (attempt + 1))
    raise TimeoutError(f"Impossibile acquisire il lock su '{lock_path}' dopo {retries} tentativi.")


def _release_lock(state_dir: str) -> None:
    try:
        os.remove(_lock_path(state_dir))
    except FileNotFoundError:
        pass


def _session_key(chat_id: Union[int, str], thread_id: Optional[Union[int, str]] = None) -> str:
    t_key = "general" if thread_id is None else str(thread_id)
    return f"{chat_id}:{t_key}"


def _load_sessions(state_dir: str) -> Dict[str, Any]:
    path = _sessions_path(state_dir)
    doc = read_document(path)
    if doc is not NO_DATABASE:
        return {"schema_version": "1.0", "sessions": {}} if doc is MISSING else doc
    if not os.path.isfile(path):
        return {"schema_version": "1.0", "sessions": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"schema_version": "1.0", "sessions": {}}


def _save_sessions(state_dir: str, data: Dict[str, Any]) -> None:
    path = _sessions_path(state_dir)
    if write_document(path, data):
        return
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def get_active_session(
    state_dir: str,
    chat_id: Union[int, str],
    thread_id: Optional[Union[int, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Restituisce la sessione attiva per il topic (chat_id, thread_id) se presente, altrimenti None."""
    data = _load_sessions(state_dir)
    key = _session_key(chat_id, thread_id)
    return data.get("sessions", {}).get(key)


def start_session(
    state_dir: str,
    chat_id: Union[int, str],
    thread_id: Optional[Union[int, str]],
    kind: str,
    lesson_dir: str,
    message_id: Optional[Union[int, str]] = None,
) -> None:
    """Registra la sessione attiva per il topic specificato.
    Il chiamante è responsabile di aver verificato con get_active_session che il topic
    sia libero o appartenga alla stessa attività prima di invocare start_session.
    """
    _acquire_lock(state_dir)
    try:
        data = _load_sessions(state_dir)
        sessions = data.setdefault("sessions", {})
        key = _session_key(chat_id, thread_id)
        existing = sessions.get(key)

        abs_lesson = os.path.abspath(lesson_dir)
        started_at = (
            existing["started_at"]
            if existing and existing.get("kind") == kind and existing.get("lesson_dir") == abs_lesson
            else datetime.now().isoformat()
        )
        current_msg_id = message_id if message_id is not None else (existing.get("message_id") if existing else None)

        sessions[key] = {
            "kind": kind,
            "lesson_dir": abs_lesson,
            "started_at": started_at,
            "chat_id": str(chat_id),
            "thread_id": None if thread_id is None else str(thread_id),
            "message_id": current_msg_id,
        }
        _save_sessions(state_dir, data)
    finally:
        _release_lock(state_dir)
    if kind == "recall":
        _registry_started(state_dir, abs_lesson, chat_id, thread_id)


def _registry_started(state_dir: str, lesson_dir: str, chat_id, thread_id) -> None:
    """Registro condiviso delle sessioni (DB): la web app vede la sessione in corso."""
    try:
        from rt.services.recall_sessions import telegram_session_started
        from rt.telegram.recall_preferences import get_active_style
        telegram_session_started(lesson_dir, chat_id, thread_id, qtype=get_active_style(state_dir))
    except Exception as exc:  # il registro non deve mai bloccare il bot
        print(f"⚠️  Registro delle sessioni non aggiornato: {exc}")


def _registry_ended(chat_id, thread_id, lesson_dir: Optional[str], ended_by: str) -> None:
    try:
        from rt.services.recall_sessions import telegram_session_ended
        telegram_session_ended(chat_id, thread_id, lesson_dir=lesson_dir, ended_by=ended_by)
    except Exception as exc:
        print(f"⚠️  Registro delle sessioni non aggiornato: {exc}")


def update_session_message(
    state_dir: str,
    chat_id: Union[int, str],
    thread_id: Optional[Union[int, str]],
    message_id: Union[int, str],
) -> None:
    """Aggiorna il message_id dell'ultimo messaggio inviato con bottoni per la sessione attiva."""
    _acquire_lock(state_dir)
    try:
        data = _load_sessions(state_dir)
        sessions = data.setdefault("sessions", {})
        key = _session_key(chat_id, thread_id)
        if key in sessions:
            sessions[key]["message_id"] = message_id
            _save_sessions(state_dir, data)
    finally:
        _release_lock(state_dir)


def end_session(
    state_dir: str,
    chat_id: Union[int, str],
    thread_id: Optional[Union[int, str]] = None,
    ended_by: str = "telegram",
) -> None:
    """Rimuove la sessione attiva per il topic specificato se presente. Una sessione di
    recall si chiude anche nel registro condiviso (ended_by: chi l'ha chiusa)."""
    removed = None
    _acquire_lock(state_dir)
    try:
        data = _load_sessions(state_dir)
        sessions = data.setdefault("sessions", {})
        key = _session_key(chat_id, thread_id)
        if key in sessions:
            removed = sessions.pop(key)
            _save_sessions(state_dir, data)
    finally:
        _release_lock(state_dir)
    if removed is not None and removed.get("kind") == "recall":
        _registry_ended(chat_id, thread_id, removed.get("lesson_dir"), ended_by)


def get_active_session_for_lesson(
    state_dir: str,
    lesson_dir: str,
    kind: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Cerca se esiste una qualsiasi sessione attiva in active_sessions.json per la lezione data (e tipo se specificato)."""
    data = _load_sessions(state_dir)
    target_real = os.path.realpath(lesson_dir)
    for sess in data.get("sessions", {}).values():
        sess_ld = sess.get("lesson_dir")
        if sess_ld and os.path.realpath(sess_ld) == target_real:
            if kind is None or sess.get("kind") == kind:
                return sess
    return None
