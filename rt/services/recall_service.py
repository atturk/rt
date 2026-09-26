"""
rt.services.recall_service
Logica di una sessione di Active Recall indipendente dal canale: stato di sessione per
lezione, batch iniziale, scelta della prossima domanda con rifornimento, valutazione delle
risposte, domande stale. Le interfacce sono rt.telegram.recall_channel (Telegram) e
rt.tui.recall (terminale). Il motore delle domande resta rt.pipeline.recall.
"""
import json
import os
from typing import Any, List, Optional

from rt.core.lesson_paths import lesson_path
from rt.core.models import RecallQuestionStatus, RecallQuestionType
from rt.storage import fs


def format_unit_reference(lesson_dir: str, question) -> str:
    """Blocco testuale (testo semplice, no HTML: i messaggi del daemon non impostano
    parse_mode) con il contenuto completo di tutte le unità didattiche della domanda.
    Mostra sempre il contenuto intero di ogni unità in question.unit_ids, separandole
    con un'intestazione per unità (es. per vasta che può averne più).
    Usata dal bottone 📖 (richiesta esplicita), non più incollata automaticamente agli esiti."""
    from rt.pipeline.ledger import load_resolved_draft
    try:
        draft = load_resolved_draft(lesson_dir)
    except Exception:
        return ""
    units = [u for u in draft.units if u.unit_id in question.unit_ids]
    if not units:
        return ""
    parts = []
    for u in units:
        parts.append(f"\n\n📚 Unità {u.unit_id} - {u.title}:\n{u.content}")
    return "".join(parts)


def get_recall_session_state_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "telegram_recall_session.json")


def load_recall_session_state(lesson_dir: str) -> dict:
    path = get_recall_session_state_path(lesson_dir)
    if not fs.isfile(path):
        return {"order": "alternato", "unit_cursor": None, "current_question_id": None, "force_mock": False}
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = {
            "order": data.get("order", "alternato"),
            "unit_cursor": data.get("unit_cursor"),
            "current_question_id": data.get("current_question_id"),
            "force_mock": data.get("force_mock", False),
        }
        if "current_question_message_id" in data:
            res["current_question_message_id"] = data["current_question_message_id"]
        if "current_post_answer_short_id" in data:
            res["current_post_answer_short_id"] = data["current_post_answer_short_id"]
        if "current_post_answer_message_id" in data:
            res["current_post_answer_message_id"] = data["current_post_answer_message_id"]
        return res
    except Exception:
        return {"order": "alternato", "unit_cursor": None, "current_question_id": None, "force_mock": False}


def save_recall_session_state(lesson_dir: str, state: dict) -> None:
    path = get_recall_session_state_path(lesson_dir)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)


def ensure_initial_batch(lesson_dir: str, force_mock: bool = False) -> None:
    from rt.core.config import load_config
    from rt.pipeline.recall import load_recall_bank, generate_recall_batch, load_fewshot_examples

    bank = load_recall_bank(lesson_dir)
    if bank.questions:
        return

    cfg = load_config()
    state_dir = cfg.telegram.state_dir
    for qtype_str, count in cfg.telegram.recall.reserve_targets.items():
        qtype = RecallQuestionType(qtype_str)
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, count, examples, force_mock=force_mock)


def handle_recall_answer(lesson_dir: str, question_id: str, answer_text: str, is_voice: bool = False, force_mock: Optional[bool] = None) -> Optional[str]:
    """Salva la risposta a una domanda mirata/vasta e la valuta con l'LLM.
    Ritorna il testo di valutazione, o None se la domanda non esiste o è un quiz
    (i quiz si rispondono con un bottone, gestiti a parte).

    force_mock=None (default) risolve dal flag persistito in telegram_recall_session.json:
    la sessione è stata avviata via terminale/CLI con --mock, e il daemon (processo separato,
    invocato più tardi per i rifornimenti/risposte) deve rispettarlo senza doverlo ripassare
    esplicitamente ad ogni chiamata."""
    from rt.pipeline.recall import load_recall_bank, record_recall_answer, evaluate_recall_answer

    bank = load_recall_bank(lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None or question.type == RecallQuestionType.QUIZ:
        return None

    if force_mock is None:
        force_mock = load_recall_session_state(lesson_dir).get("force_mock", False)

    evaluation = evaluate_recall_answer(lesson_dir, question_id, answer_text, force_mock=force_mock)
    record_recall_answer(lesson_dir, question_id, answer_text, is_voice=is_voice, evaluation=evaluation)
    return evaluation


def next_question(
    lesson_dir: str,
    qtype: RecallQuestionType,
    order: str,
    unit_cursor: Optional[str],
    exclude_id: Optional[str],
    refill_batch_size: int,
    state_dir: Optional[str],
    force_mock: bool = False,
):
    """Prossima domanda pendente del tipo richiesto; se la riserva è vuota ne genera un
    nuovo batch e riprova. None se non c'è nulla da proporre."""
    from rt.pipeline.recall import generate_recall_batch, get_next_pending_question, load_fewshot_examples

    question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
    if question is None:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, refill_batch_size, examples, force_mock=force_mock)
        question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
    return question


def refill_if_low(
    lesson_dir: str,
    qtype: RecallQuestionType,
    threshold: int,
    batch_size: int,
    state_dir: Optional[str],
    force_mock: bool = False,
) -> None:
    """Rifornisce la riserva del tipo attivo quando scende sotto soglia."""
    from rt.pipeline.recall import generate_recall_batch, get_reserve_count, load_fewshot_examples

    if get_reserve_count(lesson_dir, qtype) < threshold:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, batch_size, examples, force_mock=force_mock)


def refill_active_type_if_low(lesson_dir: str, qtype: RecallQuestionType, force_mock: bool = False) -> None:
    """refill_if_low con soglia e batch della configurazione (come dopo ogni risposta del
    recall da terminale)."""
    from rt.core.config import load_config
    cfg = load_config()
    refill_if_low(lesson_dir, qtype, cfg.telegram.recall.refill_threshold,
                  cfg.telegram.recall.refill_batch_size, cfg.telegram.state_dir, force_mock=force_mock)


def needs_refill(lesson_dir: str, qtype: RecallQuestionType) -> bool:
    from rt.core.config import load_config
    from rt.pipeline.recall import get_reserve_count
    return get_reserve_count(lesson_dir, qtype) < load_config().telegram.recall.refill_threshold


def is_question_stale(lesson_dir: str, question) -> bool:
    """La domanda è stata generata da un contenuto di unità poi modificato."""
    from rt.pipeline.recall import _compute_units_fingerprint
    if question.content_fingerprint is None:
        return False
    current_fp = _compute_units_fingerprint(lesson_dir, question.unit_ids)
    return current_fp is not None and current_fp != question.content_fingerprint


def find_stale_questions(lesson_dir: str) -> List[Any]:
    from rt.pipeline.recall import load_recall_bank
    return [q for q in load_recall_bank(lesson_dir).questions if is_question_stale(lesson_dir, q)]


# ---------------------------------------------------------------------------
# Operazioni senza LLM per l'API (RT4-E3): la generazione e la valutazione delle risposte
# aperte passano da job (rt/services/api_jobs.py).
# ---------------------------------------------------------------------------

def question_view(question, reveal: bool = False) -> dict:
    """Domanda serializzabile; la risposta corretta del quiz solo dopo aver risposto."""
    data = {
        "id": question.id, "type": question.type.value, "unit_ids": list(question.unit_ids),
        "question_text": question.question_text, "options": question.options,
        "status": question.status.value,
    }
    if reveal:
        data["correct_index"] = question.correct_index
        data["explanation"] = question.pregenerated_material
    return data


def recall_overview(lesson_dir: str) -> dict:
    """Domande per tipo e stato, risposte date."""
    from rt.pipeline.recall import load_recall_bank
    bank = load_recall_bank(lesson_dir)
    counts: dict = {}
    for q in bank.questions:
        by_status = counts.setdefault(q.type.value, {})
        by_status[q.status.value] = by_status.get(q.status.value, 0) + 1
    return {"questions": counts, "answers": len([a for a in bank.answers if a.answer_text])}


def recall_history(lesson_dir: str) -> dict:
    """Tutte le domande (soluzione visibile solo per quelle già poste) e le risposte date,
    con valutazione e voto."""
    from rt.pipeline.recall import load_recall_bank
    bank = load_recall_bank(lesson_dir)
    questions = [question_view(q, reveal=q.status != RecallQuestionStatus.PENDING) for q in bank.questions]
    return {"questions": questions, "answers": [a.model_dump(mode="json") for a in bank.answers]}


def next_question_for(lesson_dir: str, qtype: RecallQuestionType, order: str = "alternato",
                      exclude_id: Optional[str] = None):
    """Prossima domanda pendente (la marca come posta) senza generarne di nuove; None se la
    riserva è vuota. Il cursore dell'ordine alternato è quello della sessione salvata."""
    from rt.pipeline.recall import get_next_pending_question
    state = load_recall_session_state(lesson_dir)
    question = get_next_pending_question(lesson_dir, qtype, order=order,
                                         unit_cursor=state.get("unit_cursor"), exclude_id=exclude_id)
    if question is not None:
        state.update({"order": order, "current_question_id": question.id,
                      "unit_cursor": question.unit_ids[0] if order == "alternato" else state.get("unit_cursor")})
        save_recall_session_state(lesson_dir, state)
    return question


def find_question(lesson_dir: str, question_id: str):
    from rt.pipeline.recall import load_recall_bank
    return next((q for q in load_recall_bank(lesson_dir).questions if q.id == question_id), None)


def answer_quiz(lesson_dir: str, question_id: str, choice: int) -> dict:
    """Risposta a un quiz, registrata come fa il recall da terminale."""
    from rt.pipeline.recall import record_recall_answer
    question = find_question(lesson_dir, question_id)
    if question is None or question.type != RecallQuestionType.QUIZ or not question.options:
        raise ValueError("Quiz inesistente.")
    if not 0 <= choice < len(question.options):
        raise ValueError("Opzione non valida.")
    record_recall_answer(lesson_dir, question.id, question.options[choice], is_voice=False,
                         evaluation=question.pregenerated_material)
    return {"question": question_view(find_question(lesson_dir, question_id), reveal=True),
            "correct": question.correct_index == choice}


def vote_question(lesson_dir: str, question_id: str, vote: str) -> None:
    """👍 / 👎 / ⚡ su una domanda: voto nella lezione e nei few-shot globali."""
    from rt.core.config import load_config
    from rt.pipeline.recall import record_fewshot_vote, record_recall_vote
    question = find_question(lesson_dir, question_id)
    if question is None:
        raise ValueError("Domanda inesistente.")
    record_recall_vote(lesson_dir, question_id, vote)
    state_dir = load_config().telegram.state_dir
    fs.makedirs(state_dir, exist_ok=True)
    record_fewshot_vote(question.type, question.question_text, vote, state_dir=state_dir)


def skip_question(lesson_dir: str, question_id: str) -> None:
    from rt.pipeline.recall import skip_recall_question
    skip_recall_question(lesson_dir, question_id)
