"""Operazioni di review per le interfacce non interattive (web): adattatore sottile su
rt.services.review_service, più il registro eventi web_review_events.jsonl."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Optional

from rt.core.lesson_paths import lesson_path
from rt.core.models import ReviewDecision
from rt.services.review_service import (
    ReviewDecisionError, record_review_decision, undo_last_decision,
)
from rt.storage import fs

_log = logging.getLogger(__name__)


def _audit(lesson_dir: str, issue_id: str, action: str, event: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue_id": issue_id,
        "action": action,
        "event": event,
        "channel": "web",
    }
    path = lesson_path(lesson_dir, "web_review_events.jsonl")
    with fs.open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def submit_review_decision(
    lesson_dir: str, issue_id: str, action: str, edited_text: Optional[str] = None,
) -> ReviewDecision:
    """Valida e salva una decisione tramite il ledger comune a CLI e Telegram."""
    if action not in {"accepted", "rejected", "edited"}:
        raise ValueError("Decisione non riconosciuta.")
    saved = record_review_decision(
        lesson_dir, issue_id, action, edited_text, channel="web", actor="web",
        resolved_by="web", notes="Decisione registrata dall'interfaccia web", validate=True,
    )
    try:
        _audit(lesson_dir, issue_id, action, "recorded")
    except OSError:
        _log.exception("Decisione salvata, ma registrazione evento web fallita: %s", issue_id)
    return saved


def undo_web_decision(lesson_dir: str, issue_id: str) -> None:
    """Riapre soltanto l'ultima decisione presa dalla GUI per questa questione."""
    try:
        reverted = undo_last_decision(lesson_dir, issue_id, only_channel="web")
    except ReviewDecisionError as exc:
        if exc.reason == "not_allowed":
            raise ValueError("Puoi riaprire da qui solo una decisione presa nella GUI.") from exc
        raise ValueError(str(exc)) from exc
    try:
        _audit(lesson_dir, issue_id, reverted.decision, "reverted")
    except OSError:
        _log.exception("Decisione riaperta, ma registrazione evento web fallita: %s", issue_id)
