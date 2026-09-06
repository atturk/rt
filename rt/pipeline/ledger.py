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
    return os.path.join(lesson_dir, "review_decisions.json")


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
    notes: Optional[str] = None
) -> ReviewDecision:
    """Registra o aggiorna una decisione nel ledger atomico con sanitizzazione UTF-8."""
    ledger = load_ledger(lesson_dir)
    clean_resolved = fix_mojibake(resolved_text) if resolved_text else None
    clean_notes = fix_mojibake(notes) if notes else None
    
    # Se è una decisione scientifica accettata automaticamente, sanifica formule come 'Sostituire con:'
    if decision.lower().strip() == "accepted" and resolved_by.startswith("cli_auto") and clean_resolved:
        sanitized = sanitize_suggested_fix(clean_resolved)
        if sanitized is not None:
            clean_resolved = sanitized
    
    # Se la decisione esiste già per questa issue, aggiornala
    existing_idx = None
    for idx, d in enumerate(ledger.decisions):
        if d.issue_id == issue_id:
            existing_idx = idx
            break
            
    dec_obj = ReviewDecision(
        issue_id=issue_id,
        decision=decision.lower().strip(),
        resolved_text=clean_resolved,
        resolved_by=resolved_by,
        timestamp=datetime.now().isoformat(),
        notes=clean_notes
    )
    
    if existing_idx is not None:
        ledger.decisions[existing_idx] = dec_obj
    else:
        ledger.decisions.append(dec_obj)
        
    save_ledger(ledger, lesson_dir)
    return dec_obj


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
    asr_by_id = {iss.id: iss for iss in asr_issues}
    sci_by_id = {iss.id: iss for iss in science_issues}
    
    updated_units = []
    for unit in draft.units:
        content = fix_mojibake(unit.content)
        
        # 1. Applica decisioni su ASR Issues
        for iss_id, dec in decisions_map.items():
            if iss_id in asr_by_id:
                iss = asr_by_id[iss_id]
                # Se l'issue appartiene a un segmento di questa unità
                if iss.segment_id in unit.source_segment_ids:
                    resolved = fix_mojibake(dec.resolved_text) if dec.resolved_text else None
                    if dec.decision in ("accepted", "edited") and resolved:
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
