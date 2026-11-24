"""
rt.telegram.notify
Notifiche nella chat personale di Telegram: scaletta da approvare, issue da decidere, lezione
pronta, lavorazione non riuscita. Basta il token del bot e l'ID della chat: nessun bot sempre
acceso. Una notifica non deve mai far fallire la lavorazione che la manda.
"""
from collections import OrderedDict
import html
import logging
import threading
from typing import Any, Dict, List, Optional, Set

LOG = logging.getLogger(__name__)

TEST_TEXT = "👋 Da ora le notifiche di RT arrivano in questa chat."

_JOB_SENT_LOCK = threading.Lock()
_JOB_SENT_EVENTS: "OrderedDict[str, Set[str]]" = OrderedDict()
_MAX_TRACKED_JOBS = 256


def _record_job_sent(kind: str) -> None:
    from rt.llm.deferred import current_job_id
    job_id = current_job_id()
    if not job_id:
        return
    with _JOB_SENT_LOCK:
        events = _JOB_SENT_EVENTS.get(job_id)
        if events is None:
            events = set()
            _JOB_SENT_EVENTS[job_id] = events
            if len(_JOB_SENT_EVENTS) > _MAX_TRACKED_JOBS:
                _JOB_SENT_EVENTS.popitem(last=False)
        else:
            _JOB_SENT_EVENTS.move_to_end(job_id)
        events.add(kind)


def _job_already_sent(kind: str) -> bool:
    from rt.llm.deferred import current_job_id
    job_id = current_job_id()
    if not job_id:
        return False
    with _JOB_SENT_LOCK:
        return kind in _JOB_SENT_EVENTS.get(job_id, ())


def _record(kind: str, text: str, ok: bool = True) -> None:
    """Ultime notifiche per la pagina Impostazioni › Telegram della web."""
    from rt.telegram.notify_log import record_notification
    record_notification(kind, text, ok=ok)


def _redact(message: str, token: str) -> str:
    # Gli errori di rete di requests riportano l'URL, che contiene il token del bot
    return message.replace(token, "[token]") if token else message


def _is_event_enabled(kind: str) -> bool:
    try:
        from rt.core.config import load_config
        notify_prefs = getattr(load_config().telegram, "notify", None) or {}
        if kind in notify_prefs:
            return bool(notify_prefs[kind])
    except Exception:  # noqa: BLE001
        pass
    return True


def send_notification(kind: str, text: str, raise_errors: bool = False) -> bool:
    """True se il messaggio è partito; False se Telegram è spento, l'evento è disattivato o
    non configurato, o (senza raise_errors) se l'invio non è riuscito."""
    if not _is_event_enabled(kind):
        return False
    from rt.core.config import load_env_file
    from rt.telegram.client import send_message
    from rt.telegram.config import TelegramConfigError, load_telegram_config
    # I processi lunghi (worker) leggono qui token e chat salvati dalla web dopo il loro avvio
    load_env_file()
    try:
        cfg = load_telegram_config()
    except TelegramConfigError:
        return False
    try:
        send_message(cfg, text)
    except Exception as exc:  # noqa: BLE001 - la notifica non deve far fallire chi la manda
        message = _redact(str(exc), cfg.bot_token)
        _record(kind, text, ok=False)
        if raise_errors:
            raise RuntimeError(message) from None
        LOG.warning("Notifica Telegram non inviata: %s", message)
        return False
    _record(kind, text)
    _record_job_sent(kind)
    return True


def _job_fallback_meta(lesson_dir: Optional[str]) -> Dict[str, str]:
    """Titolo, data e materia dal job o dal DB quando la cartella/info.yaml non c'è ancora."""
    meta: Dict[str, str] = {}
    try:
        import os
        from sqlalchemy import select
        from rt.db.engine import get_database
        from rt.db.models import Job, Lesson
        from rt.db.repositories import normalize_lesson_path
        from rt.db.session import read_scope
        from rt.llm.deferred import current_job_id
        db = get_database()
        if db is None:
            return meta
        job_id = current_job_id()
        with read_scope(db) as s:
            job = s.get(Job, job_id) if job_id else None
            payload = (job.payload or {}) if job is not None else {}
            opts = payload.get("options") if isinstance(payload.get("options"), dict) else {}
            lid = payload.get("lesson_id")
            lesson = s.get(Lesson, lid) if lid is not None else None
            if lesson is None:
                path_candidate = lesson_dir or (job.lesson_path if job is not None else None)
                if path_candidate:
                    lesson = s.scalar(select(Lesson).where(Lesson.path == normalize_lesson_path(path_candidate)))
            if lesson is not None:
                if lesson.title:
                    meta["title"] = lesson.title
                if lesson.date:
                    meta["data"] = lesson.date
                if lesson.materia:
                    meta["materia"] = lesson.materia
            if not meta.get("data"):
                meta["data"] = str(payload.get("date") or opts.get("date") or "").strip()
            if not meta.get("materia"):
                meta["materia"] = str(payload.get("materia") or opts.get("materia") or "").strip()
            title_opt = str(payload.get("title") or opts.get("title") or "").strip()
            if title_opt and not meta.get("title"):
                meta["title"] = title_opt
            if not meta.get("title") and isinstance(payload.get("inputs"), list) and payload["inputs"]:
                meta["title"] = os.path.basename(str(payload["inputs"][0]))
    except Exception:  # noqa: BLE001 - i dettagli di fallback sono facoltativi
        pass
    return meta


def _lesson_lines(lesson_dir: Optional[str], lesson_title: Optional[str]) -> List[str]:
    """Titolo, data e materia della lezione, per riconoscerla dal telefono."""
    info: Dict[str, Any] = {}
    if lesson_dir:
        try:
            from rt.core.lesson_paths import lesson_path
            from rt.core.state import read_info_yaml
            info = read_info_yaml(lesson_path(lesson_dir, "info.yaml")) or {}
        except Exception:  # noqa: BLE001 - i dettagli sono facoltativi
            info = {}
    details = [str(info.get(key, "")).strip() for key in ("data", "materia")]
    if not lesson_title or not any(details):
        fallback = _job_fallback_meta(lesson_dir)
        if not lesson_title:
            lesson_title = fallback.get("title") or None
        if not details[0]:
            details[0] = fallback.get("data", "")
        if not details[1]:
            details[1] = fallback.get("materia", "")
    lines: List[str] = []
    if lesson_title:
        lines.append(f"📘 {html.escape(lesson_title)}")
    if any(details):
        lines.append("📅 " + " · ".join(html.escape(d) for d in details if d))
    return lines


def notify_build_completed(lesson_dir: str, build_result: Dict[str, Any], lesson_title: str,
                           raise_errors: bool = False) -> bool:
    lines = ["✅ <b>Lezione pronta</b>"] + _lesson_lines(lesson_dir, lesson_title)
    reason = str((build_result or {}).get("reason") or "").strip()
    if reason:
        lines.append(f"🔄 {html.escape(reason)}")
    return send_notification("lezione_pronta", "\n".join(lines), raise_errors=raise_errors)


def notify_review_completed(lesson_dir: Optional[str], pending_count: int,
                            lesson_title: Optional[str] = None, raise_errors: bool = False) -> bool:
    title = lesson_title if lesson_title is not None else _title(lesson_dir)
    tail = f"{pending_count} issue da decidere in RT" if pending_count > 0 else "Nessuna issue"
    lines = ["🔎 <b>Verifica completata</b>"] + _lesson_lines(lesson_dir, title) + [tail]
    return send_notification("verifica_pronta", "\n".join(lines), raise_errors=raise_errors)


def notify_decision_needed(kind: str, lesson_dir: Optional[str], lesson_title: Optional[str],
                           count: Optional[int] = None) -> bool:
    """La lavorazione aspetta una decisione: la scaletta da approvare o le issue da decidere."""
    if kind == "outline_approval":
        event_kind = "scaletta_da_approvare"
        head, tail = "📝 <b>Scaletta da approvare</b>", "Aprila in RT per approvarla o chiedere modifiche."
    elif kind == "science_issue":
        event_kind = "issue_da_decidere"
        head = "🔎 <b>Issue da decidere</b>" + (f" ({count})" if count else "")
        tail = "Decidile in RT: dopo la lezione si completa da sola."
    else:
        return False
    text = "\n".join([head] + _lesson_lines(lesson_dir, lesson_title) + [tail])
    return send_notification(event_kind, text)


def notify_job_failed(lesson_dir: Optional[str], lesson_title: Optional[str], error: Optional[str]) -> bool:
    from rt.services.human_error import human_error
    lines = ["❌ <b>Lavorazione non riuscita</b>"] + _lesson_lines(lesson_dir, lesson_title)
    if error:
        readable = human_error(error) or error
        lines.append(html.escape(readable[:300]))
    return send_notification("errore", "\n".join(lines))


class TelegramBuildNotifier:
    """Notifica di fine lavorazione per 'rt run' e per i job del worker. Se Telegram non è
    configurato non fa nulla; un errore di invio sale all'orchestratore, che lo segnala senza
    far fallire il job."""
    channel = "Telegram"

    def build_completed(self, lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> bool:
        return notify_build_completed(lesson_dir, build_result, lesson_title=lesson_title, raise_errors=True)

    def review_completed(self, lesson_dir: str, pending_count: int, lesson_title: str) -> bool:
        return notify_review_completed(lesson_dir, pending_count, lesson_title=lesson_title, raise_errors=True)


class TelegramJobNotifier:
    """Notifiche dei job del worker che si fermano su una decisione o non riescono."""

    def job_waiting(self, lesson_dir: Optional[str], decision: Dict[str, Any]) -> None:
        kind = (decision or {}).get("kind")
        if kind == "outline_approval" and _outline_auto_approved():
            return  # la scaletta si approva da sola dopo pochi secondi: niente notifica
        if kind == "science_issue" and _job_already_sent("verifica_pronta"):
            return  # verifica_pronta riporta già il numero di issue: evita doppioni nello stesso job
        payload = (decision or {}).get("payload") or {}
        lesson_dir = payload.get("lesson_dir") or lesson_dir
        count = len(payload["pending"]) if isinstance(payload.get("pending"), list) else None
        notify_decision_needed(kind, lesson_dir, _title(lesson_dir), count)

    def job_failed(self, lesson_dir: Optional[str], error: Optional[str]) -> None:
        notify_job_failed(lesson_dir, _title(lesson_dir), error)


def _outline_auto_approved() -> bool:
    try:
        from rt.core.config import load_config
        return getattr(load_config().ui, "outline_mode", "auto") in ("auto", "timer")
    except Exception:  # noqa: BLE001
        return False


def _title(lesson_dir: Optional[str]) -> Optional[str]:
    if not lesson_dir:
        return None
    from rt.services.pipeline_service import lesson_title
    return lesson_title(lesson_dir)


def send_test() -> Dict[str, Any]:
    """Messaggio di prova dalle impostazioni: {ok, message}."""
    try:
        sent = send_notification("prova", TEST_TEXT, raise_errors=True)
    except RuntimeError as exc:
        return {"ok": False, "message": f"Messaggio non inviato: {exc}"}
    if not sent:
        return {"ok": False, "message": "Salva prima il token del bot e la chat, con le notifiche attive."}
    return {"ok": True, "message": "Messaggio di prova inviato: controlla Telegram."}


def detect_private_chat(token: str) -> Optional[Dict[str, str]]:
    """La chat personale dell'ultimo messaggio ricevuto dal bot (chi ha scritto /start):
    {chat_id, name}, oppure None se nessuno gli ha ancora scritto."""
    from rt.telegram.client import get_updates
    for update in reversed(get_updates(token) or []):
        chat = ((update or {}).get("message") or {}).get("chat") or {}
        if chat.get("type") == "private" and chat.get("id") is not None:
            name = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p) or chat.get("username") or ""
            return {"chat_id": str(chat["id"]), "name": name}
    return None
