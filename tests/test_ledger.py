"""
Unit tests per rt.pipeline.ledger
"""

import pytest
from rt.core.models import (
    Draft, DraftUnit,
    ScienceIssue, ScienceType, ScienceSeverity
)
from rt.pipeline.ledger import (
    load_ledger, save_ledger, record_decision,
    apply_decisions_to_draft, load_resolved_draft
)


def test_record_and_update_decision(tmp_path):
    lesson_dir = str(tmp_path)
    
    # Registra una decisione
    dec1 = record_decision(
        lesson_dir=lesson_dir,
        issue_id="sci_000001",
        decision="accepted",
        resolved_text="glicerolo chinasi"
    )
    assert dec1.issue_id == "sci_000001"
    assert dec1.decision == "accepted"
    assert dec1.resolved_text == "glicerolo chinasi"
    
    # Aggiorna la decisione per la stessa issue
    dec2 = record_decision(
        lesson_dir=lesson_dir,
        issue_id="sci_000001",
        decision="rejected",
        resolved_text="licorolo finansi"
    )
    
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[-1].decision == "rejected"
    assert ledger.decisions[-1].resolved_text == "licorolo finansi"


def test_load_resolved_draft_reflects_accepted_science_decision(tmp_path):
    """Bug reale riscontrato: il recall (domande/valutazioni/riferimento unità) leggeva il
    draft grezzo, ignorando le correzioni scientifiche già approvate dall'utente — l'utente
    veniva interrogato/valutato su un testo diverso da quello che aveva davvero studiato.
    load_resolved_draft() deve restituire lo stesso testo che finisce nel documento finale."""
    from rt.pipeline.rewrite import save_draft
    lesson_dir = str(tmp_path)

    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="1.2",
                title="Limiti pre-PCR",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                content="Fino all'avvento della PCR, Southern e Northern blotting presentavano un limite intrinseco."
            )
        ]
    )
    save_draft(draft, lesson_dir)

    sci_issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.LOW,
        unit_id="1.2",
        segment_id="seg_000001",
        claim="Fino all'avvento della PCR, Southern e Northern blotting presentavano un limite intrinseco.",
        reason="La PCR convenzionale ha lo stesso limite.",
        suggested_fix="Fino all'avvento delle metodologie ad alto rendimento, Southern e Northern blotting e la stessa PCR convenzionale presentavano un limite intrinseco.",
    )
    # save_science_issues salva la lista in science_issues.json (funzione già testata altrove)
    import json
    from rt.pipeline.review import get_science_issues_path
    with open(get_science_issues_path(lesson_dir), "w", encoding="utf-8") as f:
        json.dump([sci_issue.model_dump(mode="json")], f)

    record_decision(
        lesson_dir=lesson_dir, issue_id="sci_000001", decision="accepted",
        resolved_text=sci_issue.suggested_fix,
    )

    resolved = load_resolved_draft(lesson_dir)
    assert "la stessa PCR convenzionale" in resolved.units[0].content

    # Il draft grezzo su disco resta invariato: solo la vista risolta riflette la decisione.
    from rt.pipeline.rewrite import load_draft
    raw = load_draft(lesson_dir)
    assert "la stessa PCR convenzionale" not in raw.units[0].content


def test_sanitize_suggested_fix():
    from rt.pipeline.ledger import sanitize_suggested_fix
    
    assert sanitize_suggested_fix("Sostituire con: 'La beta-ossidazione è un processo finemente regolato.'") == "La beta-ossidazione è un processo finemente regolato."
    assert sanitize_suggested_fix("Correggere con: 'CPT1 è sulla membrana esterna'.") == "CPT1 è sulla membrana esterna"
    assert sanitize_suggested_fix("Riformulare in: 'nei citocromi di tipo b il ferro è coordinato con due residui'.") == "nei citocromi di tipo b il ferro è coordinato con due residui"
    assert sanitize_suggested_fix("Sostituire con 'flavoproteine contenenti FMN' per indicare...") == "flavoproteine contenenti FMN"
    # Advisory notes must return None
    assert sanitize_suggested_fix("Precisare che solo acetoacetato e beta-idrossibutirrato vengono usati.") is None
    assert sanitize_suggested_fix("Chiarire che gli acidi grassi fino a 12C entrano liberi.") is None
    assert sanitize_suggested_fix("Specificare che VLCFA sono >22C.") is None
    assert sanitize_suggested_fix("None") is None
    assert sanitize_suggested_fix(None) is None


def test_apply_science_decision_clean_replacement(tmp_path):
    lesson_dir = str(tmp_path)
    
    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="4.3",
                title="Regolazione della beta-ossidazione",
                start_segment_id="seg_000100",
                end_segment_id="seg_000105",
                source_segment_ids=["seg_000100"],
                content="La beta-ossidazione rappresenta un processo dispendioso che deve essere regolato. La regolazione avviene a livello di enzimi chiave."
            )
        ]
    )
    
    sci_issue = ScienceIssue(
        id="sci_000011",
        type=ScienceType.ERR_RECONSTRUCTION,
        severity=ScienceSeverity.HIGH,
        unit_id="4.3",
        segment_id="seg_000100",
        claim="La beta-ossidazione rappresenta un processo dispendioso",
        reason="La beta-ossidazione produce energia",
        suggested_fix="Sostituire con: 'La beta-ossidazione è un processo che deve essere finemente regolato per evitare sprechi.'",
        status="accepted"
    )
    
    # Registra con cli_auto
    record_decision(
        lesson_dir=lesson_dir,
        issue_id="sci_000011",
        decision="accepted",
        resolved_text=sci_issue.suggested_fix,
        resolved_by="cli_auto"
    )
    
    ledger = load_ledger(lesson_dir)
    updated_draft = apply_decisions_to_draft(
        draft=draft,
        ledger=ledger,
        science_issues=[sci_issue]
    )
    
    u_content = updated_draft.units[0].content
    assert "Sostituire con:" not in u_content
    assert "La beta-ossidazione è un processo che deve essere finemente regolato per evitare sprechi." in u_content
    # Nessuna duplicazione del resto della frase
    assert "che deve essere regolato" not in u_content
    assert "La regolazione avviene a livello di enzimi chiave." in u_content

