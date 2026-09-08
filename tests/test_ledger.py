"""
Unit tests per rt.pipeline.ledger
"""

import pytest
from rt.core.models import (
    Draft, DraftUnit, ASRIssue, ASRLevel,
    ScienceIssue, ScienceType, ScienceSeverity
)
from rt.pipeline.ledger import (
    load_ledger, save_ledger, record_decision,
    apply_decisions_to_draft
)


def test_record_and_update_decision(tmp_path):
    lesson_dir = str(tmp_path)
    
    # Registra una decisione
    dec1 = record_decision(
        lesson_dir=lesson_dir,
        issue_id="asr_000001",
        decision="accepted",
        resolved_text="glicerolo chinasi"
    )
    assert dec1.decision == "accepted"
    
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_000001"
    assert ledger.decisions[0].resolved_text == "glicerolo chinasi"
    
    # Aggiorna la stessa decisione (append-only ledger: aggiunge nuova decisione, l'ultima è quella attiva)
    dec2 = record_decision(
        lesson_dir=lesson_dir,
        issue_id="asr_000001",
        decision="edited",
        resolved_text="glicerolo-chinasi mitocondriale"
    )
    assert dec2.decision == "edited"
    
    ledger_updated = load_ledger(lesson_dir)
    assert len(ledger_updated.decisions) == 2
    assert ledger_updated.decisions[-1].decision == "edited"
    assert ledger_updated.decisions[-1].resolved_text == "glicerolo-chinasi mitocondriale"



def test_apply_decisions_to_draft(tmp_path):
    lesson_dir = str(tmp_path)
    
    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Attivazione del glicerolo",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                content="L'enzima licorolo finansi converte il glicerolo in glicerolo-3-fosfato."
            )
        ]
    )
    
    asr_issue = ASRIssue(
        id="asr_000001",
        segment_id="seg_000001",
        source_text="licorolo finansi",
        candidate="glicerolo chinasi",
        confidence=0.88,
        level=ASRLevel.YELLOW,
        reason="Errore fonetico"
    )
    
    record_decision(
        lesson_dir=lesson_dir,
        issue_id="asr_000001",
        decision="accepted",
        resolved_text="glicerolo chinasi"
    )
    
    ledger = load_ledger(lesson_dir)
    updated_draft = apply_decisions_to_draft(
        draft=draft,
        ledger=ledger,
        asr_issues=[asr_issue],
        science_issues=[]
    )
    
    assert "glicerolo chinasi" in updated_draft.units[0].content
    assert "licorolo finansi" not in updated_draft.units[0].content


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
        asr_issues=[],
        science_issues=[sci_issue]
    )
    
    u_content = updated_draft.units[0].content
    assert "Sostituire con:" not in u_content
    assert "La beta-ossidazione è un processo che deve essere finemente regolato per evitare sprechi." in u_content
    # Nessuna duplicazione del resto della frase
    assert "che deve essere regolato" not in u_content
    assert "La regolazione avviene a livello di enzimi chiave." in u_content

