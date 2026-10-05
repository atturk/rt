"""Modifiche a mano alle domande del pool (4.2.2b3): testo, alternative, commento dell'IA,
stato posta/da porre e ripescaggio delle domande già poste.

Una domanda modificata torna sempre fra quelle da porre: la vecchia risposta resta nello
storico, ma la domanda si rifà. Il commento dell'IA (`pregenerated_material`) esiste solo dove
il modello lo prevede: quiz, vaste ed esercizi.
"""
from typing import List, Optional

from rt.core.models import (GeneratedRecallQuestion, RecallQuestion, RecallQuestionStatus,
                            RecallQuestionType)
from pydantic import BaseModel, Field

from rt.services.errors import NotFound


class RegeneratedComment(BaseModel):
    """Contratto del modello quando riscrive solo il commento di una domanda."""
    testo: str = Field(min_length=1, description="Il commento riscritto, senza preamboli")


#: Tipi con il commento (o la scaletta, o lo schema) pregenerato dall'IA.
TYPES_WITH_COMMENT = (RecallQuestionType.QUIZ, RecallQuestionType.VASTA, RecallQuestionType.ESERCIZIO)

ASKED_STATES = (RecallQuestionStatus.ASKED, RecallQuestionStatus.ANSWERED)


def _find(bank, question_id: str) -> RecallQuestion:
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        raise NotFound("question_not_found", "Domanda inesistente.")
    return question


def edit_question(lesson_dir: str, question_id: str, *, question_text: str,
                  options: Optional[List[str]] = None, correct_index: Optional[int] = None,
                  explanation: Optional[str] = None) -> RecallQuestion:
    """Riscrive la domanda com'è stata corretta a mano e la rimette fra quelle da porre.

    Le regole sono quelle del modello (quiz: quattro opzioni distinte, un indice giusto e la
    spiegazione; mirate e casi senza materiale pregenerato): le riusa `GeneratedRecallQuestion`,
    così una modifica a mano non può produrre una domanda che l'IA non avrebbe potuto scrivere.
    """
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank

    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        question = _find(bank, question_id)
        candidate = {
            "type": question.type,
            "question_text": (question_text or "").strip(),
            "options": [o.strip() for o in options] if options is not None else None,
            "correct_index": correct_index,
            "pregenerated_material": (explanation or "").strip() or None,
        }
        if question.type != RecallQuestionType.QUIZ:
            candidate["options"] = None
            candidate["correct_index"] = None
        if question.type not in TYPES_WITH_COMMENT:
            candidate["pregenerated_material"] = None
        GeneratedRecallQuestion.model_validate(candidate)  # ValueError: la rifiuta il router
        duplicate = any(q.id != question.id and q.type == question.type
                        and q.question_text.strip().casefold() == candidate["question_text"].casefold()
                        for q in bank.questions)
        if duplicate:
            from rt.services.errors import Conflict
            raise Conflict("question_duplicate", "C'è già una domanda uguale nel pool.")
        question.question_text = candidate["question_text"]
        question.options = candidate["options"]
        question.correct_index = candidate["correct_index"]
        question.pregenerated_material = candidate["pregenerated_material"]
        # Modificata: si rifà da capo, qualunque fosse il suo stato (anche scartata).
        question.status = RecallQuestionStatus.PENDING
        question.discarded_from = None
        save_recall_bank(bank, lesson_dir)
        return question


def set_question_status(lesson_dir: str, question_id: str, status: str) -> RecallQuestion:
    """Segna una domanda come posta o da porre, senza toccare le risposte già date."""
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank

    wanted = RecallQuestionStatus(status)
    if wanted not in (RecallQuestionStatus.PENDING, RecallQuestionStatus.ASKED):
        raise ValueError("Si può segnare solo come 'pending' o 'asked'.")
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        question = _find(bank, question_id)
        if question.status != wanted:
            question.status = wanted
            question.discarded_from = None
            save_recall_bank(bank, lesson_dir)
        return question


def _last_outcome(bank, question_id: str) -> Optional[str]:
    answers = [a for a in bank.answers if a.question_id == question_id]
    return answers[-1].outcome if answers else None


def restore_questions(lesson_dir: str, scope: str) -> int:
    """Rimette fra quelle da porre le domande già poste ('asked') o solo quelle sbagliate
    ('wrong': esito sbagliata, quindi anche i 'Non lo so'). Le scartate restano fuori."""
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank

    if scope not in ("asked", "wrong"):
        raise ValueError("Ambito sconosciuto.")
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        restored = 0
        for question in bank.questions:
            if question.status not in ASKED_STATES:
                continue
            if scope == "wrong" and _last_outcome(bank, question.id) != "sbagliata":
                continue
            question.status = RecallQuestionStatus.PENDING
            restored += 1
        if restored:
            save_recall_bank(bank, lesson_dir)
        return restored


def restorable(lesson_dir: str) -> dict:
    """Quante domande potrebbe ripescare ciascun pulsante del pannello."""
    from rt.pipeline.recall import load_recall_bank

    bank = load_recall_bank(lesson_dir)
    asked = [q for q in bank.questions if q.status in ASKED_STATES]
    wrong = [q for q in asked if _last_outcome(bank, q.id) == "sbagliata"]
    return {"asked": len(asked), "wrong": len(wrong)}


def regenerate_comment(lesson_dir: str, question_id: str, *, force_mock: bool = False) -> RecallQuestion:
    """Riscrive solo il commento dell'IA, lasciando domanda e alternative come sono."""
    import json

    from rt.llm.client import LLMClient
    from rt.pipeline.ledger import load_resolved_draft
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank
    from rt.services.errors import Conflict
    from rt.services.prompt_settings import effective_system

    bank = load_recall_bank(lesson_dir)
    question = _find(bank, question_id)
    if question.type not in TYPES_WITH_COMMENT:
        raise Conflict("comment_not_supported", "Questo tipo di domanda non ha un commento dell'IA.")
    units = [u for u in load_resolved_draft(lesson_dir).units if u.unit_id in question.unit_ids]
    if not units:
        raise Conflict("unit_not_found", "Le unità della domanda non esistono più.")
    what = {RecallQuestionType.QUIZ: "la spiegazione della risposta giusta",
            RecallQuestionType.VASTA: "la scaletta della risposta ideale",
            RecallQuestionType.ESERCIZIO: "lo schema di risoluzione"}[question.type]
    system = (f"Riscrivi solo {what} di una domanda di ripasso, usando esclusivamente le unità fornite. "
              "Non cambiare la domanda né le alternative. Restituisci il JSON {\"testo\": ...}.")
    prompt = json.dumps({
        "domanda": question.model_dump(mode="json"),
        "unita": [{"id": u.unit_id, "titolo": u.title, "testo": u.content} for u in units],
    }, ensure_ascii=False)
    client = LLMClient(force_mock=force_mock)
    if client.force_mock:
        text = f"Commento rigenerato per {question.id}: la risposta si ricava dal testo dell'unità."
    else:
        result = client.call_structured(prompt=prompt, system_prompt=effective_system("recall", system),
                                        response_model=RegeneratedComment, job_name="recall",
                                        unit_id=", ".join(question.unit_ids), lesson_dir=lesson_dir)
        text = result.testo
    text = (text or "").strip()
    if not text:
        raise Conflict("comment_empty", "Il modello non ha restituito un commento.")
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        question = _find(bank, question_id)
        question.pregenerated_material = text
        save_recall_bank(bank, lesson_dir)
        return question
