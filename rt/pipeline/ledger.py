"""
rt.pipeline.ledger
Gestione deterministica del Decision Ledger (review_decisions.json) e interfaccia Human-in-the-Loop.
Registra ogni decisione in modo riproducibile e non ri-chiede decisioni già convalidate.
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional
from rt.core.models import DecisionLedger, ReviewDecision, ASRIssue, ScienceIssue, Draft
from rt.core.encoding import fix_mojibake, sanitize_object_encoding
from rt.core.lesson_paths import lesson_path


def sanitize_suggested_fix(text: Optional[str]) -> Optional[str]:
    """
    Estrae e sanifica il testo letterale di correzione rimuovendo formule metatestuali
    (es. 'Sostituire con: ...', 'Correggere con: ...', 'Riformulare in: ...')
    e virgolette di contorno. Se il suggerimento è un commento discorsivo/guida
    (es. 'Precisare che...', 'Chiarire che...'), restituisce None per evitare
    sostituzioni improprie nel testo di studio.
    """
    if not text:
        return None
    s = fix_mojibake(str(text)).strip()
    if s.lower() in ("none", "null", ""):
        return None

    # 1. Match 'Sostituire con: "..."' / 'Sostituire la frase con: "..."' / 'Correggere con: "..."' / 'Riformulare in/come: "..."'
    m = re.match(
        r"^(?:Sostituire(?:\s+(?:la\s+frase|il\s+testo))?\s+con|Correggere(?:\s+la\s+descrizione)?\s+con|Riformulare\s+(?:come|in)):\s*['\"«](.+?)['\"»]\.?\s*$",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()

    # 2. Match 'Sostituire con \'...\' per indicare...'
    m2 = re.match(r"^Sostituire\s+con\s+['\"«](.+?)['\"»](?:\s+per\s+.+)?\.?\s*$", s, re.IGNORECASE | re.DOTALL)
    if m2:
        return m2.group(1).strip()

    # 3. Match 'Riformulare come: \'...\''
    m3 = re.match(r"^Riformulare\s+come:\s*['\"«](.+?)['\"»]\.?\s*$", s, re.IGNORECASE | re.DOTALL)
    if m3:
        return m3.group(1).strip()

    # 4. Pattern discorsivi/esplicativi non sostituibili direttamente come testo continuo
    advisory_starts = [
        "precisare che",
        "chiarire che",
        "specificare che",
        "correggere la descrizione",
        "sostituire '",
        "verificare",
        "si raccomanda",
    ]
    if any(s.lower().startswith(adv) for adv in advisory_starts):
        return None

    # 5. Se racchiuso tra virgolette esterne
    m_quotes = re.match(r"^['\"«](.+?)['\"»]\.?$", s, re.DOTALL)
    if m_quotes:
        return m_quotes.group(1).strip()

    return s


def get_ledger_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "review_decisions.json")


def load_ledger(lesson_dir: str) -> DecisionLedger:
    path = get_ledger_path(lesson_dir)
    if not os.path.isfile(path):
        return DecisionLedger(schema_version="1.0", decisions=[])
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cleaned_data = sanitize_object_encoding(data)
        return DecisionLedger.model_validate(cleaned_data)
    except Exception:
        return DecisionLedger(schema_version="1.0", decisions=[])


def save_ledger(ledger: DecisionLedger, lesson_dir: str) -> None:
    path = get_ledger_path(lesson_dir)
    data = sanitize_object_encoding(ledger.model_dump(mode="json"))
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def record_decision(
    lesson_dir: str,
    issue_id: str,
    decision: str,
    resolved_text: Optional[str] = None,
    resolved_by: str = "user",
    notes: Optional[str] = None,
    original_context: Optional[str] = None,
) -> ReviewDecision:
    """Registra una decisione nel ledger atomico append-only con sanitizzazione UTF-8."""
    ledger = load_ledger(lesson_dir)
    clean_resolved = fix_mojibake(resolved_text) if resolved_text else None
    clean_notes = fix_mojibake(notes) if notes else None
    clean_context = fix_mojibake(original_context) if original_context else None
    
    # Se è una decisione scientifica accettata automaticamente, sanifica formule come 'Sostituire con:'
    if decision.lower().strip() == "accepted" and resolved_by.startswith("cli_auto") and clean_resolved:
        sanitized = sanitize_suggested_fix(clean_resolved)
        if sanitized is not None:
            clean_resolved = sanitized
    
    dec_obj = ReviewDecision(
        issue_id=issue_id,
        decision=decision.lower().strip(),
        resolved_text=clean_resolved,
        resolved_by=resolved_by,
        timestamp=datetime.now().isoformat(),
        notes=clean_notes,
        original_context=clean_context,
    )
    
    ledger.decisions.append(dec_obj)
    save_ledger(ledger, lesson_dir)

    return dec_obj



def revert_last_decision(lesson_dir: str, issue_id: str) -> bool:
    """Rimuove l'ultima voce per issue_id dal ledger (append-only). Ritorna False se non trovata."""
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
    ledger = load_ledger(lesson_dir)
    original_count = len(ledger.decisions)
    ledger.decisions = [d for d in ledger.decisions if not d.issue_id.startswith(prefix)]
    removed_count = original_count - len(ledger.decisions)
    if removed_count > 0:
        save_ledger(ledger, lesson_dir)
    return removed_count


def apply_asr_decisions_to_text(
    content: str,
    asr_issues: List[ASRIssue],
    decisions_map: Dict[str, ReviewDecision],
    target_segment_ids: Optional[List[str]] = None,
) -> str:
    """
    Applica al testo le correzioni ASR decise nel ledger per i segmenti specificati
    (o per tutti i segmenti se target_segment_ids è None).
    """
    asr_by_id = {iss.id: iss for iss in asr_issues}
    content = fix_mojibake(content)
    
    for iss_id, dec in decisions_map.items():
        if iss_id in asr_by_id:
            iss = asr_by_id[iss_id]
            if target_segment_ids is not None and iss.segment_id not in target_segment_ids:
                continue
            resolved = fix_mojibake(dec.resolved_text) if dec.resolved_text else None
            orig_ctx = fix_mojibake(dec.original_context) if dec.original_context else None
            if dec.decision in ("accepted", "edited") and resolved:
                if orig_ctx:
                    if orig_ctx in content:
                        content = content.replace(orig_ctx, resolved, 1)
                else:
                    candidate = fix_mojibake(iss.candidate) if iss.candidate else ""
                    source = fix_mojibake(iss.source_text) if iss.source_text else ""
                    if candidate and candidate in content:
                        content = content.replace(candidate, resolved, 1)
                    elif source and source in content:
                        content = content.replace(source, resolved, 1)
            elif dec.decision == "rejected":
                candidate = fix_mojibake(iss.candidate) if iss.candidate else ""
                source = fix_mojibake(iss.source_text) if iss.source_text else ""
                if candidate and candidate in content:
                    content = content.replace(candidate, source, 1)
                    
    return content


def apply_decisions_to_draft(
    draft: Draft,
    ledger: DecisionLedger,
    asr_issues: List[ASRIssue],
    science_issues: List[ScienceIssue]
) -> Draft:
    """
    Applica deterministicamente al draft le decisioni convalidate dal ledger.
    Ogni sostituzione viene applicata una sola volta garantendo idempotenza e conformità UTF-8.
    """
    decisions_map: Dict[str, ReviewDecision] = {d.issue_id: d for d in ledger.decisions}
    sci_by_id = {iss.id: iss for iss in science_issues}
    
    updated_units = []
    for unit in draft.units:
        content = fix_mojibake(unit.content)
        
        # 1. Applica decisioni su ASR Issues
        content = apply_asr_decisions_to_text(content, asr_issues, decisions_map, unit.source_segment_ids)
                            
        # 2. Applica decisioni su Science Issues
        for iss_id, dec in decisions_map.items():
            if iss_id in sci_by_id:
                s_iss = sci_by_id[iss_id]
                if s_iss.unit_id == unit.unit_id or (s_iss.segment_id and s_iss.segment_id in unit.source_segment_ids):
                    raw_resolved = dec.resolved_text
                    resolved = sanitize_suggested_fix(raw_resolved) if dec.decision == "accepted" else (fix_mojibake(raw_resolved) if raw_resolved else None)
                    if dec.decision in ("accepted", "edited") and resolved:
                        claim_clean = fix_mojibake(s_iss.claim)
                        claim_raw = s_iss.claim
                        target = None
                        if claim_clean in content:
                            target = claim_clean
                        elif claim_raw in content:
                            target = claim_raw
                            
                        if target:
                            # Se la correzione è una frase completa e il claim era un frammento,
                            # controlliamo se la sostituzione risolve l'intera frase per evitare duplicazioni sintattiche
                            idx = content.find(target)
                            end_sent = content.find(".", idx)
                            if end_sent != -1 and resolved.strip().endswith("."):
                                full_sent = content[idx : end_sent + 1].strip()
                                w_clean = set(resolved.lower().split())
                                w_sent = set(full_sent.lower().split())
                                overlap = len(w_clean & w_sent) / max(1, len(w_sent))
                                if overlap > 0.4:
                                    target = full_sent
                            content = content.replace(target, resolved, 1)
                            
        unit_copy = unit.model_copy(update={
            "title": fix_mojibake(unit.title),
            "content": fix_mojibake(content)
        })
        updated_units.append(unit_copy)
        
    return Draft(schema_version=draft.schema_version, lesson_id=draft.lesson_id, units=updated_units)


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
    """Issue ASR (YELLOW/RED) e scientifiche non ancora decise nel ledger. Ritorna (asr_issues, science_issues)."""
    from rt.core.models import ASRLevel
    from rt.pipeline.review_asr import load_asr_issues
    from rt.pipeline.review_science import load_science_issues

    ledger = load_ledger(lesson_dir)
    decided_ids = {d.issue_id for d in ledger.decisions}
    asr_issues = [
        iss for iss in load_asr_issues(lesson_dir)
        if iss.level in (ASRLevel.YELLOW, ASRLevel.RED) and iss.id not in decided_ids
    ]
    sci_issues = [
        iss for iss in load_science_issues(lesson_dir)
        if iss.id not in decided_ids
    ]
    return asr_issues, sci_issues


def find_asr_issue_by_id(lesson_dir: str, issue_id: str):
    from rt.pipeline.review_asr import load_asr_issues
    return next((iss for iss in load_asr_issues(lesson_dir) if iss.id == issue_id), None)


def find_science_issue_by_id(lesson_dir: str, issue_id: str):
    from rt.pipeline.review_science import load_science_issues
    return next((iss for iss in load_science_issues(lesson_dir) if iss.id == issue_id), None)


def resolve_asr_accept_text(iss) -> str:
    return iss.candidate


def resolve_asr_reject_text(iss) -> str:
    return iss.source_text


def resolve_science_accept_text(iss) -> Optional[str]:
    return sanitize_suggested_fix(iss.suggested_fix)


def resolve_science_reject_text(iss) -> str:
    return iss.claim

