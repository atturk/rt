"""
rt.pipeline.ledger
Gestione deterministica del Decision Ledger (review_decisions.json) e interfaccia Human-in-the-Loop.
Registra ogni decisione in modo riproducibile e non ri-chiede decisioni già convalidate.
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional, Set
from rt.core.models import DecisionLedger, ReviewDecision, ScienceIssue, ScienceType, Draft
from rt.core.encoding import fix_mojibake, sanitize_object_encoding
from rt.core.lesson_paths import lesson_path
from rt.storage import fs



def get_ledger_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "review_decisions.json")


def load_ledger(lesson_dir: str, strict: bool = False, *, _migrate: bool = True) -> DecisionLedger:
    """Carica il ledger. Un file illeggibile vale come ledger vuoto, oppure (strict=True)
    solleva l'errore: chi sta per scrivere non deve sovrascrivere dati che non sa leggere."""
    if _migrate:
        from rt.pipeline.review_migration import migrate_review_anchors
        migrate_review_anchors(lesson_dir)
    path = get_ledger_path(lesson_dir)
    if not fs.isfile(path):
        return DecisionLedger(schema_version="1.0", decisions=[])
    if strict:
        with fs.open(path, "r", encoding="utf-8") as f:
            return DecisionLedger.model_validate(sanitize_object_encoding(json.load(f)))
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cleaned_data = sanitize_object_encoding(data)
        return DecisionLedger.model_validate(cleaned_data)
    except Exception:
        return DecisionLedger(schema_version="1.0", decisions=[])


def write_ledger_file(ledger: DecisionLedger, lesson_dir: str) -> None:
    """Scrive review_decisions.json (formato storico), senza toccare il DB."""
    path = get_ledger_path(lesson_dir)
    data = sanitize_object_encoding(ledger.model_dump(mode="json"))
    # channel/actor si scrivono solo quando noti: le decisioni senza restano nel formato storico.
    for dec in data.get("decisions", []):
        for key in ("channel", "actor", "anchor"):
            if dec.get(key) is None:
                dec.pop(key, None)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)


def save_ledger(ledger: DecisionLedger, lesson_dir: str) -> None:
    """Sovrascrive il ledger con `ledger` e allinea il DB (che lo reimporta)."""
    write_ledger_file(ledger, lesson_dir)

    from rt.db.sync import dual_write_lesson
    dual_write_lesson(lesson_dir)


def record_decision(
    lesson_dir: str,
    issue_id: str,
    decision: str,
    resolved_text: Optional[str] = None,
    resolved_by: str = "user",
    notes: Optional[str] = None,
    original_context: Optional[str] = None,
    channel: Optional[str] = None,
    actor: Optional[str] = None,
) -> ReviewDecision:
    """Registra una decisione nel ledger atomico append-only con sanitizzazione UTF-8.
    Le interfacce passano da rt.services.review_service, che prende il lock per lezione."""
    ledger = load_ledger(lesson_dir)
    clean_resolved = fix_mojibake(resolved_text) if resolved_text else None
    clean_notes = fix_mojibake(notes) if notes else None
    clean_context = fix_mojibake(original_context) if original_context else None
    
    issue = find_science_issue_by_id(lesson_dir, issue_id)
    # Una decisione nuova si ancora al testo che l'utente sta vedendo, anche
    # quando l'issue proviene da un produttore storico privo di ancore.
    if issue and issue.anchor is None:
        from rt.pipeline.anchors import find_quote, make_anchor
        try:
            draft = load_resolved_draft(lesson_dir)
        except FileNotFoundError:
            draft = None
        unit = next((u for u in draft.units if u.unit_id == issue.unit_id), None) if draft else None
        if unit:
            if issue.type in (ScienceType.ERR_ASR_ST, ScienceType.ERR_ASR_LLM, ScienceType.ERR_REWRITE_DRIFT):
                issue.anchor = make_anchor(unit.content, 0, len(unit.content))
            else:
                found = find_quote(unit.content, issue.claim)
                if found:
                    issue.anchor = make_anchor(unit.content, found.start, found.end)
    dec_obj = ReviewDecision(
        anchor=issue.anchor.model_copy(deep=True) if issue and issue.anchor else None,
        issue_id=issue_id,
        decision=decision.lower().strip(),
        resolved_text=clean_resolved,
        resolved_by=resolved_by,
        timestamp=datetime.now().isoformat(),
        notes=clean_notes,
        original_context=clean_context,
        channel=channel,
        actor=actor,
    )
    
    # Con il DB attivo la decisione si registra lì e il file viene riesportato dal DB.
    from rt.db.ledger_store import NO_DATABASE, append_decision
    if append_decision(lesson_dir, dec_obj.model_dump()) is NO_DATABASE:
        ledger.decisions.append(dec_obj)
        save_ledger(ledger, lesson_dir)

    return dec_obj



def revert_last_decision(lesson_dir: str, issue_id: str) -> bool:
    """Rimuove l'ultima voce per issue_id dal ledger (append-only). Ritorna False se non trovata.
    Con il DB attivo la voce resta nel DB marcata come annullata."""
    from rt.db.ledger_store import NO_DATABASE, revert_last
    result = revert_last(lesson_dir, issue_id)
    if result is not NO_DATABASE:
        return result
    ledger = load_ledger(lesson_dir)
    target_idx = None
    for idx in range(len(ledger.decisions) - 1, -1, -1):
        if ledger.decisions[idx].issue_id == issue_id:
            target_idx = idx
            break
    if target_idx is None:
        return False
    ledger.decisions.pop(target_idx)
    save_ledger(ledger, lesson_dir)
    return True


def purge_decisions_by_prefix(lesson_dir: str, prefix: str) -> int:
    """Rimuove dal ledger (append-only) tutte le voci il cui issue_id inizia con prefix. Salva e ritorna il numero di voci rimosse."""
    from rt.db.ledger_store import NO_DATABASE, revert_prefix
    removed = revert_prefix(lesson_dir, prefix)
    if removed is not NO_DATABASE:
        return removed
    ledger = load_ledger(lesson_dir)
    original_count = len(ledger.decisions)
    ledger.decisions = [d for d in ledger.decisions if not d.issue_id.startswith(prefix)]
    removed_count = original_count - len(ledger.decisions)
    if removed_count > 0:
        save_ledger(ledger, lesson_dir)
    return removed_count


def apply_decisions_to_draft(
    draft: Draft, ledger: DecisionLedger, science_issues: List[ScienceIssue],
    edited_units: Optional[Dict[str, str]] = None, *, missing_decisions: Optional[Set[str]] = None,
) -> Draft:
    """Applica le ultime decisioni nell'ordine del registro, solo nella loro unità.

    Le ancore mancanti restano registrate: missing_decisions raccoglie lo stato
    calcolato per l'API. I contratti storici in memoria passano dalla migrazione.
    """
    from rt.pipeline.anchors import locate
    from rt.pipeline.review_migration import PARAGRAPH_TYPES
    if ledger.schema_version != "2.0":
        from rt.pipeline.review_migration import migrate_objects
        ledger, science_issues = migrate_objects(draft, ledger, science_issues, edited_units or {})
    latest = {d.issue_id: d for d in ledger.decisions}
    ordered = [d for d in ledger.decisions if latest[d.issue_id] is d]
    by_id = {i.id:i for i in science_issues}
    by_unit = {u.unit_id:u.model_copy(deep=True) for u in draft.units}
    for unit in by_unit.values():
        unit.content = fix_mojibake(unit.content)
        unit.title = fix_mojibake(unit.title)
    for decision in ordered:
        issue = by_id.get(decision.issue_id)
        if issue is None:
            if missing_decisions is not None:
                missing_decisions.add(decision.issue_id)
            continue
        unit = by_unit.get(issue.unit_id)
        if unit is None:
            if missing_decisions is not None:
                missing_decisions.add(issue.id)
            continue
        if edited_units and unit.unit_id in edited_units and decision.timestamp <= edited_units[unit.unit_id]:
            continue
        if decision.decision == 'rejected':
            continue
        if issue.type in PARAGRAPH_TYPES:
            if decision.decision == 'edited' and decision.resolved_text:
                unit.content = fix_mojibake(decision.resolved_text)
            continue
        found = locate(decision.anchor, unit.content) if decision.anchor else None
        if found is None:
            if missing_decisions is not None:
                missing_decisions.add(issue.id)
            continue
        if decision.decision in ('accepted', 'edited') and decision.resolved_text:
            unit.content = (unit.content[:found.start] + fix_mojibake(decision.resolved_text)
                            + unit.content[found.end:])
    return draft.model_copy(update={'units':[by_unit[u.unit_id] for u in draft.units]})


def load_resolved_draft(lesson_dir: str, *, missing_decisions: Optional[Set[str]] = None) -> Draft:
    """Carica il draft con le decisioni del ledger scientifiche già applicate —
    la stessa vista che build.py usa per generare i documenti finali.

    Qualunque consumatore che mostra all'utente, o ragiona su, il testo di un'unità
    didattica (es. il recall) deve usare questa funzione invece di rt.pipeline.rewrite
    .load_draft(): il draft grezzo non riflette le correzioni che l'utente ha approvato
    in review, e usarlo direttamente li fa divergere silenziosamente da quello che
    l'utente ha davvero studiato."""
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review import load_science_issues

    from rt.pipeline.document_edits import edited_unit_dates

    draft = load_draft(lesson_dir)
    ledger = load_ledger(lesson_dir)
    science_issues = load_science_issues(lesson_dir)
    return apply_decisions_to_draft(draft, ledger, science_issues, edited_unit_dates(lesson_dir),
                                    missing_decisions=missing_decisions)


def resolved_unit_content(lesson_dir: str, issue: ScienceIssue, draft: Optional[Draft] = None) -> Optional[str]:
    """Testo dell'unità come appare nel documento, anche per issue agganciate al segmento."""
    draft = draft if draft is not None else load_resolved_draft(lesson_dir)
    unit = next((u for u in draft.units if u.unit_id == issue.unit_id), None)
    if unit is None and issue.segment_id:
        unit = next((u for u in draft.units if issue.segment_id in u.source_segment_ids), None)
    return unit.content if unit else None


def extract_context_sentence(content: str, target: str, fallback_target: str = "", highlight: bool = True) -> str:
    """
    Estrae la singola frase dal testo del draft in cui compare il target (o il fallback),
    evidenziando il termine tra parentesi quadre ([termine]) se highlight=True, senza puntini di sospensione.
    """
    if not content:
        return ""
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    targets = [t.strip() for t in [target, fallback_target] if t and t.strip()]

    # 1. Ricerca frase esatta con match per target o fallback
    for term in targets:
        term_esc = re.escape(term)
        pattern = re.compile(rf"({term_esc})", re.IGNORECASE)
        for p in paragraphs:
            sentences = re.split(r"(?<=[.!?])\s+", p)
            for s in sentences:
                s_clean = re.sub(r"^[#*\-\d\.\s]+", "", s).strip()
                if pattern.search(s_clean):
                    return pattern.sub(r"[\1]", s_clean, count=1) if highlight else s_clean

    # 2. Se non trovato come stringa intera, cerca per parole significative (>= 4 caratteri)
    words = [w for t in targets for w in re.findall(r"\b[A-Za-z0-9_-]{4,}\b", t)]
    words.sort(key=len, reverse=True)
    for w in words:
        w_esc = re.escape(w)
        pattern = re.compile(rf"(\b{w_esc}\b)", re.IGNORECASE)
        for p in paragraphs:
            sentences = re.split(r"(?<=[.!?])\s+", p)
            for s in sentences:
                s_clean = re.sub(r"^[#*\-\d\.\s]+", "", s).strip()
                if pattern.search(s_clean):
                    return pattern.sub(r"[\1]", s_clean, count=1) if highlight else s_clean

    return ""


def get_pending_issues(lesson_dir: str):
    """Issue scientifiche non ancora decise nel ledger. Ritorna ([], science_issues)."""
    from rt.pipeline.review import load_science_issues

    ledger = load_ledger(lesson_dir)
    decided_ids = {d.issue_id for d in ledger.decisions}
    missing = reconfirmation_issue_ids(lesson_dir)
    sci_issues = [
        iss for iss in load_science_issues(lesson_dir)
        if iss.id not in decided_ids or iss.id in missing
    ]
    return [], sci_issues


def find_science_issue_by_id(lesson_dir: str, issue_id: str):
    from rt.pipeline.review import load_science_issues
    return next((iss for iss in load_science_issues(lesson_dir) if iss.id == issue_id), None)


def resolve_science_accept_text(iss) -> Optional[str]:
    return fix_mojibake(iss.suggested_fix).strip() if iss.suggested_fix else None


def resolve_science_reject_text(iss) -> str:
    return iss.claim



def reconfirmation_issue_ids(lesson_dir: str) -> Set[str]:
    """Decisioni non ritrovate nel replay; nessuna scrittura e nessuna cancellazione."""
    missing: Set[str] = set()
    try:
        load_resolved_draft(lesson_dir, missing_decisions=missing)
    except FileNotFoundError:
        missing.update(d.issue_id for d in load_ledger(lesson_dir).decisions)
    return missing
