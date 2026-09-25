"""
rt.services.outline_service
Approvazione dell'outline come decisione, indipendente dall'interfaccia (terminale,
Telegram, web, API). L'approvazione viene registrata in _state/outline_approval.json
legata all'hash di outline.json: una revisione successiva la invalida da sola.
"""
import datetime
import json
import os
from typing import Any, Dict, Optional

from rt.core.idempotency import compute_file_sha256
from rt.core.lesson_paths import lesson_path
from rt.pipeline.outline import get_outline_path, load_outline, run_outline_revision
from rt.services.context import RunContext, phase_scope

APPROVAL_FILE = "outline_approval.json"


def get_outline_review(lesson_dir: str) -> Dict[str, Any]:
    """Albero dell'outline serializzabile (JSON) con lo stato di approvazione."""
    outline = load_outline(lesson_dir)
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
        "approved": is_outline_approved(lesson_dir),
    }


def _outline_hash(lesson_dir: str) -> Optional[str]:
    path = get_outline_path(lesson_dir)
    return compute_file_sha256(path) if os.path.isfile(path) else None


def get_outline_approval(lesson_dir: str) -> Optional[Dict[str, Any]]:
    path = lesson_path(lesson_dir, APPROVAL_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
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
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return record


def request_outline_revision(
    lesson_dir: str,
    feedback: str,
    ctx: Optional[RunContext] = None,
    force_mock: Optional[bool] = None,
) -> Dict[str, Any]:
    """Rigenera l'outline con il feedback dell'utente. La nuova outline non è approvata."""
    mock = ctx.force_mock if (force_mock is None and ctx is not None) else bool(force_mock)
    with phase_scope(ctx, "outline") as scope:
        return scope.complete(run_outline_revision(lesson_dir, feedback=feedback, force_mock=mock))
