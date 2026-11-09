"""Test per Item 8 del Piano 4.3.8b3:
Valutazione delle risposte (mirate e vaste) con tre parametri (correttezza, completezza, attinenza)
e domanda di approfondimento (followup).
"""
import pytest
from unittest.mock import MagicMock, patch

from rt.core.models import (
    RecallBank, RecallQuestion, RecallQuestionStatus, RecallQuestionType, RecallAnswer
)
from rt.llm.prompts import (
    RecallEvalMirataResult, RecallEvalVastaResult,
    build_recall_eval_followup_user_prompt
)
from rt.pipeline.recall import (
    evaluate_recall_answer, record_recall_answer, skip_recall_followup,
    save_recall_bank, load_recall_bank
)
from rt.services.recall_service import handle_recall_answer, skip_recall_followup as service_skip


@pytest.fixture
def sample_lesson_dir(tmp_path):
    lesson_dir = tmp_path / "lezione_1"
    lesson_dir.mkdir()
    (lesson_dir / ".rt").mkdir()
    
    bank = RecallBank(
        questions=[
            RecallQuestion(
                id="q1",
                type=RecallQuestionType.MIRATA,
                unit_ids=["1.1"],
                question_text="Che cos'è l'acidosi metabolica?",
                status=RecallQuestionStatus.ASKED,
            ),
            RecallQuestion(
                id="q2",
                type=RecallQuestionType.VASTA,
                unit_ids=["1.1", "1.2"],
                question_text="Descrivi l'equilibrio acido-base e i meccanismi di compenso.",
                pregenerated_material="1. Definizione pH; 2. Sistemi tampone; 3. Compenso respiratorio; 4. Compenso renale.",
                status=RecallQuestionStatus.ASKED,
            )
        ]
    )
    save_recall_bank(bank, str(lesson_dir))
    return str(lesson_dir)


def test_parametri_salvati_e_mock_followup(sample_lesson_dir):
    """Verifica che tre parametri (correttezza, completezza, attinenza) e domanda_followup siano salvati."""
    eval_res = handle_recall_answer(
        sample_lesson_dir,
        "q1",
        "È un disturbo dell'equilibrio acido-base.",
        force_mock=True,
    )
    assert eval_res is not None
    assert eval_res.correttezza == 75
    assert eval_res.completezza == 70
    assert eval_res.attinenza == 80
    assert eval_res.domanda_followup is not None
    assert eval_res.outcome == "parziale"

    bank = load_recall_bank(sample_lesson_dir)
    ans = next(a for a in bank.answers if a.question_id == "q1")
    assert ans.correttezza == 75
    assert ans.completezza == 70
    assert ans.attinenza == 80
    assert ans.domanda_followup == eval_res.domanda_followup
    assert ans.outcome == "parziale"
    
    # La domanda non è ancora ANSWERED perché c'è un followup pendente
    q1 = next(q for q in bank.questions if q.id == "q1")
    assert q1.status == RecallQuestionStatus.ASKED


def test_followup_non_proposto_su_non_lo_so_o_sbagliata(sample_lesson_dir):
    """Verifica che la domanda di approfondimento non venga mai proposta se la risposta è [Non lo so]."""
    eval_res = handle_recall_answer(
        sample_lesson_dir,
        "q1",
        "[Non lo so]",
        force_mock=True,
    )
    assert eval_res is not None
    assert eval_res.correttezza == 0
    assert eval_res.completezza == 0
    assert eval_res.attinenza == 0
    assert eval_res.domanda_followup is None
    assert eval_res.outcome == "sbagliata"

    bank = load_recall_bank(sample_lesson_dir)
    ans = next(a for a in bank.answers if a.question_id == "q1")
    assert ans.domanda_followup is None
    assert ans.outcome == "sbagliata"


def test_contesto_della_valutazione_2_contiene_domanda_e_risposta_1():
    """Verifica che il prompt della seconda valutazione contenga domanda, risposta 1, eval 1, followup q, e risposta 2."""
    prompt = build_recall_eval_followup_user_prompt(
        question_text="Che cos'è l'acidosi?",
        reference_text="Unità di fisiologia",
        answer_1="È una riduzione del pH ematico.",
        eval_1_comment="Corretto ma incompleto sui meccanismi.",
        eval_1_scores="Correttezza: 80%, Completezza: 60%, Attinenza: 90%",
        followup_question="Quali sono le cause metaboliche principali?",
        answer_2="Accumulo di acidi o perdita di bicarbonato.",
        dont_know=False,
    )

    assert "DOMANDA ORIGINALE:\nChe cos'è l'acidosi?" in prompt
    assert "PRIMA RISPOSTA DELLO STUDENTE:\nÈ una riduzione del pH ematico." in prompt
    assert "Correttezza: 80%, Completezza: 60%, Attinenza: 90%" in prompt
    assert "Corretto ma incompleto sui meccanismi." in prompt
    assert "DOMANDA DI APPROFONDIMENTO DEL DOCENTE:\nQuali sono le cause metaboliche principali?" in prompt
    assert "SECONDA RISPOSTA DELLO STUDENTE (APPROFONDIMENTO):\nAccumulo di acidi o perdita di bicarbonato." in prompt


def test_flusso_completo_esito_finale_e_valutazione_2(sample_lesson_dir):
    """Verifica il flusso: risposta 1 -> followup proposto -> risposta 2 -> esito finale della valutazione 2."""
    # Step 1: prima risposta
    eval1 = handle_recall_answer(
        sample_lesson_dir,
        "q2",
        "L'equilibrio acido-base regola il pH con tamponi e compenso respiratorio.",
        force_mock=True,
    )
    assert eval1.domanda_followup is not None
    assert eval1.outcome == "parziale"

    # Step 2: risposta di approfondimento (is_followup=True)
    eval2 = handle_recall_answer(
        sample_lesson_dir,
        "q2",
        "Il compenso renale interviene riassorbendo o eliminando bicarbonati a lungo termine.",
        force_mock=True,
        is_followup=True,
    )
    assert eval2 is not None
    assert eval2.outcome == "corretta"
    assert eval2.correttezza == 95
    assert eval2.completezza == 90
    assert eval2.attinenza == 90
    assert eval2.domanda_followup is None

    # Verifica stato salvato nella RecallAnswer
    bank = load_recall_bank(sample_lesson_dir)
    ans = next(a for a in bank.answers if a.question_id == "q2")
    assert ans.outcome == "corretta"  # vale l'esito della 2!
    assert ans.followup_question is not None
    assert ans.followup_answer == "Il compenso renale interviene riassorbendo o eliminando bicarbonati a lungo termine."
    assert ans.followup_correttezza == 95
    assert ans.followup_completezza == 90
    assert ans.followup_attinenza == 90
    assert ans.domanda_followup is None

    # Domanda ora marcata come ANSWERED
    q2 = next(q for q in bank.questions if q.id == "q2")
    assert q2.status == RecallQuestionStatus.ANSWERED


def test_salta_approfondimento(sample_lesson_dir):
    """Verifica che saltando l'approfondimento rimanga l'esito della prima valutazione e la domanda sia chiusa."""
    eval1 = handle_recall_answer(
        sample_lesson_dir,
        "q1",
        "È un disturbo dell'equilibrio acido-base.",
        force_mock=True,
    )
    assert eval1.domanda_followup is not None

    # Utente salta il followup
    service_skip(sample_lesson_dir, "q1")

    bank = load_recall_bank(sample_lesson_dir)
    ans = next(a for a in bank.answers if a.question_id == "q1")
    assert ans.outcome == "parziale"  # resta l'esito della 1
    assert ans.domanda_followup is None  # rimosso il followup pendente
    assert ans.followup_answer is None

    q1 = next(q for q in bank.questions if q.id == "q1")
    assert q1.status == RecallQuestionStatus.ANSWERED
