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
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from rt.core.lesson_lock import lesson_lock
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
    load_resolved_draft, resolved_unit_content,
)
from rt.storage import fs

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



def issue_context(lesson_dir: str, issue: ScienceIssue, *, segments=None, draft=None,
                  loaded: bool = False) -> Dict[str, Any]:
    """Contesto di un'issue: unità, timecode e finestra audio (secondi e segmenti)."""
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import get_draft_path, load_draft

    if not loaded:
        segments = load_segments_json(lesson_path(lesson_dir, "segments.json"))
        draft = load_resolved_draft(lesson_dir) if fs.isfile(get_draft_path(lesson_dir)) else None
    seg_by_id = {s.id: s for s in segments.segments} if segments else {}
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
        "unit_content": resolved_unit_content(lesson_dir, issue, draft) if draft else None,
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
    if fs.isfile(yaml_path):
        try:
            transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
        except Exception:
            pass


def _unit_content(lesson_dir: str, issue: ScienceIssue) -> Optional[str]:
    draft = load_resolved_draft(lesson_dir)
    if issue.unit_id and not any(unit.unit_id == issue.unit_id for unit in draft.units):
        return None
    return resolved_unit_content(lesson_dir, issue, draft)


def _validated_text(lesson_dir: str, issue: ScienceIssue, decision: str, text: Optional[str], *, reconfirming: bool = False) -> Optional[str]:
    """Regole di validazione delle interfacce non interattive (web/API): stesso testo
    risolto che producono CLI e Telegram."""
    is_asr = _is_no_diff_issue_type(issue)
    if issue.unanchored and decision != "rejected":
        raise ReviewDecisionError("Citazione non ritrovata: puoi solo rifiutare l'issue", reason="claim_changed")
    if not is_asr and decision in {"accepted", "edited"}:
        unit_content = _unit_content(lesson_dir, issue)
        from rt.pipeline.anchors import find_quote
        # Una scelta nuova non sovrascrive una correzione già applicata con un match fuzzy.
        quote = issue.anchor.quote if issue.anchor else issue.claim
        found = find_quote(unit_content, quote) if unit_content else None
        if found is None:
            raise ReviewDecisionError("Il testo è già cambiato: modificalo a mano o chiudi l'issue", reason="claim_changed")
    if decision == "rejected" and is_asr and not reconfirming:
        raise ReviewDecisionError("Per una verifica ASR puoi accettare il testo o modificarlo.")
    if decision == "accepted":
        resolved = _unit_content(lesson_dir, issue) if is_asr else text if reconfirming and text else resolve_science_accept_text(issue)
        if not is_asr and not resolved:
            raise ReviewDecisionError("È un suggerimento, non una correzione: scrivi tu il testo", reason="suggestion_only")
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

    validate=True richiede un'issue aperta o una decisione da riconfermare e,
    per applicare una correzione, la citazione letterale nel testo risolto.
    Una riconferma aggiunge una scelta senza cancellare la precedente; altrimenti
    resolved_text è salvato così com'è, come fanno da sempre CLI e Telegram."""
    if channel not in CHANNELS:
        raise ValueError(f"Canale non valido: {channel}")
    decision = decision.lower().strip()
    if decision not in {"accepted", "rejected", "edited"}:
        raise ReviewDecisionError("Decisione non riconosciuta.")
    with lesson_lock(lesson_dir):
        issue = find_science_issue_by_id(lesson_dir, issue_id)
        if issue and issue.unanchored and decision != "rejected":
            raise ReviewDecisionError("Citazione non ritrovata: puoi solo rifiutare l'issue", reason="claim_changed")
        anchor = None
        original_context = None
        if validate:
            if issue is None:
                raise ReviewDecisionError("La questione non esiste più: aggiorna l'elenco.")
            from rt.pipeline.ledger import reconfirmation_issue_ids
            previous = next((d for d in reversed(load_ledger(lesson_dir, strict=True).decisions) if d.issue_id == issue_id), None)
            reconfirming = previous is not None and issue_id in reconfirmation_issue_ids(lesson_dir)
            if previous is not None and not reconfirming:
                raise ReviewDecisionError("Questa questione ha già una decisione. Aggiorna la pagina.")
            if reconfirming and decision == "accepted" and previous.resolved_text:
                resolved_text = previous.resolved_text
            resolved_text = _validated_text(lesson_dir, issue, decision, resolved_text, reconfirming=reconfirming)
            # La nuova decisione si ancora al tratto ritrovato, senza toccare la precedente.
            if reconfirming and decision != "rejected":
                from rt.pipeline.anchors import find_quote, locate, make_anchor
                content = _unit_content(lesson_dir, issue)
                if content:
                    found = locate(issue.anchor, content) if issue.anchor else find_quote(content, issue.claim)
                    if _is_no_diff_issue_type(issue):
                        anchor = make_anchor(content, 0, len(content))
                    elif found:
                        anchor = make_anchor(content, found.start, found.end)
            elif decision == "rejected" and _unit_content(lesson_dir, issue) is None:
                original_context = ""  # Mantieni esplicito su un passaggio ormai sparito.
        recorded = record_decision(
            lesson_dir, issue_id, decision, resolved_text=resolved_text,
            resolved_by=resolved_by or "user",
            notes=notes, channel=channel, actor=actor, anchor=anchor, original_context=original_context,
        )
        from rt.services.documents_service import request_documents
        request_documents(lesson_dir)
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
        from rt.services.documents_service import request_documents
        request_documents(lesson_dir)
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
        if not should_auto_accept_science(iss, auto_accept) or not (_is_no_diff_issue_type(iss) or resolve_science_accept_text(iss)):
            remaining.append(iss)
            continue
        try:
            record_review_decision(lesson_dir, iss.id, "accepted", channel=channel,
                                   actor="auto_accept", resolved_by="cli_auto", validate=True)
        except ReviewDecisionError:
            remaining.append(iss)
        else:
            accepted.append(iss)
    return accepted, remaining


# ---------------------------------------------------------------- avvisi per il documento finale

def orphan_issue_ids(lesson_dir: str) -> List[str]:
    """Issue scientifiche che non trovano più il loro testo (claim) nella bozza: una
    correzione accettata non verrebbe applicata. Le ASR (senza diff) e quelle rifiutate
    (il testo resta com'è) non contano."""
    from rt.pipeline.review import load_science_issues
    from rt.pipeline.rewrite import get_draft_path, load_draft
    if not fs.isfile(get_draft_path(lesson_dir)):
        return []
    draft = load_resolved_draft(lesson_dir)
    ledger = {d.issue_id: d for d in load_ledger(lesson_dir).decisions}
    out = []
    for issue in load_science_issues(lesson_dir):
        decision = ledger.get(issue.id)
        if _is_no_diff_issue_type(issue) or (decision and decision.decision == "rejected"):
            continue
        content = resolved_unit_content(lesson_dir, issue, draft)
        claim = (issue.claim or "").strip()
        if content is not None and claim and claim in content:
            continue
        fixed = (decision.resolved_text or "").strip() if decision and decision.decision in ("accepted", "edited") else ""
        literal = fixed or None
        if content is not None and literal and literal in content:
            continue
        out.append(issue.id)
    return out


def build_warnings(lesson_dir: str) -> List[Dict[str, Any]]:
    """Controlli di integrità prima del documento finale. Non bloccano il build (è la
    conferma dell'utente): l'API li espone e la web li mostra nel dialogo di conferma.
    Ogni avviso: code, message, count (numero di issue, se ha senso)."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.pipeline.review import load_science_issues
    warnings: List[Dict[str, Any]] = []
    status, reason = check_phase_status(lesson_dir, "review")
    if status == PhaseStatus.MISSING:
        warnings.append({"code": "review_missing", "count": None,
                         "message": "Revisione scientifica non eseguita."})
        return warnings
    if status == PhaseStatus.STALE:
        warnings.append({"code": "review_stale", "count": None,
                         "message": f"Revisione non aggiornata: {reason}."})
    elif status == PhaseStatus.PARTIAL:
        warnings.append({"code": "review_partial", "count": None,
                         "message": f"Revisione incompleta: {reason}."})
    elif status == PhaseStatus.INVALID:
        warnings.append({"code": "review_invalid", "count": None,
                         "message": f"Revisione non leggibile: {reason}."})
        return warnings
    try:
        orphans = set(orphan_issue_ids(lesson_dir))
        decided = {d.issue_id for d in load_ledger(lesson_dir).decisions}
        pending = [i for i in load_science_issues(lesson_dir) if i.id not in decided and i.id not in orphans]
    except Exception as exc:  # file illeggibili: lo dice l'avviso, il build decide
        warnings.append({"code": "review_invalid", "count": None,
                         "message": f"Issue della revisione non leggibili: {exc}."})
        return warnings
    resolved = load_resolved_draft(lesson_dir)
    latest = {d.issue_id: d for d in load_ledger(lesson_dir).decisions}
    not_applied = []
    for issue in load_science_issues(lesson_dir):
        decision = latest.get(issue.id)
        if not decision or decision.decision not in {"accepted", "edited"}:
            continue
        text = decision.resolved_text
        content = resolved_unit_content(lesson_dir, issue, resolved)
        if not text or content is None or text not in content:
            # Accettare un avviso di paragrafo conferma il testo corrente.
            if _is_no_diff_issue_type(issue) and decision.decision == "accepted" and content is not None:
                continue
            not_applied.append(issue.id)
    if not_applied:
        warnings.append({"code": "decision_not_applied", "count": len(not_applied),
                         "message": f"{len(not_applied)} decisioni non applicate al testo del documento."})
    if pending:
        n = len(pending)
        warnings.append({"code": "pending_issues", "count": n,
                         "message": f"{n} issue ancora da valutare: le correzioni proposte non entrano nel documento."})
    if orphans:
        n = len(orphans)
        text = ("1 issue orfana: il suo testo non è più nella bozza" if n == 1
                else f"{n} issue orfane: il loro testo non è più nella bozza")
        warnings.append({"code": "orphan_issues", "count": n, "message": text + "."})
    return warnings


def review_units(lesson_dir: str) -> List[Dict[str, Any]]:
    """Stati della verifica in ordine di bozza, con compatibilità per i checkpoint storici."""
    from rt.pipeline.review_units import load_review_units
    from rt.pipeline.review import _unit_hashes, load_science_issues
    from rt.pipeline.rewrite import load_draft
    from rt.core.idempotency import get_phase_checkpoint
    from rt.services.unit_relevance import included_ids
    draft = load_resolved_draft(lesson_dir)
    # Le impronte seguono la bozza grezza: una decisione non rende l'unità "cambiata".
    current = _unit_hashes(load_draft(lesson_dir).units)
    registry = load_review_units(lesson_dir)
    checkpoint, _, _ = get_phase_checkpoint(lesson_dir, "review")
    checkpoint = checkpoint or {}
    hashes = checkpoint.get("unit_hashes") or {}
    completed = set(checkpoint.get("completed_items") or [])
    decided = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    issues = load_science_issues(lesson_dir)
    allowed = included_ids(lesson_dir, draft.units)
    rows = []
    for unit in draft.units:
        entry = registry.get(unit.unit_id) or {}
        unit_issues = [i for i in issues if i.unit_id == unit.unit_id or
                       (not i.unit_id and i.segment_id in unit.source_segment_ids)]
        digest = entry.get("text_hash") or hashes.get(unit.unit_id)
        known = bool(entry) or unit.unit_id in completed
        if unit.unit_id not in allowed:
            state = "excluded"
        elif known and digest and digest != current[unit.unit_id]:
            state = "changed"
        elif entry.get("result") == "failed":
            state = "failed"
        elif known and digest == current[unit.unit_id]:
            state = "issues" if unit_issues else "ok"
        else:
            state = "never"
        rows.append({"unit_id": unit.unit_id, "title": unit.title, "state": state,
                     "reviewed_at": entry.get("reviewed_at"), "model": entry.get("model"),
                     "issues_total": len(unit_issues), "issues_pending": sum(i.id not in decided for i in unit_issues)})
    return rows
