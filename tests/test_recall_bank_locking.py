"""
Test per Task 73: concurrent_updates nel demone Telegram e locking del recall bank.
"""
import os
import time
import threading
from unittest.mock import patch, MagicMock
import pytest

from rt.core.models import RecallBank, RecallQuestion, RecallQuestionStatus, RecallQuestionType, RecallAnswer
from rt.pipeline.recall import (
    load_recall_bank,
    save_recall_bank,
    recall_bank_lock,
    get_recall_bank_lock_path,
    record_recall_answer,
    get_next_pending_question,
)

from rt.core.filelock import acquire_file_lock, release_file_lock, file_lock


def test_file_lock_stale_recovery(tmp_path):
    """Verifica che un lock stale (> 30s) venga rimosso e riacquisito con successo."""
    lock_file = str(tmp_path / "test.lock")
    # Crea un file lock artificiale con data nel passato (60 secondi fa)
    with open(lock_file, "w") as f:
        f.write("stale")
    past_time = time.time() - 60
    os.utime(lock_file, (past_time, past_time))

    # L'acquisizione del lock deve avere successo e rimuovere il lock vecchio
    with file_lock(lock_file, stale_sec=30.0):
        assert os.path.exists(lock_file)

    assert not os.path.exists(lock_file)


def test_concurrent_recall_bank_updates_no_lost_updates(tmp_path):
    """Simula due thread concorrenti che aggiungono risposte diverse al recall bank.
    Garantisce che il locking prevenga lost updates."""
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    # Inizializza bank con 2 domande
    q1 = RecallQuestion(id="q1", type=RecallQuestionType.MIRATA, question_text="Domanda 1", unit_ids=["u1"])
    q2 = RecallQuestion(id="q2", type=RecallQuestionType.MIRATA, question_text="Domanda 2", unit_ids=["u1"])
    bank = RecallBank(questions=[q1, q2])
    save_recall_bank(bank, lesson_dir)

    errors = []

    def answer_worker(qid: str, text: str):
        try:
            record_recall_answer(lesson_dir, qid, text, is_voice=False, evaluation="OK")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=answer_worker, args=("q1", "Risposta 1"))
    t2 = threading.Thread(target=answer_worker, args=("q2", "Risposta 2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Errori nei worker concorrenti: {errors}"

    # Verifica stato finale: entrambe le domande devono essere ANSWERED e avere relative risposte
    final_bank = load_recall_bank(lesson_dir)
    assert len(final_bank.answers) == 2
    answered_qids = {a.question_id for a in final_bank.answers}
    assert answered_qids == {"q1", "q2"}
    for q in final_bank.questions:
        assert q.status == RecallQuestionStatus.ANSWERED


def test_banks_with_duplicate_ids_are_repaired_when_a_question_is_asked(tmp_path):
    """Bank scritti prima della correzione: tre domande con lo stesso ID. Chiedere la seconda
    segnava la prima; ora le copie vengono rinumerate e le risposte restano alla loro domanda."""
    from rt.pipeline.recall import get_next_pending_question, load_recall_bank, save_recall_bank
    lesson = str(tmp_path)

    def question(text, status, unit="1.1"):
        return RecallQuestion(id="recall_000001", type=RecallQuestionType.QUIZ, unit_ids=[unit],
                              question_text=text, options=["a", "b", "c", "d"], correct_index=0, status=status)
    bank = RecallBank(questions=[question("prima", RecallQuestionStatus.PENDING),
                                 question("risposta", RecallQuestionStatus.ANSWERED),
                                 question("terza", RecallQuestionStatus.PENDING, "1.2")],
                      answers=[RecallAnswer(question_id="recall_000001", answer_text="a")])
    save_recall_bank(bank, lesson)

    asked = get_next_pending_question(lesson, RecallQuestionType.QUIZ, order="sequenziale", exclude_id=None)
    repaired = load_recall_bank(lesson)
    ids = [q.id for q in repaired.questions]
    assert len(set(ids)) == 3
    answered = next(q for q in repaired.questions if q.question_text == "risposta")
    assert answered.id == "recall_000001" and repaired.answers[0].question_id == answered.id
    assert next(q for q in repaired.questions if q.id == asked.id).status == RecallQuestionStatus.ASKED
    assert sum(q.status == RecallQuestionStatus.ASKED for q in repaired.questions) == 1


def test_refill_merges_questions_without_overwriting_concurrent_answer(tmp_path, monkeypatch):
    """Durante generate_recall_batch (refill), una risposta salvata mentre l'LLM lavora
    non viene sovrascritta quando il refill salva le nuove domande sotto lock."""
    from rt.core.models import (
        DraftUnit, Draft, RecallMirataGenerationResult,
    )
    from rt.pipeline import recall as recall_mod

    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, ".rt"), exist_ok=True)

    q_existing = RecallQuestion(
        id="recall_000001",
        type=RecallQuestionType.MIRATA,
        unit_ids=["1.1"],
        question_text="Domanda già posta?",
        status=RecallQuestionStatus.ASKED,
    )
    save_recall_bank(RecallBank(questions=[q_existing]), lesson_dir)

    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Unità 1",
                start_segment_id="s1",
                end_segment_id="s1",
                source_segment_ids=["s1"],
                content="Contenuto esteso della prima unità didattica.",
            )
        ],
    )
    monkeypatch.setattr(recall_mod, "load_resolved_draft", lambda _: draft)
    monkeypatch.setattr("rt.services.unit_relevance.refresh", lambda *a, **kw: None)
    monkeypatch.setattr("rt.services.unit_relevance.recall_assessment", lambda *a, **kw: {"state": "didactic", "level": 1})
    monkeypatch.setattr("rt.services.recall_units.selected_units", lambda _: list(draft.units))
    monkeypatch.setattr("rt.services.recall_units.selected_unit_ids", lambda _: {"1.1"})
    monkeypatch.setattr("rt.pipeline.ledger.get_pending_issues", lambda _: (None, []))
    monkeypatch.setattr("rt.services.recall_rules.prepare", lambda *a, **kw: [])
    monkeypatch.setattr("rt.services.recall_rules.filter_group", lambda qs, *a, **kw: qs)
    monkeypatch.setattr("rt.services.recall_context.lesson_context", lambda _: {"materia": "Biologia"})

    def fake_call_structured(self, **kwargs):
        # Simula una risposta salvata da recall_evaluate mentre il modello del refill sta girando (fuori lock)
        record_recall_answer(
            lesson_dir,
            "recall_000001",
            "Risposta salvata in parallelo.",
            evaluation="Ottima risposta.",
            outcome="corretta",
            correttezza=95,
            completezza=90,
            attinenza=95,
        )
        return RecallMirataGenerationResult.model_validate({
            "questions": [
                {
                    "type": "mirata",
                    "question_text": "Nuova domanda generata durante il refill su Unità 1?",
                }
            ]
        })

    monkeypatch.setattr(recall_mod.LLMClient, "call_structured", fake_call_structured)

    saved = recall_mod.generate_recall_batch(
        lesson_dir,
        RecallQuestionType.MIRATA,
        count=1,
        few_shot_examples=[],
        force_mock=False,
        regenerate=True,
    )
    assert len(saved) == 1

    final_bank = load_recall_bank(lesson_dir)
    assert len(final_bank.questions) == 2
    assert len(final_bank.answers) == 1
    assert final_bank.answers[0].answer_text == "Risposta salvata in parallelo."
    assert final_bank.answers[0].outcome == "corretta"
    q1 = next(q for q in final_bank.questions if q.id == "recall_000001")
    assert q1.status == RecallQuestionStatus.ANSWERED
