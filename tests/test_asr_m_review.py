"""
tests.test_asr_m_review
Test specifici per la nuova modalità 'M' (Modifica) nella review ASR:
- Modifica a livello di frase/unità del draft senza marcatori
- Salvataggio e persistenza del campo original_context nel ReviewDecision e DecisionLedger
- Sostituzione deterministica tramite apply_asr_decisions_to_text con original_context
- Retrocompatibilità per decisioni storiche senza original_context
- Gestione di: nessuna modifica, testo vuoto, fallback su intera unità, fallback su trascrizione grezza
"""

import os
import json
import pytest
from unittest.mock import patch
from rt.core.models import (
    ASRIssue, ASRLevel, ReviewDecision, DecisionLedger, SegmentsData, Segment, Draft, DraftUnit
)
from rt.pipeline.ledger import (
    record_decision,
    load_ledger,
    apply_asr_decisions_to_text,
    apply_decisions_to_draft,
    extract_context_sentence,
)
from rt.pipeline.issue_review import run_interactive_review


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="audio.wav",
        total_duration=60.0,
        segment_count=3,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="La proteina EPCB regola il metabolismo del ferro."),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="La concentrazione di acidogromina aumenta in fase acuta."),
            Segment(id="seg_000003", index=3, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="Segmento orfano senza corrispondenza di unità."),
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="3.2",
                title="Regolazione del ferro",
                content=(
                    "### 3.2 Regolazione del ferro\n\n"
                    "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro attraverso la degradazione della ferroportina. "
                    "Questo meccanismo previene il sovraccarico sistemico."
                ),
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
            ),
            DraftUnit(
                unit_id="4.1",
                title="Proteine di fase acuta",
                content=(
                    "### 4.1 Proteine di fase acuta\n\n"
                    "Durante la risposta infiammatoria sistemica, i livelli plasmatici di alfa-1 glicoproteina acida aumentano notevolmente, "
                    "fungendo da importante proteina di trasporto e modulatore immunitario."
                ),
                start_segment_id="seg_000002",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000002"],
            ),
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\n")


def test_review_decision_model_original_context():
    # Backward compatibility: deserializzazione di decisioni vecchie prive di original_context
    raw_old = {
        "issue_id": "asr_000001",
        "decision": "accepted",
        "resolved_text": "epcidina",
        "resolved_by": "user",
        "timestamp": "2026-09-09T12:00:00"
    }
    dec_old = ReviewDecision.model_validate(raw_old)
    assert dec_old.original_context is None

    # Nuova decisione con original_context
    raw_new = {
        "issue_id": "asr_000001",
        "decision": "edited",
        "resolved_text": "La proteina epcidina regola il ferro.",
        "resolved_by": "user",
        "timestamp": "2026-09-09T12:00:00",
        "original_context": "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro."
    }
    dec_new = ReviewDecision.model_validate(raw_new)
    assert dec_new.original_context == "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro."


def test_record_decision_with_original_context(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    orig = "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro."
    resolved = "La proteina epcidina regola il ferro."
    dec = record_decision(lesson_dir, "asr_1", "edited", resolved_text=resolved, original_context=orig)

    assert dec.original_context == orig
    assert dec.resolved_text == resolved

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].original_context == orig
    assert ledger.decisions[0].resolved_text == resolved


def test_apply_asr_decisions_with_original_context():
    content = (
        "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro. "
        "Questo meccanismo previene il sovraccarico sistemico."
    )
    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="EPCB", candidate="epcidina", confidence=0.8, level=ASRLevel.YELLOW, reason="fonetica")
    ]
    dec = ReviewDecision(
        issue_id="asr_1",
        decision="edited",
        resolved_text="La proteina epcidina regola il ferro.",
        original_context="La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro."
    )
    decisions_map = {"asr_1": dec}

    updated = apply_asr_decisions_to_text(content, asr_issues, decisions_map)
    assert updated == (
        "La proteina epcidina regola il ferro. "
        "Questo meccanismo previene il sovraccarico sistemico."
    )


def test_apply_asr_decisions_legacy_without_original_context():
    content = "La proteina EPCB regola il ferro."
    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="EPCB", candidate="epcidina", confidence=0.8, level=ASRLevel.YELLOW, reason="fonetica")
    ]
    # Decisione legacy senza original_context
    dec = ReviewDecision(
        issue_id="asr_1",
        decision="accepted",
        resolved_text="epcidina",
        original_context=None
    )
    decisions_map = {"asr_1": dec}

    # Deve sostituire candidate se presente o source_text ("EPCB") con resolved_text
    updated = apply_asr_decisions_to_text(content, asr_issues, decisions_map)
    assert updated == "La proteina epcidina regola il ferro."


def test_interactive_review_m_sentence_found(tmp_path, monkeypatch):
    import sys
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="EPCB", candidate="epcidina", confidence=0.8, level=ASRLevel.YELLOW, reason="fonetica")
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["m"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    editor_content_received = []

    def mock_edit(content):
        editor_content_received.append(content)
        # Rimuove il parentetico
        return (
            "# Commento dell'editor\n"
            "La proteina epcidina regola il ferro attraverso la degradazione della ferroportina."
        )

    with patch("rt.pipeline.issue_review.edit_text_in_editor", side_effect=mock_edit):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    assert len(editor_content_received) == 1
    # Verifica che l'editor abbia ricevuto la frase del draft e il commento appropriato
    assert "Modifica liberamente la frase qui sotto" in editor_content_received[0]
    assert "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro attraverso la degradazione della ferroportina." in editor_content_received[0]

    # Verifica che la decisione contenga original_context
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    dec = ledger.decisions[0]
    assert dec.decision == "edited"
    assert dec.resolved_text == "La proteina epcidina regola il ferro attraverso la degradazione della ferroportina."
    assert dec.original_context == "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro attraverso la degradazione della ferroportina."

    # Verifica che applicando al draft il testo venga aggiornato correttamente
    from rt.pipeline.rewrite import load_draft
    draft = load_draft(lesson_dir)
    updated_draft = apply_decisions_to_draft(draft, ledger, asr_issues, [])
    assert "La proteina epcidina regola il ferro attraverso la degradazione della ferroportina." in updated_draft.units[0].content
    assert "(indicata come EPCB nella trascrizione)" not in updated_draft.units[0].content


def test_interactive_review_m_unit_fallback_when_term_not_in_draft(tmp_path, monkeypatch):
    import sys
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    # candidate="acidoglicoproteina", ma nel draft c'è "alfa-1 glicoproteina acida", source_text="acidogromina"
    asr_issues = [
        ASRIssue(id="asr_2", segment_id="seg_000002", source_text="acidogromina", candidate="acidoglicoproteina", confidence=0.7, level=ASRLevel.YELLOW, reason="fonetica")
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["m"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    editor_content_received = []

    def mock_edit(content):
        editor_content_received.append(content)
        return (
            "# Commento dell'editor\n"
            "### 4.1 Proteine di fase acuta\n\n"
            "Durante la risposta infiammatoria sistemica, i livelli di AGP aumentano notevolmente."
        )

    with patch("rt.pipeline.issue_review.edit_text_in_editor", side_effect=mock_edit):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    assert len(editor_content_received) == 1
    # Verifica che l'editor abbia aperto l'intera unità con il commento fallback
    assert "Termine non trovato letteralmente nel draft" in editor_content_received[0]
    assert "### 4.1 Proteine di fase acuta" in editor_content_received[0]

    ledger = load_ledger(lesson_dir)
    dec = ledger.decisions[0]
    assert dec.decision == "edited"
    assert "i livelli di AGP aumentano notevolmente" in dec.resolved_text
    assert "alfa-1 glicoproteina acida" in dec.original_context

    # Verifica applicazione al draft
    from rt.pipeline.rewrite import load_draft
    draft = load_draft(lesson_dir)
    updated_draft = apply_decisions_to_draft(draft, ledger, asr_issues, [])
    assert "i livelli di AGP aumentano notevolmente." in updated_draft.units[1].content


def test_interactive_review_m_no_changes_and_empty_text(tmp_path, monkeypatch, capsys):
    import sys
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="EPCB", candidate="epcidina", confidence=0.8, level=ASRLevel.YELLOW, reason="fonetica")
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["m", "m", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    edit_results = [
        # Identico all'originale
        "La proteina epcidina (indicata come EPCB nella trascrizione) regola il ferro attraverso la degradazione della ferroportina.",
        # Vuoto (solo commenti)
        "# solo commenti\n\n   \n",
    ]

    with patch("rt.pipeline.issue_review.edit_text_in_editor", side_effect=edit_results):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    out = capsys.readouterr().out
    assert "ASR AMBIGUITY" in out
    assert "Approvato." in out

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"
