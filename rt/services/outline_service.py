"""
rt.services.outline_service
Approvazione dell'outline come decisione, indipendente dall'interfaccia (terminale,
Telegram, web, API). L'approvazione viene registrata in _state/outline_approval.json
legata all'hash di outline.json: una revisione successiva la invalida da sola.
Supporta anche il conto alla rovescia e l'approvazione automatica dal server.
"""
import datetime
import json
import os
import threading
from typing import Any, Dict, Optional

from rt.core.config import load_config
from rt.core.idempotency import compute_file_sha256
from rt.core.lesson_paths import lesson_path
from rt.pipeline.outline import get_outline_path, load_outline, run_outline_revision
from rt.services.context import RunContext, phase_scope
from rt.storage import fs

APPROVAL_FILE = "outline_approval.json"
TIMER_FILE = "outline_timer.json"

_TIMERS: Dict[str, threading.Timer] = {}
_TIMER_LOCK = threading.Lock()


def _cancel_in_memory_timer(lesson_dir: str) -> None:
    with _TIMER_LOCK:
        timer = _TIMERS.pop(lesson_dir, None)
        if timer is not None:
            timer.cancel()


def get_outline_timer(lesson_dir: str) -> Optional[Dict[str, Any]]:
    path = lesson_path(lesson_dir, TIMER_FILE)
    if not fs.isfile(path):
        return None
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        current = _outline_hash(lesson_dir)
        if current and data.get("outline_sha256") == current:
            return data
        return None
    except (OSError, ValueError):
        return None


def _save_outline_timer(lesson_dir: str, record: Dict[str, Any]) -> None:
    path = lesson_path(lesson_dir, TIMER_FILE)
    tmp = path + ".tmp"
    with fs.open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    fs.replace(tmp, path)


def _auto_approve_task(lesson_dir: str, expected_sha: str) -> None:
    with _TIMER_LOCK:
        _TIMERS.pop(lesson_dir, None)
    if is_outline_approved(lesson_dir):
        return
    current = _outline_hash(lesson_dir)
    if current != expected_sha:
        return
    timer_data = get_outline_timer(lesson_dir)
    if not timer_data or timer_data.get("suspended"):
        return
    try:
        approve_outline(lesson_dir, actor="server", channel="server")
    except Exception:
        pass


def start_outline_timer(lesson_dir: str, seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Avvia il conto alla rovescia per l'approvazione automatica della scaletta."""
    if is_outline_approved(lesson_dir):
        return None
    current = _outline_hash(lesson_dir)
    if current is None:
        return None

    if seconds is None:
        cfg = load_config()
        seconds = getattr(cfg.ui, "outline_auto_approval_seconds", 10)

    if seconds <= 0:
        return None

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=seconds)

    record = {
        "outline_sha256": current,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "seconds": seconds,
        "suspended": False,
    }
    _save_outline_timer(lesson_dir, record)

    _cancel_in_memory_timer(lesson_dir)
    timer = threading.Timer(float(seconds), _auto_approve_task, args=[lesson_dir, current])
    timer.daemon = True
    with _TIMER_LOCK:
        _TIMERS[lesson_dir] = timer
    timer.start()
    return record


def suspend_outline_timer(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """Sospende il conto alla rovescia per l'approvazione automatica."""
    _cancel_in_memory_timer(lesson_dir)
    record = get_outline_timer(lesson_dir)
    if record is not None:
        record["suspended"] = True
        _save_outline_timer(lesson_dir, record)
        return record
    return None


def get_outline_review(lesson_dir: str) -> Dict[str, Any]:
    """Albero dell'outline serializzabile (JSON) con lo stato di approvazione e timer."""
    outline = load_outline(lesson_dir)
    approved = is_outline_approved(lesson_dir)

    if not approved:
        timer = get_outline_timer(lesson_dir)
        if timer and not timer.get("suspended") and timer.get("expires_at"):
            try:
                exp_dt = datetime.datetime.fromisoformat(timer["expires_at"])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                if now_dt >= exp_dt:
                    approve_outline(lesson_dir, actor="server", channel="server")
                    approved = True
            except Exception:
                pass

    timer = get_outline_timer(lesson_dir) if not approved else None
    return {
        "lesson_title": outline.lesson_title,
        "macro_sections": [
            {
                "id": m.id,
                "title": m.title,
                "units": [
                    {
                        "id": u.id,
                        "title": u.title,
                        "key_concepts": list(u.key_concepts),
                        "start_segment_id": u.start_segment_id,
                        "end_segment_id": u.end_segment_id,
                    }
                    for u in m.units
                ],
            }
            for m in outline.macro_sections
        ],
        "approval": get_outline_approval(lesson_dir),
        "approved": approved,
        "expires_at": timer.get("expires_at") if timer and not approved else None,
        "timer_seconds": timer.get("seconds") if timer and not approved else None,
        "timer_suspended": bool(timer.get("suspended")) if timer and not approved else False,
    }


def _outline_hash(lesson_dir: str) -> Optional[str]:
    path = get_outline_path(lesson_dir)
    return compute_file_sha256(path) if fs.isfile(path) else None


def get_outline_approval(lesson_dir: str) -> Optional[Dict[str, Any]]:
    path = lesson_path(lesson_dir, APPROVAL_FILE)
    if not fs.isfile(path):
        return None
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_outline_approved(lesson_dir: str) -> bool:
    """Vero se l'outline attuale (stesso contenuto) è stata approvata."""
    approval = get_outline_approval(lesson_dir)
    current = _outline_hash(lesson_dir)
    return bool(approval and current and approval.get("outline_sha256") == current)


def approve_outline(lesson_dir: str, actor: str = "user", channel: str = "cli") -> Dict[str, Any]:
    """Registra l'approvazione dell'outline corrente (scrittura atomica)."""
    _cancel_in_memory_timer(lesson_dir)
    current = _outline_hash(lesson_dir)
    if current is None:
        raise FileNotFoundError(f"outline.json mancante in '{lesson_dir}'")
    record = {
        "outline_sha256": current,
        "actor": actor,
        "channel": channel,
        "approved_at": datetime.datetime.now().isoformat(),
    }
    path = lesson_path(lesson_dir, APPROVAL_FILE)
    tmp = path + ".tmp"
    with fs.open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    fs.replace(tmp, path)
    # Un job della coda fermo su questa approvazione riparte da solo (fase D).
    from rt.services.jobs import resume_waiting_jobs
    resume_waiting_jobs(lesson_dir, "outline_approval")
    return record


def request_outline_revision(
    lesson_dir: str,
    feedback: str,
    ctx: Optional[RunContext] = None,
    force_mock: Optional[bool] = None,
) -> Dict[str, Any]:
    """Rigenera l'outline con il feedback dell'utente. La nuova outline non è approvata."""
    _cancel_in_memory_timer(lesson_dir)
    mock = ctx.force_mock if (force_mock is None and ctx is not None) else bool(force_mock)
    with phase_scope(ctx, "outline") as scope:
        result = run_outline_revision(lesson_dir, feedback=feedback, force_mock=mock)
        start_outline_timer(lesson_dir)
        return scope.complete(result)
