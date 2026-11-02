import json
import pytest

from rt.core.models import (
    Draft, DraftUnit, RecallQuestionType, RecallQuestionStatus,
    ScienceIssue, ScienceType, ScienceSeverity, Anchor
)
from rt.pipeline.recall import (
    generate_recall_batch, load_recall_bank, save_recall_bank
)
from rt.pipeline.review import save_science_issues
from rt.services.review_service import record_review_decision, sync_recall_questions_with_review


@pytest.fixture
def lesson_dir(tmp_path):
    d = tmp_path / "lesson"
    d.mkdir()
    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Unità Uno",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                content="Contenuto scientifico dell'unità 1 con concetto errato.",
            ),
            DraftUnit(
                unit_id="1.2",
                title="Unità Due",
                start_segment_id="seg_000002",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000002"],
                content="Contenuto scientifico dell'unità 2 del tutto corretto.",
            ),
        ],
    )
    draft_path = d / "draft.json"
    draft_path.write_text(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
    return str(d)


def test_unit_with_pending_conceptual_issue_is_skipped(lesson_dir):
    issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        claim="concetto errato",
        reason="Errore concettuale",
        anchor=Anchor(quote="concetto errato", start=46, end=61),
    )
    save_science_issues([issue], lesson_dir)

    reports = []
    def progress_callback(cur, tot, msg, **kwargs):
        reports.append(msg)

    questions = generate_recall_batch(
        lesson_dir, RecallQuestionType.QUIZ, count=None, few_shot_examples=[],
        force_mock=True, progress=progress_callback
    )

    # Verifica che il report indichi che 1 unità è stata saltata
    assert any("1 unità saltata: ha segnalazioni da decidere nella Verifica" in r for r in reports)
    # Nessuna domanda deve essere generata sull'unità 1.1
    assert questions
    for q in questions:
        assert "1.1" not in q.unit_ids
        assert "1.2" in q.unit_ids


def test_explicit_unit_ids_generates_with_da_verificare(lesson_dir):
    issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        claim="concetto errato",
        reason="Errore concettuale",
        anchor=Anchor(quote="concetto errato", start=46, end=61),
    )
    save_science_issues([issue], lesson_dir)

    questions = generate_recall_batch(
        lesson_dir, RecallQuestionType.QUIZ, count=2, few_shot_examples=[],
        force_mock=True, unit_ids=["1.1"]
    )

    assert questions
    for q in questions:
        assert "1.1" in q.unit_ids
        assert q.da_verificare is True


def test_asr_issue_not_skipped(lesson_dir):
    # Le issue ASR non devono bloccare la generazione delle domande sul recall
    issue = ScienceIssue(
        id="sci_000002",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.LOW,
        unit_id="1.1",
        claim="concetto errato",
        reason="ASR degradato",
    )
    save_science_issues([issue], lesson_dir)

    reports = []
    questions = generate_recall_batch(
        lesson_dir, RecallQuestionType.QUIZ, count=None, few_shot_examples=[],
        force_mock=True, progress=lambda c, t, m, **kw: reports.append(m)
    )

    assert not any("saltata" in r for r in reports)
    # 1.1 genera normalmente
    assert any("1.1" in q.unit_ids for q in questions)


def test_decision_resolution_updates_recall_questions(lesson_dir):
    issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        claim="concetto errato",
        reason="Errore concettuale",
        suggested_fix="concetto corretto",
        anchor=Anchor(quote="concetto errato", start=46, end=61),
    )
    save_science_issues([issue], lesson_dir)

    # Genera con unit_ids esplicito -> da_verificare=True
    questions = generate_recall_batch(
        lesson_dir, RecallQuestionType.QUIZ, count=2, few_shot_examples=[],
        force_mock=True, unit_ids=["1.1"]
    )
    assert all(q.da_verificare is True for q in questions)

    # 1. Se rifiutata (testo NON cambiato): le domande restano e da_verificare diventa False
    record_review_decision(lesson_dir, "sci_000001", "rejected", channel="web")
    bank = load_recall_bank(lesson_dir)
    q1 = next(q for q in bank.questions if "1.1" in q.unit_ids)
    assert q1.status == RecallQuestionStatus.PENDING
    assert q1.da_verificare is False

    # 2. Se una decisione successiva cambia il testo: le domande diventano stale
    issue2 = ScienceIssue(
        id="sci_000003",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        claim="concetto errato",
        reason="Errore concettuale",
        suggested_fix="concetto corretto",
        anchor=Anchor(quote="concetto errato", start=46, end=61),
    )
    save_science_issues([issue, issue2], lesson_dir)
    record_review_decision(lesson_dir, "sci_000003", "accepted", resolved_text="concetto corretto", channel="web")
    bank = load_recall_bank(lesson_dir)
    q1 = next(q for q in bank.questions if "1.1" in q.unit_ids)
    assert q1.status == RecallQuestionStatus.DISCARDED
    assert "stale" in q1.discard_reasons
