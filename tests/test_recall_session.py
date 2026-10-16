"""
tests/test_recall_session.py
Stato della sessione di Active Recall, riferimenti alle unità e valutazione delle risposte.
"""
import os
import json

from rt.core.models import (
    RecallQuestion, RecallQuestionType, RecallAnswer,
    SegmentsData, Segment, Draft, DraftUnit,
)
from rt.core.manifest import init_or_update_manifest
from rt.pipeline.recall import save_recall_bank, load_recall_bank
from rt.core.models import RecallBank
from rt.services.recall_service import load_recall_session_state, save_recall_session_state, handle_recall_answer, format_unit_reference


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _setup_lesson(lesson_dir: str, num_units: int = 4):
    os.makedirs(lesson_dir, exist_ok=True)
    segs = [
        Segment(id=f"seg_{i:06d}", index=i, start_seconds=float(i * 10), end_seconds=float(i * 10 + 8),
                start_formatted=f"00:{i*10:02d}", end_formatted=f"00:{i*10+8:02d}", text_raw=f"testo {i}")
        for i in range(1, num_units + 1)
    ]
    seg_data = SegmentsData(schema_version="1.0", audio_file="audio.mp3", audio_duration_seconds=120.0, segments=segs)
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    units = [
        DraftUnit(unit_id=f"{i}.1", title=f"Unita {i}", content=f"Contenuto unita {i}.",
                  start_segment_id=f"seg_{i:06d}", end_segment_id=f"seg_{i:06d}", source_segment_ids=[f"seg_{i:06d}"])
        for i in range(1, num_units + 1)
    ]
    draft = Draft(schema_version="1.0", lesson_id="L1", units=units)
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    init_or_update_manifest(lesson_dir=lesson_dir, lesson_id="L1", date="2026-09-09", subject="TEST",
                             current_state="DRAFT_VALIDATED")
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\nfase_corrente: rewrite_completato\nmateria: TEST\n")


def _make_quiz_question(qid="recall_000001", unit_id="1.1") -> RecallQuestion:
    return RecallQuestion(
        id=qid, type=RecallQuestionType.QUIZ, unit_ids=[unit_id],
        question_text="Qual e' il substrato?", options=["A", "B", "C", "D"], correct_index=1,
        pregenerated_material="B e' corretta perche'...",
    )


def _make_mirata_question(qid="recall_000002", unit_id="1.1") -> RecallQuestion:
    return RecallQuestion(id=qid, type=RecallQuestionType.MIRATA, unit_ids=[unit_id], question_text="Descrivi X.")


# ---------------------------------------------------------------------------
# Stato di sessione (ordine/cursore/domanda corrente)
# ---------------------------------------------------------------------------

class TestSessionState:
    def test_default_state_when_missing(self, tmp_path):
        state = load_recall_session_state(str(tmp_path))
        assert state["order"] == "alternato"
        assert state["unit_cursor"] is None
        assert state["current_question_id"] is None

    def test_round_trip(self, tmp_path):
        save_recall_session_state(str(tmp_path), {"order": "alternato", "unit_cursor": "2.1", "current_question_id": "recall_000005", "force_mock": True})
        state = load_recall_session_state(str(tmp_path))
        assert state == {"order": "alternato", "unit_cursor": "2.1", "current_question_id": "recall_000005", "force_mock": True}

    def test_force_mock_persists_between_calls(self, tmp_path):
        """Il flag mock della sessione sopravvive alle chiamate che non lo ripassano."""
        save_recall_session_state(str(tmp_path), {"order": "sequenziale", "unit_cursor": None, "current_question_id": None, "force_mock": True})
        state = load_recall_session_state(str(tmp_path))
        assert state["force_mock"] is True


# ---------------------------------------------------------------------------
# Riferimenti alle unità e handle_recall_answer (salvataggio + valutazione)
# ---------------------------------------------------------------------------

class TestFormatUnitReference:
    def test_shows_full_content_for_all_unit_ids(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        question = RecallQuestion(
            id="recall_000009", type=RecallQuestionType.VASTA, unit_ids=["1.1", "2.1"],
            question_text="Domanda vasta di prova.",
        )
        text = format_unit_reference(lesson_dir, question)
        assert "Unità 1.1 - Unita 1" in text and "Contenuto unita 1." in text
        assert "Unità 2.1 - Unita 2" in text and "Contenuto unita 2." in text

    def test_empty_string_when_no_units_match(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        question = RecallQuestion(
            id="recall_000010", type=RecallQuestionType.MIRATA, unit_ids=["9.9"],
            question_text="Domanda su unità inesistente.",
        )
        assert format_unit_reference(lesson_dir, question) == ""

    def test_reflects_accepted_science_decision_not_raw_draft(self, tmp_path):
        """Bug reale: il bottone 📖 mostrava il testo grezzo del draft, ignorando le
        correzioni scientifiche già approvate — diverso da quello che l'utente studia
        davvero nel documento finale."""
        from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
        from rt.pipeline.review import get_science_issues_path
        from rt.pipeline.ledger import record_decision

        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)

        sci_issue = ScienceIssue(
            id="sci_000001", type=ScienceType.ERR_CONCETTUALE, severity=ScienceSeverity.LOW,
            unit_id="1.1", segment_id="seg_000001", claim="Contenuto unita 1.",
            reason="Dettaglio approvato dal docente.",
            suggested_fix="Contenuto unita 1, RIVISTO E APPROVATO.",
        )
        with open(get_science_issues_path(lesson_dir), "w", encoding="utf-8") as f:
            json.dump([sci_issue.model_dump(mode="json")], f)
        record_decision(lesson_dir=lesson_dir, issue_id="sci_000001", decision="accepted", resolved_text=sci_issue.suggested_fix)

        question = RecallQuestion(
            id="recall_000011", type=RecallQuestionType.MIRATA, unit_ids=["1.1"],
            question_text="Domanda di prova.",
        )
        text = format_unit_reference(lesson_dir, question)
        assert "RIVISTO E APPROVATO" in text


class TestHandleRecallAnswer:
    def test_mirata_answer_is_evaluated_and_saved(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        evaluation = handle_recall_answer(lesson_dir, "recall_000002", "La mia risposta.", is_voice=False, force_mock=True)
        assert evaluation is not None
        assert "Correttezza" in evaluation and "Completezza" in evaluation

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000002")
        assert ans.answer_text == "La mia risposta."
        assert ans.is_voice is False
        assert ans.evaluation == evaluation

    def test_quiz_returns_none(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        result = handle_recall_answer(lesson_dir, "recall_000001", "B", is_voice=False, force_mock=True)
        assert result is None


# ---------------------------------------------------------------------------
# Storico delle risposte
# ---------------------------------------------------------------------------


def test_question_list_exposes_the_latest_actual_attempt_and_summary_keeps_legacy_answers(tmp_path):
    from rt.services.recall_service import question_list, recall_history
    from rt.services.recall_sessions import summarize
    path = str(tmp_path)
    _setup_lesson(path)
    q = _make_quiz_question()
    answers = [
        RecallAnswer(question_id=q.id, answer_text='B', outcome='corretta', answered_at='2026-10-01T10:00:00'),
        RecallAnswer(question_id=q.id, answer_text='', vote='up', answered_at='2026-10-01T12:00:00'),
        RecallAnswer(question_id=q.id, answer_text='A', outcome='sbagliata', answered_at='2026-10-01T11:00:00'),
    ]
    save_recall_bank(RecallBank(questions=[q], answers=answers), path)
    assert question_list(path)['questions'][0]['outcome'] == 'sbagliata'
    assert recall_history(path)['questions'][0]['outcome'] == 'sbagliata'
    legacy = RecallAnswer(question_id=q.id, answer_text='B')
    save_recall_bank(RecallBank(questions=[q], answers=[legacy]), path)
    assert summarize(path, question_ids=[q.id])['correct'] == 1
    q.options[1] = '[Non lo so]'
    save_recall_bank(RecallBank(questions=[q], answers=[RecallAnswer(
        question_id=q.id, answer_text='[Non lo so]', dont_know=True, outcome='sbagliata')]), path)
    assert summarize(path, question_ids=[q.id])['correct'] == 0
