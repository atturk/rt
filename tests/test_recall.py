"""
tests/test_recall.py
Acceptance tests per il motore di Active Recall (Fase D1).

Copertura:
1. Modelli Pydantic  – RecallQuestion/RecallAnswer/RecallBank (validazione base)
2. Persistenza       – load/save round-trip, scrittura atomica (no .tmp residuo)
3. get_reserve_count – conta solo le PENDING del tipo richiesto
4. get_next_pending_question – 3 modalità d'ordine + marcatura ASKED
5. record_recall_answer / record_recall_vote
6. Few-shot pool     – FIFO ≤ 5, separazione per tipo, lista vuota su tipo mai votato
7. generate_recall_batch (force_mock=True) – per i 3 tipi
"""

import os
import json
import pytest

from rt.core.models import (
    RecallQuestion, RecallQuestionType, RecallQuestionStatus,
    RecallAnswer, RecallBank, DraftUnit, Draft,
)
from rt.pipeline.recall import (
    load_recall_bank, save_recall_bank, get_recall_bank_path,
    get_reserve_count,
    get_next_pending_question, skip_recall_question,
    record_recall_answer, record_recall_vote,
    record_fewshot_vote, load_fewshot_examples,
    generate_recall_batch,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def lesson_dir(tmp_path):
    """Cartella lezione temporanea con un draft.json minimale."""
    d = tmp_path / "lesson"
    d.mkdir()
    # Minimal draft.json for generate_recall_batch
    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id=f"{i}.1",
                title=f"Unita' {i}",
                start_segment_id=f"seg_{i:06d}",
                end_segment_id=f"seg_{i:06d}",
                source_segment_ids=[f"seg_{i:06d}"],
                content=f"Contenuto accademico dell'unita' {i}.",
            )
            for i in range(1, 7)
        ],
    )
    draft_path = d / "draft.json"
    draft_path.write_text(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
    return str(d)


@pytest.fixture
def fewshot_dir(tmp_path):
    """Cartella separata per il few-shot store globale."""
    d = tmp_path / "state"
    d.mkdir()
    return str(d)


def _make_question(qid: str, qtype: RecallQuestionType, unit_id: str,
                   status: RecallQuestionStatus = RecallQuestionStatus.PENDING) -> RecallQuestion:
    opts = ["A", "B", "C", "D"] if qtype == RecallQuestionType.QUIZ else None
    cidx = 0 if qtype == RecallQuestionType.QUIZ else None
    prematerial = "spiegazione" if qtype in (RecallQuestionType.QUIZ, RecallQuestionType.VASTA) else None
    unit_ids = [unit_id] if qtype != RecallQuestionType.VASTA else [unit_id, "2.1"]
    return RecallQuestion(
        id=qid,
        type=qtype,
        unit_ids=unit_ids,
        question_text=f"Domanda {qid}?",
        options=opts,
        correct_index=cidx,
        pregenerated_material=prematerial,
        status=status,
    )


# -----------------------------------------------------------------------
# 1. Validazione Pydantic
# -----------------------------------------------------------------------

class TestModels:
    def test_recall_question_basic(self):
        q = RecallQuestion(
            id="recall_000001",
            type=RecallQuestionType.QUIZ,
            unit_ids=["1.1"],
            question_text="Qual è il substrato?",
            options=["A", "B", "C", "D"],
            correct_index=2,
            pregenerated_material="A è corretta perché...",
        )
        assert q.status == RecallQuestionStatus.PENDING
        assert len(q.options) == 4

    def test_recall_question_mirata_no_options(self):
        q = RecallQuestion(
            id="recall_000002",
            type=RecallQuestionType.MIRATA,
            unit_ids=["2.1"],
            question_text="Descrivi il meccanismo X.",
        )
        assert q.options is None
        assert q.correct_index is None
        assert q.pregenerated_material is None

    def test_recall_question_vasta_multiple_units(self):
        q = RecallQuestion(
            id="recall_000003",
            type=RecallQuestionType.VASTA,
            unit_ids=["1.1", "1.2", "2.1"],
            question_text="Descrivi il processo Y.",
            pregenerated_material="1) Punto A; 2) Punto B",
        )
        assert len(q.unit_ids) == 3

    def test_recall_answer_basic(self):
        a = RecallAnswer(question_id="recall_000001", answer_text="Risposta.", is_voice=True)
        assert a.vote is None
        assert a.evaluation is None

    def test_recall_bank_empty(self):
        bank = RecallBank()
        assert bank.schema_version == "1.0"
        assert bank.questions == []
        assert bank.answers == []

    def test_recall_question_requires_unit_ids(self):
        with pytest.raises(Exception):
            RecallQuestion(id="x", type=RecallQuestionType.MIRATA, unit_ids=[], question_text="?")


# -----------------------------------------------------------------------
# 2. Persistenza (round-trip + scrittura atomica)
# -----------------------------------------------------------------------

class TestPersistence:
    def test_round_trip(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.QUIZ, "1.1"))
        bank.answers.append(RecallAnswer(question_id="recall_000001", answer_text="R"))
        save_recall_bank(bank, lesson_dir)

        loaded = load_recall_bank(lesson_dir)
        assert len(loaded.questions) == 1
        assert loaded.questions[0].id == "recall_000001"
        assert len(loaded.answers) == 1
        assert loaded.answers[0].answer_text == "R"

    def test_atomic_write_no_tmp_residue(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1"))
        save_recall_bank(bank, lesson_dir)

        bank_path = get_recall_bank_path(lesson_dir)
        tmp_path = bank_path + ".tmp"
        assert os.path.isfile(bank_path)
        assert not os.path.isfile(tmp_path), ".tmp residuo trovato dopo salvataggio riuscito"

    def test_load_missing_file_returns_empty(self, tmp_path):
        empty_dir = str(tmp_path / "empty")
        os.makedirs(empty_dir)
        bank = load_recall_bank(empty_dir)
        assert bank.questions == []
        assert bank.answers == []


# -----------------------------------------------------------------------
# 3. get_reserve_count
# -----------------------------------------------------------------------

class TestReserveCount:
    def test_counts_only_pending_of_given_type(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.QUIZ, "1.1", RecallQuestionStatus.PENDING))
        bank.questions.append(_make_question("recall_000002", RecallQuestionType.QUIZ, "1.2", RecallQuestionStatus.ASKED))
        bank.questions.append(_make_question("recall_000003", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.PENDING))
        bank.questions.append(_make_question("recall_000004", RecallQuestionType.VASTA, "1.1", RecallQuestionStatus.PENDING))
        save_recall_bank(bank, lesson_dir)

        assert get_reserve_count(lesson_dir, RecallQuestionType.QUIZ) == 1
        assert get_reserve_count(lesson_dir, RecallQuestionType.MIRATA) == 1
        assert get_reserve_count(lesson_dir, RecallQuestionType.VASTA) == 1

    def test_zero_if_no_pending(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.QUIZ, "1.1", RecallQuestionStatus.ANSWERED))
        save_recall_bank(bank, lesson_dir)
        assert get_reserve_count(lesson_dir, RecallQuestionType.QUIZ) == 0


# -----------------------------------------------------------------------
# 4. get_next_pending_question (3 modalità + marcatura ASKED)
# -----------------------------------------------------------------------

class TestGetNextPending:
    def _setup_bank(self, lesson_dir) -> None:
        """Crea 6 domande mirata: 2 per ciascuna di 3 unità (1.1, 2.1, 3.1)."""
        bank = RecallBank()
        for unit in ["1.1", "2.1", "3.1"]:
            for i in range(2):
                qid = f"recall_{len(bank.questions)+1:06d}"
                bank.questions.append(
                    RecallQuestion(
                        id=qid,
                        type=RecallQuestionType.MIRATA,
                        unit_ids=[unit],
                        question_text=f"Domanda {qid} per {unit}?",
                        # created_at ordering: earlier for i=0
                        created_at=f"2026-01-01T{10+i}:00:00",
                    )
                )
        save_recall_bank(bank, lesson_dir)

    def test_sequenziale_respects_unit_then_time_order(self, lesson_dir):
        self._setup_bank(lesson_dir)
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="sequenziale")
        assert q is not None
        assert q.unit_ids[0] == "1.1"

    def test_alternato_alternates_between_units(self, lesson_dir):
        self._setup_bank(lesson_dir)
        q1 = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="alternato", unit_cursor=None)
        q2 = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="alternato", unit_cursor=q1.unit_ids[0])
        assert q1 is not None and q2 is not None
        assert q1.unit_ids[0] != q2.unit_ids[0], "alternato dovrebbe cambiare unità"

    def test_casuale_returns_valid_question(self, lesson_dir):
        self._setup_bank(lesson_dir)
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="casuale")
        assert q is not None
        assert q.status == RecallQuestionStatus.ASKED  # già aggiornata prima di restituire

    def test_marks_question_as_asked(self, lesson_dir):
        self._setup_bank(lesson_dir)
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="sequenziale")
        assert q is not None
        # Ricarica il bank e verifica
        bank = load_recall_bank(lesson_dir)
        stored = next(sq for sq in bank.questions if sq.id == q.id)
        assert stored.status == RecallQuestionStatus.ASKED

    def test_returns_none_if_no_pending(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.ANSWERED))
        save_recall_bank(bank, lesson_dir)
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA)
        assert q is None

    def test_exclude_id_skips_it_when_alternatives_exist(self, lesson_dir):
        self._setup_bank(lesson_dir)
        bank = load_recall_bank(lesson_dir)
        first_id = sorted(bank.questions, key=lambda q: (q.unit_ids[0], q.created_at))[0].id
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, order="sequenziale", exclude_id=first_id)
        assert q is not None
        assert q.id != first_id

    def test_exclude_id_falls_back_when_it_is_the_only_pending(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1"))
        save_recall_bank(bank, lesson_dir)
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA, exclude_id="recall_000001")
        assert q is not None
        assert q.id == "recall_000001"  # nessun'altra alternativa: va restituita comunque


# -----------------------------------------------------------------------
# 4b. skip_recall_question
# -----------------------------------------------------------------------

class TestSkipRecallQuestion:
    def test_reverts_asked_to_pending(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.ASKED))
        save_recall_bank(bank, lesson_dir)
        skip_recall_question(lesson_dir, "recall_000001")
        bank2 = load_recall_bank(lesson_dir)
        assert bank2.questions[0].status == RecallQuestionStatus.PENDING

    def test_is_noop_on_answered_question(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.ANSWERED))
        save_recall_bank(bank, lesson_dir)
        skip_recall_question(lesson_dir, "recall_000001")
        bank2 = load_recall_bank(lesson_dir)
        assert bank2.questions[0].status == RecallQuestionStatus.ANSWERED

    def test_is_noop_on_unknown_question(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.ASKED))
        save_recall_bank(bank, lesson_dir)
        skip_recall_question(lesson_dir, "recall_nonexistent")  # non deve sollevare eccezioni
        bank2 = load_recall_bank(lesson_dir)
        assert bank2.questions[0].status == RecallQuestionStatus.ASKED

    def test_skipped_question_is_reachable_again(self, lesson_dir):
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1", RecallQuestionStatus.ASKED))
        save_recall_bank(bank, lesson_dir)
        assert get_reserve_count(lesson_dir, RecallQuestionType.MIRATA) == 0
        skip_recall_question(lesson_dir, "recall_000001")
        assert get_reserve_count(lesson_dir, RecallQuestionType.MIRATA) == 1
        q = get_next_pending_question(lesson_dir, RecallQuestionType.MIRATA)
        assert q is not None and q.id == "recall_000001"


# -----------------------------------------------------------------------
# 5. record_recall_answer / record_recall_vote
# -----------------------------------------------------------------------

class TestAnswerAndVote:
    def _setup_question(self, lesson_dir, qid="recall_000001"):
        bank = RecallBank()
        bank.questions.append(_make_question(qid, RecallQuestionType.MIRATA, "1.1"))
        save_recall_bank(bank, lesson_dir)

    def test_record_answer_marks_answered(self, lesson_dir):
        self._setup_question(lesson_dir)
        ans = record_recall_answer(lesson_dir, "recall_000001", "Risposta completa.", is_voice=False)
        assert ans.answer_text == "Risposta completa."
        bank = load_recall_bank(lesson_dir)
        q = next(q for q in bank.questions if q.id == "recall_000001")
        assert q.status == RecallQuestionStatus.ANSWERED

    def test_record_answer_updates_existing(self, lesson_dir):
        self._setup_question(lesson_dir)
        record_recall_answer(lesson_dir, "recall_000001", "Prima risposta.")
        record_recall_answer(lesson_dir, "recall_000001", "Risposta aggiornata.", evaluation="buona")
        bank = load_recall_bank(lesson_dir)
        answers = [a for a in bank.answers if a.question_id == "recall_000001"]
        assert len(answers) == 1
        assert answers[0].answer_text == "Risposta aggiornata."
        assert answers[0].evaluation == "buona"

    def test_record_vote_on_existing_answer(self, lesson_dir):
        self._setup_question(lesson_dir)
        record_recall_answer(lesson_dir, "recall_000001", "Risposta.")
        record_recall_vote(lesson_dir, "recall_000001", "up")
        bank = load_recall_bank(lesson_dir)
        a = next(a for a in bank.answers if a.question_id == "recall_000001")
        assert a.vote == "up"

    def test_record_vote_creates_partial_answer_if_none(self, lesson_dir):
        """record_recall_vote su domanda senza risposta crea una RecallAnswer parziale."""
        self._setup_question(lesson_dir)
        record_recall_vote(lesson_dir, "recall_000001", "lightning")
        bank = load_recall_bank(lesson_dir)
        answers = [a for a in bank.answers if a.question_id == "recall_000001"]
        assert len(answers) == 1
        assert answers[0].vote == "lightning"
        assert answers[0].answer_text == ""
        assert answers[0].is_voice is False

    def test_record_answer_with_voice(self, lesson_dir):
        self._setup_question(lesson_dir)
        ans = record_recall_answer(lesson_dir, "recall_000001", "Risposta vocale.", is_voice=True, vote="up")
        assert ans.is_voice is True
        assert ans.vote == "up"


# -----------------------------------------------------------------------
# 6. Few-shot pool
# -----------------------------------------------------------------------

class TestFewShot:
    def test_fifo_max_5_per_type(self, fewshot_dir):
        for i in range(7):
            record_fewshot_vote(RecallQuestionType.QUIZ, f"Domanda quiz {i}", "up", state_dir=fewshot_dir)
        examples = load_fewshot_examples(RecallQuestionType.QUIZ, state_dir=fewshot_dir)
        assert len(examples) == 5
        # Inserendo 7 voci (0-6), le ultime 5 mantenute sono 2,3,4,5,6 (FIFO: 0 e 1 escono)
        texts = [e["question_text"] for e in examples]
        assert "Domanda quiz 0" not in texts  # esce (la più vecchia)
        assert "Domanda quiz 1" not in texts  # esce
        assert "Domanda quiz 6" in texts      # rimane (la più recente)

    def test_types_are_completely_separate(self, fewshot_dir):
        record_fewshot_vote(RecallQuestionType.QUIZ, "Quiz question", "up", state_dir=fewshot_dir)
        record_fewshot_vote(RecallQuestionType.MIRATA, "Mirata question", "down", state_dir=fewshot_dir)
        record_fewshot_vote(RecallQuestionType.VASTA, "Vasta question", "lightning", state_dir=fewshot_dir)

        quiz_ex = load_fewshot_examples(RecallQuestionType.QUIZ, state_dir=fewshot_dir)
        mirata_ex = load_fewshot_examples(RecallQuestionType.MIRATA, state_dir=fewshot_dir)
        vasta_ex = load_fewshot_examples(RecallQuestionType.VASTA, state_dir=fewshot_dir)

        assert len(quiz_ex) == 1 and quiz_ex[0]["question_text"] == "Quiz question"
        assert len(mirata_ex) == 1 and mirata_ex[0]["question_text"] == "Mirata question"
        assert len(vasta_ex) == 1 and vasta_ex[0]["question_text"] == "Vasta question"

        # Verifica separazione: nessun esempio di un tipo appare in un altro
        quiz_texts = {e["question_text"] for e in quiz_ex}
        mirata_texts = {e["question_text"] for e in mirata_ex}
        vasta_texts = {e["question_text"] for e in vasta_ex}
        assert quiz_texts.isdisjoint(mirata_texts)
        assert quiz_texts.isdisjoint(vasta_texts)
        assert mirata_texts.isdisjoint(vasta_texts)

    def test_empty_on_unseen_type(self, fewshot_dir):
        result = load_fewshot_examples(RecallQuestionType.VASTA, state_dir=fewshot_dir)
        assert result == []

    def test_vote_fields_stored_correctly(self, fewshot_dir):
        record_fewshot_vote(RecallQuestionType.MIRATA, "Domanda X", "down", state_dir=fewshot_dir)
        examples = load_fewshot_examples(RecallQuestionType.MIRATA, state_dir=fewshot_dir)
        assert examples[0]["vote"] == "down"
        assert "voted_at" in examples[0]


# -----------------------------------------------------------------------
# 7. generate_recall_batch (force_mock=True)
# -----------------------------------------------------------------------

class TestGenerateBatch:
    def test_quiz_mock_produces_count_questions(self, lesson_dir):
        qs = generate_recall_batch(
            lesson_dir, RecallQuestionType.QUIZ, count=3, few_shot_examples=[], force_mock=True
        )
        assert len(qs) == 3
        for q in qs:
            assert q.type == RecallQuestionType.QUIZ
            assert q.options is not None and len(q.options) == 4
            assert q.correct_index is not None
            assert q.pregenerated_material is not None
            assert len(q.unit_ids) == 1
            assert q.id.startswith("recall_")

    def test_mirata_mock_produces_count_questions(self, lesson_dir):
        qs = generate_recall_batch(
            lesson_dir, RecallQuestionType.MIRATA, count=4, few_shot_examples=[], force_mock=True
        )
        assert len(qs) == 4
        for q in qs:
            assert q.type == RecallQuestionType.MIRATA
            assert q.options is None
            assert q.correct_index is None
            assert q.pregenerated_material is None
            assert len(q.unit_ids) == 1

    def test_vasta_mock_produces_groups(self, lesson_dir):
        qs = generate_recall_batch(
            lesson_dir, RecallQuestionType.VASTA, count=2, few_shot_examples=[], force_mock=True
        )
        assert len(qs) >= 1  # count capped by available unit groups
        for q in qs:
            assert q.type == RecallQuestionType.VASTA
            assert 2 <= len(q.unit_ids) <= 4
            assert q.pregenerated_material is not None
            assert q.options is None

    def test_batch_appends_not_overwrites(self, lesson_dir):
        """Chiamate successive aggiungono al bank senza cancellare quelle precedenti."""
        generate_recall_batch(lesson_dir, RecallQuestionType.QUIZ, count=2, few_shot_examples=[], force_mock=True)
        generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=2, few_shot_examples=[], force_mock=True)
        bank = load_recall_bank(lesson_dir)
        quiz_qs = [q for q in bank.questions if q.type == RecallQuestionType.QUIZ]
        mirata_qs = [q for q in bank.questions if q.type == RecallQuestionType.MIRATA]
        assert len(quiz_qs) == 2
        assert len(mirata_qs) == 2

    def test_sequential_ids(self, lesson_dir):
        """Gli ID recall_NNNNNN sono sequenziali e non si sovrappongono tra chiamate."""
        q1 = generate_recall_batch(lesson_dir, RecallQuestionType.QUIZ, count=2, few_shot_examples=[], force_mock=True)
        q2 = generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=2, few_shot_examples=[], force_mock=True)
        all_ids = [q.id for q in q1 + q2]
        assert len(all_ids) == len(set(all_ids)), "ID duplicati rilevati"

    def test_count_exceeds_units(self, lesson_dir):
        """Se count > numero unità disponibili per quiz/mirata, non solleva errori."""
        qs = generate_recall_batch(
            lesson_dir, RecallQuestionType.QUIZ, count=20, few_shot_examples=[], force_mock=True
        )
        assert len(qs) == 20  # deve funzionare riutilizzando le unità

    def test_all_questions_pending_after_generation(self, lesson_dir):
        qs = generate_recall_batch(lesson_dir, RecallQuestionType.QUIZ, count=3, few_shot_examples=[], force_mock=True)
        for q in qs:
            assert q.status == RecallQuestionStatus.PENDING


class TestGenerateBatchDistribution:
    """Bug reale trovato in verifica: prima del fix, _pick_unit_groups ripartiva sempre da
    idx=0 (quiz/mirata) o i=0 (vasta) ad ogni chiamata, indipendentemente da quante domande
    esistessero già — sia il batch iniziale sia ogni rifornimento finivano sempre sulle prime
    N unità del draft, non toccando mai le altre. Il fix sceglie le unità meno rappresentate
    nel bank esistente per quel tipo."""

    def test_repeated_calls_spread_across_units_instead_of_restarting(self, lesson_dir):
        """Con reserve_targets piccoli rispetto alle 6 unità della fixture, due chiamate
        consecutive senza risposte nel mezzo devono coprire unità diverse tra loro."""
        first = generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=2, few_shot_examples=[], force_mock=True)
        second = generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=2, few_shot_examples=[], force_mock=True)
        first_units = {q.unit_ids[0] for q in first}
        second_units = {q.unit_ids[0] for q in second}
        assert first_units.isdisjoint(second_units), (
            f"le unità si ripetono tra le due generazioni: {first_units} vs {second_units}"
        )

    def test_prefers_units_with_no_existing_questions(self, lesson_dir):
        """Con 2 unità già coperte da domande mirata esistenti, un nuovo batch di 2 deve
        preferire le 2 unità scoperte invece di generare ancora su quelle già coperte."""
        bank = RecallBank()
        bank.questions.append(_make_question("recall_000001", RecallQuestionType.MIRATA, "1.1"))
        bank.questions.append(_make_question("recall_000002", RecallQuestionType.MIRATA, "2.1"))
        save_recall_bank(bank, lesson_dir)

        qs = generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=2, few_shot_examples=[], force_mock=True)
        new_units = {q.unit_ids[0] for q in qs}
        assert new_units.isdisjoint({"1.1", "2.1"})

    def test_vasta_windows_prefer_less_covered_units(self, lesson_dir):
        """Una seconda finestra vasta non deve ripartire dalle stesse unità già coperte
        dalla prima se altre unità del draft sono ancora scoperte."""
        first = generate_recall_batch(lesson_dir, RecallQuestionType.VASTA, count=1, few_shot_examples=[], force_mock=True)
        second = generate_recall_batch(lesson_dir, RecallQuestionType.VASTA, count=1, few_shot_examples=[], force_mock=True)
        assert set(first[0].unit_ids).isdisjoint(set(second[0].unit_ids))


# -----------------------------------------------------------------------
# 8. Il recall usa il draft con le decisioni del ledger già applicate
# -----------------------------------------------------------------------

class TestRecallUsesResolvedDraft:
    """Bug reale riscontrato: generate_recall_batch/evaluate_recall_answer leggevano il
    draft grezzo (load_draft), ignorando le correzioni scientifiche/ASR già approvate
    dall'utente. L'utente veniva interrogato/valutato su un testo diverso da quello che
    aveva davvero studiato nel documento finale. Devono usare load_resolved_draft()."""

    def _accept_science_decision_on_unit_1(self, lesson_dir):
        from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
        from rt.pipeline.review_science import get_science_issues_path
        from rt.pipeline.ledger import record_decision

        sci_issue = ScienceIssue(
            id="sci_000001",
            type=ScienceType.ERR_DOCENTE,
            severity=ScienceSeverity.LOW,
            unit_id="1.1",
            segment_id="seg_000001",
            claim="Contenuto accademico dell'unita' 1.",
            reason="Dettaglio mancante confermato dal docente.",
            suggested_fix="Contenuto accademico RIVISTO E APPROVATO dell'unita' 1.",
        )
        with open(get_science_issues_path(lesson_dir), "w", encoding="utf-8") as f:
            json.dump([sci_issue.model_dump(mode="json")], f)
        record_decision(
            lesson_dir=lesson_dir, issue_id="sci_000001", decision="accepted",
            resolved_text=sci_issue.suggested_fix,
        )

    def test_generate_recall_batch_prompt_uses_resolved_content(self, lesson_dir):
        self._accept_science_decision_on_unit_1(lesson_dir)
        captured = {}

        def fake_call_structured(self, prompt, system_prompt, response_model, **kwargs):
            captured["prompt"] = prompt
            return response_model(
                id="placeholder", type=RecallQuestionType.MIRATA, unit_ids=["1.1"],
                question_text="Domanda di prova?",
            )

        from unittest.mock import patch
        with patch("rt.llm.client.LLMClient.call_structured", fake_call_structured):
            generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, count=1, few_shot_examples=[], force_mock=False)

        assert "RIVISTO E APPROVATO" in captured["prompt"]

    def test_evaluate_recall_answer_prompt_uses_resolved_content(self, lesson_dir):
        self._accept_science_decision_on_unit_1(lesson_dir)
        bank = RecallBank(questions=[
            RecallQuestion(id="recall_000001", type=RecallQuestionType.MIRATA, unit_ids=["1.1"], question_text="Domanda?")
        ])
        save_recall_bank(bank, lesson_dir)

        captured = {}

        def fake_call_structured(self, prompt, system_prompt, response_model, **kwargs):
            captured["prompt"] = prompt
            return response_model(correttezza=80, completezza=70, commento="ok")

        from unittest.mock import patch
        from rt.pipeline.recall import evaluate_recall_answer
        with patch("rt.llm.client.LLMClient.call_structured", fake_call_structured):
            evaluate_recall_answer(lesson_dir, "recall_000001", "risposta studente", force_mock=False)

        assert "RIVISTO E APPROVATO" in captured["prompt"]
