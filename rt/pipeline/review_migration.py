"""Compatibilità delle lezioni storiche: nessuna chiamata al modello.

La logica precedente resta qui esclusivamente per ricostruire le ancore e
confrontare il testo durante la migrazione, senza alterare la bozza.
"""
import re
import threading
from typing import Dict, List, Optional
from rt.core.models import Draft, DecisionLedger, ReviewDecision, ScienceIssue, ScienceType
from rt.core.encoding import fix_mojibake
from rt.pipeline.anchors import make_anchor, find_quote

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

def replace_claim(content: str, claim: str, resolved: str) -> str:
    """Sostituisce il claim, allargando alla frase solo entro lo stesso paragrafo."""
    start = content.find(claim)
    if start < 0:
        return content
    end = start + len(claim)
    paragraph_end = content.find("\n", start)
    if paragraph_end < 0:
        paragraph_end = len(content)
    if end <= paragraph_end and resolved.strip().endswith((".", "!", "?")):
        # La fine deve comprendere tutto il claim: un decimale o un'abbreviazione
        # interna non possono troncarlo.
        match = re.search(r"[.!?](?=\s|$)", content[max(start, end - 1):paragraph_end])
        if match:
            sentence_end = max(start, end - 1) + match.end()
            sentence = content[start:sentence_end]
            words = set(sentence.lower().split())
            overlap = len(words & set(resolved.lower().split())) / max(1, len(words))
            if overlap > 0.4:
                end = sentence_end
    return content[:start] + resolved + content[end:]

def legacy_apply_decisions(
    draft: Draft,
    ledger: DecisionLedger,
    science_issues: List[ScienceIssue],
    edited_units: Optional[Dict[str, str]] = None,
) -> Draft:
    """
    Applica deterministicamente al draft le decisioni convalidate dal ledger.
    Ogni sostituzione viene applicata una sola volta garantendo idempotenza e conformità UTF-8.
    Per le unità modificate a mano si applicano solo le decisioni successive alla modifica.
    """
    decisions_map: Dict[str, ReviewDecision] = {d.issue_id: d for d in ledger.decisions}
    sci_by_id = {iss.id: iss for iss in science_issues}
    # Ultima decisione per issue, nell'ordine delle ultime voci del ledger.
    ordered = [d for d in ledger.decisions if decisions_map[d.issue_id] is d]
    paragraph_types = {ScienceType.ERR_ASR_ST, ScienceType.ERR_ASR_LLM, ScienceType.ERR_REWRITE_DRIFT}
    ordered.sort(key=lambda d: sci_by_id[d.issue_id].type not in paragraph_types
                 if d.issue_id in sci_by_id else True)
    
    updated_units = []
    for unit in draft.units:
        content = fix_mojibake(unit.content)
        paragraph_date = None
        # Applica decisioni su Science Issues
        for dec in ordered:
            iss_id = dec.issue_id
            if edited_units and unit.unit_id in edited_units and dec.timestamp <= edited_units[unit.unit_id]:
                continue
            if iss_id in sci_by_id:
                s_iss = sci_by_id[iss_id]
                if s_iss.unit_id == unit.unit_id or (s_iss.segment_id and s_iss.segment_id in unit.source_segment_ids):
                    if s_iss.type in (
                        ScienceType.ERR_ASR_ST,
                        getattr(ScienceType, "ERR_ASR_LLM", "ERR_ASR_LLM"),
                        getattr(ScienceType, "ERR_REWRITE_DRIFT", "ERR_REWRITE_DRIFT"),
                    ):
                        if dec.decision == "accepted":
                            continue
                        elif dec.decision == "edited" and dec.resolved_text:
                            content = fix_mojibake(dec.resolved_text)
                            paragraph_date = dec.timestamp
                            continue

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
                            # Una modifica di paragrafo parte dal testo risolto:
                            # le correzioni precedenti già dentro quel testo non
                            # vanno ripetute se contengono il proprio claim.
                            fixed_at = content.find(resolved)
                            claim_at = content.find(target)
                            if paragraph_date and dec.timestamp <= paragraph_date and fixed_at >= 0 and fixed_at <= claim_at < fixed_at + len(resolved):
                                continue
                            content = replace_claim(content, target, resolved)
                            
        unit_copy = unit.model_copy(update={
            "title": fix_mojibake(unit.title),
            "content": fix_mojibake(content)
        })
        updated_units.append(unit_copy)
        
    return Draft(schema_version=draft.schema_version, lesson_id=draft.lesson_id, units=updated_units)

PARAGRAPH_TYPES = {ScienceType.ERR_ASR_ST, ScienceType.ERR_ASR_LLM, ScienceType.ERR_REWRITE_DRIFT}



def _changed_span(before, after, claim):
    """Comprende la citazione e l'eventuale allargamento fatto dalla logica storica."""
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    tail = 0
    while tail < min(len(before), len(after))-start and before[-tail-1] == after[-tail-1]:
        tail += 1
    end = len(before)-tail
    quote = find_quote(before, claim)
    if quote and quote.start <= end and quote.end >= start:
        start = min(start, quote.start)
        end = max(end, quote.end)
    if start == end:
        # Un'inserzione pura si aggancia anche al carattere vicino, senza ancore vuote.
        if end < len(before):
            end += 1
        elif start:
            start -= 1
    return start, end, after[start:len(after)-(len(before)-end)]


def migrate_objects(draft, ledger, issues, edited_units, sequence_floor=0):
    """Converti il registro storico senza cambiare il testo, né perderne le voci.

    I prefissi del registro sono risolti con il codice storico. Le differenze
    diventano sostituzioni esatte; i paragrafi includono così anche le correzioni
    precedenti che il vecchio codice applicava dopo il paragrafo.
    """
    migrated = ledger.model_copy(deep=True)
    migrated.schema_version = '2.0'
    new_issues = [i.model_copy(deep=True) for i in issues]
    by_id = {i.id:i for i in new_issues}
    latest = {d.issue_id:d for d in ledger.decisions}
    active = [d for d in ledger.decisions if latest[d.issue_id] is d]
    number = max([sequence_floor] + [int(value[4:]) for value in
                 [i.id for i in issues]+[d.issue_id for d in ledger.decisions]
                 if value.startswith('sci_') and value[4:].isdigit()])
    prior = []
    output = []
    replacements = {}
    # Le issue aperte si ancorano al testo già risolto che l'utente vedeva.
    final = legacy_apply_decisions(draft, ledger, issues, edited_units)
    final_units = {u.unit_id:u for u in final.units}
    for issue in new_issues:
        unit = final_units.get(issue.unit_id)
        if unit is None and not issue.unit_id and issue.segment_id:
            unit = next((u for u in final.units if issue.segment_id in u.source_segment_ids), None)
            if unit:
                issue.unit_id = unit.unit_id
        found = find_quote(unit.content, issue.claim) if unit else None
        issue.anchor = make_anchor(unit.content, found.start, found.end) if found else None
        if issue.type not in PARAGRAPH_TYPES:
            issue.suggested_fix = sanitize_suggested_fix(issue.suggested_fix)
    for old in active:
        before = legacy_apply_decisions(draft, DecisionLedger(decisions=prior), issues, edited_units)
        prior.append(old)
        after = legacy_apply_decisions(draft, DecisionLedger(decisions=prior), issues, edited_units)
        original = by_id.get(old.issue_id)
        converted = old.model_copy(deep=True)
        converted.anchor = None
        if old.decision == 'accepted' and original and original.type not in PARAGRAPH_TYPES:
            converted.resolved_text = sanitize_suggested_fix(old.resolved_text)
        before_units = {u.unit_id:u for u in before.units}
        changed = [u for u in after.units if u.content != before_units[u.unit_id].content]
        # Una sostituzione storica poteva raggiungere più unità dello stesso segmento:
        # conserviamo ciascun effetto con una decisione esplicita nella relativa unità.
        if original and not original.unit_id and changed:
            original.unit_id = changed[0].unit_id
        if original:
            unit = before_units.get(original.unit_id)
            if unit:
                found = find_quote(unit.content, original.claim)
                if original.type in PARAGRAPH_TYPES:
                    converted.anchor = make_anchor(unit.content, 0, len(unit.content))
                elif found:
                    converted.anchor = make_anchor(unit.content, found.start, found.end)
        extras = []
        for unit_after in changed:
            unit_before = before_units[unit_after.unit_id]
            if original is None:
                continue
            current_issue = original
            current = converted
            if unit_after.unit_id != original.unit_id:
                number += 1
                current_issue = original.model_copy(deep=True)
                current_issue.id = f'sci_{number:06d}'
                current_issue.unit_id = unit_after.unit_id
                current = old.model_copy(deep=True)
                current.issue_id = current_issue.id
                new_issues.append(current_issue)
                extras.append(current)
            if current_issue.type in PARAGRAPH_TYPES:
                current.anchor = make_anchor(unit_before.content, 0, len(unit_before.content))
                current.resolved_text = unit_after.content
            else:
                literal = (sanitize_suggested_fix(old.resolved_text) if old.decision == 'accepted'
                           else fix_mojibake(old.resolved_text) if old.resolved_text else None)
                claim = fix_mojibake(current_issue.claim)
                start = unit_before.content.find(claim)
                if start >= 0 and literal and replace_claim(unit_before.content, claim, literal) == unit_after.content:
                    end = len(unit_before.content) - (len(unit_after.content) - start - len(literal))
                    replacement = literal
                else:
                    start, end, replacement = _changed_span(unit_before.content, unit_after.content, current_issue.claim)
                current.anchor = make_anchor(unit_before.content, start, end)
                current.resolved_text = replacement
            current_issue.anchor = current.anchor.model_copy(deep=True)
        replacements[old.issue_id] = [converted] + extras
    # Mantiene anche le decisioni superate e i loro campi storici, nella stessa posizione.
    for old in ledger.decisions:
        if latest[old.issue_id] is old:
            output.extend(replacements[old.issue_id])
        else:
            previous = old.model_copy(deep=True)
            issue = by_id.get(old.issue_id)
            previous.anchor = issue.anchor.model_copy(deep=True) if issue and issue.anchor else None
            if old.decision == 'accepted' and issue and issue.type not in PARAGRAPH_TYPES:
                previous.resolved_text = sanitize_suggested_fix(old.resolved_text)
            output.append(previous)
    migrated.decisions = output
    from rt.pipeline.ledger import apply_decisions_to_draft
    replayed = apply_decisions_to_draft(draft, migrated, new_issues, edited_units)
    if [u.content for u in replayed.units] != [u.content for u in final.units]:
        raise ValueError('Migrazione ancore: il testo risolto non coincide con quello storico')
    return migrated, new_issues


_local = threading.local()


def migrate_review_anchors(lesson_dir):
    """Alla prima lettura converte file e DB; rientri della sincronizzazione esclusi."""
    from rt.storage import fs
    from rt.pipeline.ledger import load_ledger, save_ledger
    from rt.pipeline.review import load_science_issues, save_science_issues, get_science_issues_path
    from rt.pipeline.rewrite import load_draft, get_draft_path
    from rt.pipeline.document_edits import edited_unit_dates
    from rt.core.idempotency import get_phase_checkpoint
    busy = getattr(_local, 'busy', set())
    if lesson_dir in busy:
        return
    _local.busy = busy
    busy.add(lesson_dir)
    try:
        ledger = load_ledger(lesson_dir, strict=True, _migrate=False)
        if ledger.schema_version == '2.0' or not fs.isfile(get_draft_path(lesson_dir)):
            return
        if not fs.isfile(get_science_issues_path(lesson_dir)) and not ledger.decisions:
            return
        issues = load_science_issues(lesson_dir, _migrate=False)
        checkpoint, _, _ = get_phase_checkpoint(lesson_dir, 'review')
        migrated, anchored = migrate_objects(load_draft(lesson_dir), ledger, issues,
                                              edited_unit_dates(lesson_dir),
                                              int((checkpoint or {}).get('issue_sequence', 0)))
        save_science_issues(anchored, lesson_dir)
        save_ledger(migrated, lesson_dir)
    finally:
        busy.remove(lesson_dir)
