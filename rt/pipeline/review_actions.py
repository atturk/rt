"""Operazioni di review riutilizzabili da interfacce non interattive."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from threading import RLock
from typing import Optional

from rt.core.lesson_paths import lesson_path
from rt.core.models import DecisionLedger, ReviewDecision
from rt.pipeline.issue_review import _is_no_diff_issue_type
from rt.pipeline.ledger import (
    find_science_issue_by_id, get_ledger_path, load_ledger, record_decision,
    resolve_science_accept_text, resolve_science_reject_text, revert_last_decision,
)

_web_lock = RLock()
_log = logging.getLogger(__name__)


def _checked_ledger(lesson_dir: str) -> DecisionLedger:
    """Non sovrascrivere un ledger esistente che RT non riesce a leggere."""
    path = get_ledger_path(lesson_dir)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            DecisionLedger.model_validate(json.load(handle))
    return load_ledger(lesson_dir)


def _audit(lesson_dir: str, issue_id: str, action: str, event: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue_id": issue_id,
        "action": action,
        "event": event,
        "channel": "web",
    }
    path = lesson_path(lesson_dir, "web_review_events.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _unit_content(lesson_dir: str, issue) -> Optional[str]:
    from rt.pipeline.rewrite import load_draft

    draft = load_draft(lesson_dir)
    unit = next((unit for unit in draft.units if unit.unit_id == issue.unit_id), None)
    if unit is None and issue.segment_id:
        unit = next((unit for unit in draft.units if issue.segment_id in unit.source_segment_ids), None)
    return unit.content if unit else None


def submit_review_decision(
    lesson_dir: str, issue_id: str, action: str, edited_text: Optional[str] = None,
) -> ReviewDecision:
    """Valida e salva una decisione tramite il ledger comune a CLI e Telegram."""
    if action not in {"accepted", "rejected", "edited"}:
        raise ValueError("Decisione non riconosciuta.")
    with _web_lock:
        issue = find_science_issue_by_id(lesson_dir, issue_id)
        if issue is None:
            raise ValueError("La questione non esiste più: aggiorna l'elenco.")
        if any(decision.issue_id == issue_id for decision in _checked_ledger(lesson_dir).decisions):
            raise ValueError("Questa questione ha già una decisione. Aggiorna la pagina.")

        is_asr = _is_no_diff_issue_type(issue)
        if not is_asr and action in {"accepted", "edited"}:
            unit_content = _unit_content(lesson_dir, issue)
            if not unit_content or not issue.claim.strip() or issue.claim.strip() not in unit_content:
                raise ValueError("Il claim non è presente nel draft: impossibile applicare la correzione. Apri il file delle issue per verificarla.")
        if action == "rejected" and is_asr:
            raise ValueError("Per una verifica ASR puoi accettare il testo o modificarlo.")
        if action == "accepted":
            resolved = _unit_content(lesson_dir, issue) if is_asr else resolve_science_accept_text(issue)
            if is_asr and not resolved:
                raise ValueError("Unità non disponibile: impossibile accettare questa verifica ASR.")
        elif action == "rejected":
            resolved = resolve_science_reject_text(issue)
        else:
            resolved = (edited_text or "").strip()
            if not resolved:
                raise ValueError("Scrivi un testo corretto prima di salvare la modifica.")

        saved = record_decision(
            lesson_dir, issue_id, action, resolved_text=resolved,
            resolved_by="web", notes="Decisione registrata dall'interfaccia web",
        )
        try:
            _audit(lesson_dir, issue_id, action, "recorded")
        except OSError:
            _log.exception("Decisione salvata, ma registrazione evento web fallita: %s", issue_id)
        return saved


def undo_web_decision(lesson_dir: str, issue_id: str) -> None:
    """Riapre soltanto l'ultima decisione presa dalla GUI per questa questione."""
    with _web_lock:
        decisions = [d for d in _checked_ledger(lesson_dir).decisions if d.issue_id == issue_id]
        if not decisions or decisions[-1].resolved_by != "web":
            raise ValueError("Puoi riaprire da qui solo una decisione presa nella GUI.")
        if not revert_last_decision(lesson_dir, issue_id):
            raise ValueError("La decisione non è più presente nel ledger.")
        try:
            _audit(lesson_dir, issue_id, decisions[-1].decision, "reverted")
        except OSError:
            _log.exception("Decisione riaperta, ma registrazione evento web fallita: %s", issue_id)
