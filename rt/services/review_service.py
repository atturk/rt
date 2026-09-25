"""
rt.services.review_service
Punto unico per le decisioni sulle issue scientifiche, da qualunque canale (cli, telegram,
web, api): elenco delle issue pendenti con contesto, registrazione di una decisione,
annullamento dell'ultima, stato di completamento.

Ogni scrittura del ledger (review_decisions.json, stesso formato di sempre) avviene sotto
un lock a file per lezione (.rt.lock), così due processi (CLI, daemon Telegram, web) che
decidono sulla stessa lezione non si perdono decisioni a vicenda.
"""
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Protocol, Sequence, Tuple

from rt.core.filelock import file_lock
from rt.core.lesson_paths import lesson_path
from rt.core.models import ReviewDecision, ScienceIssue
from rt.pipeline.issue_review import _is_no_diff_issue_type, should_auto_accept_science
from rt.pipeline.ledger import (
    find_science_issue_by_id,
    get_pending_issues,
    load_ledger,
    record_decision,
    resolve_science_accept_text,
    resolve_science_reject_text,
    revert_last_decision,
    sanitize_suggested_fix,
)

CHANNELS = ("cli", "telegram", "web", "api")
LOCK_FILE = ".rt.lock"


class ReviewChannel(Protocol):
    """Porta verso un canale che presenta le issue all'utente una alla volta (Telegram)."""

    def start_review(self, lesson_dir: str, issues: Sequence[ScienceIssue]) -> None: ...

    def send_current_issue(self, lesson_dir: str) -> None: ...


class ReviewDecisionError(ValueError):
    """Decisione non applicabile (issue sparita, già decisa, testo mancante...).
    reason: "invalid" | "not_allowed" (annullamento da un altro canale) | "missing"."""

    def __init__(self, message: str, reason: str = "invalid"):
        super().__init__(message)
        self.reason = reason


@contextmanager
def lesson_lock(lesson_dir: str) -> Iterator[None]:
    """Lock esclusivo per lezione, valido tra processi e thread."""
    with file_lock(os.path.join(lesson_dir, LOCK_FILE), retries=100, backoff=0.05):
        yield


def issue_context(lesson_dir: str, issue: ScienceIssue) -> Dict[str, Any]:
    """Contesto di un'issue: unità, timecode e finestra audio (secondi e segmenti)."""
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import get_draft_path, load_draft

    seg_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in seg_data.segments} if seg_data else {}
    draft = load_draft(lesson_dir) if os.path.isfile(get_draft_path(lesson_dir)) else None
    seg_to_unit, unit_by_id = {}, {}
    if draft:
        for u in draft.units:
            unit_by_id[u.unit_id] = u
            for sid in u.source_segment_ids:
                seg_to_unit[sid] = u

    seg = seg_by_id.get(issue.segment_id) if issue.segment_id else None
    sci_unit = unit_by_id.get(issue.unit_id) if issue.unit_id else (seg_to_unit.get(issue.segment_id) if issue.segment_id else None)
    start_segment_id, end_segment_id = None, None
    start_s, end_s = None, None
    if sci_unit:
        start_segment_id = sci_unit.start_segment_id
        end_segment_id = sci_unit.end_segment_id
        s_seg = seg_by_id.get(sci_unit.start_segment_id)
        e_seg = seg_by_id.get(sci_unit.end_segment_id)
        if s_seg and e_seg:
            start_s = s_seg.start_seconds
            end_s = e_seg.end_seconds
    if start_segment_id is None and issue.segment_id:
        start_segment_id = issue.segment_id
        end_segment_id = issue.segment_id
        if seg:
            start_s = seg.start_seconds
            end_s = seg.end_seconds

    return {
        "timecode": seg.start_formatted if seg else "N/D",
        "unit_info": f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else issue.unit_id,
        "unit_content": sci_unit.content if sci_unit else None,
        "start_segment_id": start_segment_id,
        "end_segment_id": end_segment_id,
        "start_s": start_s,
        "end_s": end_s,
    }


def list_pending_issues(lesson_dir: str, with_context: bool = True) -> List[Dict[str, Any]]:
    """Issue scientifiche ancora senza decisione, serializzabili (JSON)."""
    _, pending = get_pending_issues(lesson_dir)
    out = []
    for iss in pending:
        item = {"issue": iss.model_dump(mode="json")}
        if with_context:
            item["context"] = issue_context(lesson_dir, iss)
        out.append(item)
    return out


def is_review_complete(lesson_dir: str) -> bool:
    rem_asr, rem_sci = get_pending_issues(lesson_dir)
    return not rem_asr and not rem_sci


def mark_ready_to_build(lesson_dir: str) -> None:
    from rt.core.state import WorkflowState, transition_to
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    if os.path.isfile(yaml_path):
        try:
            transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
        except Exception:
            pass


def _unit_content(lesson_dir: str, issue: ScienceIssue) -> Optional[str]:
    from rt.pipeline.rewrite import load_draft

    draft = load_draft(lesson_dir)
    unit = next((u for u in draft.units if u.unit_id == issue.unit_id), None)
    if unit is None and issue.segment_id:
        unit = next((u for u in draft.units if issue.segment_id in u.source_segment_ids), None)
    return unit.content if unit else None


def _validated_text(lesson_dir: str, issue: ScienceIssue, decision: str, text: Optional[str]) -> Optional[str]:
    """Regole di validazione delle interfacce non interattive (web/API): stesso testo
    risolto che producono CLI e Telegram."""
    is_asr = _is_no_diff_issue_type(issue)
    if not is_asr and decision in {"accepted", "edited"}:
        unit_content = _unit_content(lesson_dir, issue)
        if not unit_content or not issue.claim.strip() or issue.claim.strip() not in unit_content:
            raise ReviewDecisionError("Il claim non è presente nel draft: impossibile applicare la correzione. Apri il file delle issue per verificarla.")
    if decision == "rejected" and is_asr:
        raise ReviewDecisionError("Per una verifica ASR puoi accettare il testo o modificarlo.")
    if decision == "accepted":
        resolved = _unit_content(lesson_dir, issue) if is_asr else resolve_science_accept_text(issue)
        if is_asr and not resolved:
            raise ReviewDecisionError("Unità non disponibile: impossibile accettare questa verifica ASR.")
        return resolved
    if decision == "rejected":
        return resolve_science_reject_text(issue)
    resolved = (text or "").strip()
    if not resolved:
        raise ReviewDecisionError("Scrivi un testo corretto prima di salvare la modifica.")
    return resolved


def record_review_decision(
    lesson_dir: str,
    issue_id: str,
    decision: str,
    resolved_text: Optional[str] = None,
    *,
    channel: str,
    actor: str = "user",
    resolved_by: Optional[str] = None,
    notes: Optional[str] = None,
    validate: bool = False,
) -> ReviewDecision:
    """Registra una decisione (accepted | rejected | edited) nel ledger.

    validate=True applica i controlli delle interfacce non interattive (issue esistente e
    non ancora decisa, claim presente nel draft) e calcola il testo risolto; altrimenti
    resolved_text è salvato così com'è, come fanno da sempre CLI e Telegram."""
    if channel not in CHANNELS:
        raise ValueError(f"Canale non valido: {channel}")
    decision = decision.lower().strip()
    if decision not in {"accepted", "rejected", "edited"}:
        raise ReviewDecisionError("Decisione non riconosciuta.")
    with lesson_lock(lesson_dir):
        if validate:
            issue = find_science_issue_by_id(lesson_dir, issue_id)
            if issue is None:
                raise ReviewDecisionError("La questione non esiste più: aggiorna l'elenco.")
            if any(d.issue_id == issue_id for d in load_ledger(lesson_dir, strict=True).decisions):
                raise ReviewDecisionError("Questa questione ha già una decisione. Aggiorna la pagina.")
            resolved_text = _validated_text(lesson_dir, issue, decision, resolved_text)
        recorded = record_decision(
            lesson_dir, issue_id, decision, resolved_text=resolved_text,
            resolved_by=resolved_by or "user",
            notes=notes, channel=channel, actor=actor,
        )
    # Con l'ultima issue decisa, il job della coda fermo sulla review riparte verso il build.
    from rt.services.jobs import resume_waiting_jobs
    resume_waiting_jobs(lesson_dir, "science_issue", condition=lambda: is_review_complete(lesson_dir))
    return recorded


def undo_last_decision(lesson_dir: str, issue_id: str, only_channel: Optional[str] = None) -> ReviewDecision:
    """Rimuove l'ultima decisione per issue_id e la restituisce. Con only_channel rifiuta
    di annullare una decisione presa da un altro canale."""
    with lesson_lock(lesson_dir):
        decisions = [d for d in load_ledger(lesson_dir, strict=True).decisions if d.issue_id == issue_id]
        last = decisions[-1] if decisions else None
        if only_channel is not None and (last is None or (last.channel or last.resolved_by) != only_channel):
            raise ReviewDecisionError("Puoi riaprire da qui solo una decisione presa da questo canale.", reason="not_allowed")
        if last is None or not revert_last_decision(lesson_dir, issue_id):
            raise ReviewDecisionError("La decisione non è più presente nel ledger.", reason="missing")
        return last


def auto_accept_pending(
    lesson_dir: str,
    auto_accept: Optional[str],
    channel: str = "cli",
) -> Tuple[List[ScienceIssue], List[ScienceIssue]]:
    """Applica l'auto-accept alle issue pendenti. Ritorna (accettate, da rivedere)."""
    _, pending = get_pending_issues(lesson_dir)
    accepted, remaining = [], []
    for iss in pending:
        (accepted if should_auto_accept_science(iss, auto_accept) else remaining).append(iss)
    for iss in accepted:
        record_review_decision(
            lesson_dir, iss.id, "accepted", sanitize_suggested_fix(iss.suggested_fix),
            channel=channel, actor="auto_accept", resolved_by="cli_auto",
        )
    return accepted, remaining
