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
        if "last_type" in data:
            res["last_type"] = data["last_type"]
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


def generate_pool(lesson_dir: str, force_mock: bool = False, qtypes=None, progress=None, unit_ids=None,
                  instructions=None, selection=None, count=None) -> dict:
    """Pool di domande dell'intera lezione: il recaller riceve tutte le unità selezionate
    (una chiamata per unità, per le vaste una per gruppo) e per ognuna genera zero, una o
    più domande nuove. Le domande già nel pool restano (il recaller le vede e non le ripete);
    quelle che non piacciono si eliminano con delete_questions. Restituisce quante domande
    nuove per tipo. unit_ids limita la generazione a quelle unità (anche se non selezionate)."""
    from rt.core.config import load_config
    from rt.pipeline.recall import generate_recall_batch, load_fewshot_examples

    types = [RecallQuestionType(t) for t in (qtypes or [t.value for t in RecallQuestionType])]
    state_dir = load_config().telegram.state_dir
    generated = {}
    for qtype in types:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generated[qtype.value] = len(generate_recall_batch(lesson_dir, qtype, count, examples,
                                                           force_mock=force_mock, regenerate=True, progress=progress,
                                                           unit_ids=unit_ids,
                                                           instructions=instructions, selection=selection))
    return generated


def delete_questions(lesson_dir: str, question_ids) -> int:
    """Elimina domande dal bank (con le loro risposte). Gli ID non tornano più in uso e le
    sessioni che le avevano poste restano leggibili. Restituisce quante ne ha eliminate."""
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank

    wanted = set(question_ids)
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        removed = [q for q in bank.questions if q.id in wanted]
        if not removed:
            return 0
        bank.last_question_number = max([bank.last_question_number] + [
            int(q.id.split("_")[1]) for q in bank.questions if q.id.startswith("recall_") and q.id.split("_")[1].isdigit()])
        gone = {q.id for q in removed}
        bank.questions = [q for q in bank.questions if q.id not in gone]
        bank.answers = [a for a in bank.answers if a.question_id not in gone]
        save_recall_bank(bank, lesson_dir)
    state = load_recall_session_state(lesson_dir)
    if state.get("current_question_id") in gone:
        state["current_question_id"] = None
        save_recall_session_state(lesson_dir, state)
    return len(removed)


def ensure_initial_batch(lesson_dir: str, force_mock: bool = False, *, regenerate: bool = False) -> None:
    """Genera il pool se la lezione non ha ancora domande (o se regenerate)."""
    from rt.pipeline.recall import load_recall_bank

    if load_recall_bank(lesson_dir).questions and not regenerate:
        return
    generate_pool(lesson_dir, force_mock=force_mock)


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
    """Prossima domanda pendente del tipo richiesto; se il pool del tipo è vuoto ne genera
    altre da unità selezionate a caso e riprova. None se non c'è nulla da proporre."""
    from rt.pipeline.recall import generate_recall_batch, get_next_pending_question, load_fewshot_examples

    question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
    if question is None:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, refill_batch_size, examples, force_mock=force_mock, shuffle=True)
        question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
    return question


# Casi ed esercizi: si riforniscono (con varianti dei tipi salvati) solo quando finiscono.
DEFAULT_REFILL_THRESHOLDS = {"vasta": 2, "mirata": 3, "quiz": 5, "caso": 0, "esercizio": 0}


def refill_threshold(qtype: RecallQuestionType) -> int:
    """Soglia del tipo: con questo numero di domande da porre, o meno, si rifornisce."""
    from rt.core.config import load_config
    thresholds = load_config().telegram.recall.refill_thresholds
    return int(thresholds.get(qtype.value, DEFAULT_REFILL_THRESHOLDS[qtype.value]))


def is_low(lesson_dir: str, qtype: RecallQuestionType) -> bool:
    from rt.pipeline.recall import get_pool_count
    return get_pool_count(lesson_dir, qtype) <= refill_threshold(qtype)


def refill_if_low(
    lesson_dir: str,
    qtype: RecallQuestionType,
    batch_size: int,
    state_dir: Optional[str],
    force_mock: bool = False,
    progress=None,
) -> None:
    """Quando le domande da porre del tipo scendono alla soglia (2 vaste, 3 mirate, 5 quiz
    di predefinito), il recaller ne genera altre da unità selezionate scelte a caso."""
    from rt.pipeline.recall import generate_recall_batch, load_fewshot_examples

    if is_low(lesson_dir, qtype):
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, batch_size, examples, force_mock=force_mock, shuffle=True,
                              progress=progress)


def refill_active_type_if_low(lesson_dir: str, qtype: RecallQuestionType, force_mock: bool = False,
                              progress=None) -> None:
    """refill_if_low con il batch della configurazione (come dopo ogni risposta del recall
    da terminale)."""
    from rt.core.config import load_config
    cfg = load_config()
    refill_if_low(lesson_dir, qtype, cfg.telegram.recall.refill_batch_size, cfg.telegram.state_dir,
                  force_mock=force_mock, progress=progress)


def needs_refill(lesson_dir: str, qtype: RecallQuestionType, *, force_mock: bool = False) -> bool:
    from rt.pipeline.recall import generation_available
    return is_low(lesson_dir, qtype) and generation_available(lesson_dir, qtype, force_mock=force_mock)


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
    from rt.services.recall_context import POLICY_VERSION
    return {"questions": counts, "answers": len([a for a in bank.answers if a.answer_text]),
            "legacy_pending": sum(q.status == RecallQuestionStatus.PENDING and q.generation_version != POLICY_VERSION for q in bank.questions),
            "evaluated_empty": sum(row.get("outcome") == "empty" for row in bank.generation_attempts.values()),
            "refill_thresholds": {t.value: refill_threshold(t) for t in RecallQuestionType}}


def recall_history(lesson_dir: str) -> dict:
    """Tutte le domande (soluzione visibile solo per quelle già poste) e le risposte date,
    con valutazione e voto."""
    from rt.pipeline.recall import load_recall_bank
    bank = load_recall_bank(lesson_dir)
    questions = [question_view(q, reveal=q.status != RecallQuestionStatus.PENDING) for q in bank.questions]
    return {"questions": questions, "answers": [a.model_dump(mode="json") for a in bank.answers]}


def question_list(lesson_dir: str, reveal: bool = False) -> dict:
    """Tutte le domande della lezione per rivederle: stato, unità (con titolo), livello del
    classificatore, voto. Le soluzioni solo con reveal (per le domande ancora da porre
    rovinerebbero il recall)."""
    from rt.pipeline.recall import load_recall_bank
    from rt.pipeline.ledger import load_resolved_draft
    bank = load_recall_bank(lesson_dir)
    votes = {a.question_id: a.vote for a in bank.answers if a.vote}
    try:
        titles = {u.unit_id: u.title for u in load_resolved_draft(lesson_dir).units}
    except (FileNotFoundError, ValueError):
        titles = {}
    questions = []
    for q in bank.questions:
        view = question_view(q, reveal=reveal or q.status != RecallQuestionStatus.PENDING)
        view.update(created_at=q.created_at, classifier_level=q.classifier_level, vote=votes.get(q.id))
        questions.append(view)
    used = {uid for q in bank.questions for uid in q.unit_ids}
    return {"questions": questions, "unit_titles": {uid: titles[uid] for uid in titles if uid in used}}


# "mista": quiz, mirate, vaste, casi ed esercizi a turno nella stessa sessione.
MIXED = "mista"


def resolve_types(qtype) -> List[RecallQuestionType]:
    """I tipi da cui pescare per un tipo richiesto (un tipo, o tutti per "mista")."""
    if isinstance(qtype, RecallQuestionType):
        return [qtype]
    if qtype == MIXED:
        return list(RecallQuestionType)
    return [RecallQuestionType(qtype)]


def type_value(qtype) -> str:
    return qtype.value if isinstance(qtype, RecallQuestionType) else str(qtype)


def pending_count(lesson_dir: str, qtype, unit_id: Optional[str] = None) -> int:
    """Domande da porre del tipo (o di tutti, "mista"), eventualmente solo di un'unità."""
    from rt.pipeline.recall import _allowed_units, _question_allowed, load_recall_bank, on_unit
    types = set(resolve_types(qtype))
    allowed = _allowed_units(lesson_dir)
    return sum(1 for q in load_recall_bank(lesson_dir).questions
               if q.type in types and q.status == RecallQuestionStatus.PENDING and _question_allowed(q, allowed)
               and (unit_id is None or on_unit(q, unit_id)))


def next_question_for(lesson_dir: str, qtype, order: str = "alternato",
                      exclude_id: Optional[str] = None, unit_id: Optional[str] = None):
    """Prossima domanda pendente (la marca come posta) senza generarne di nuove; None se il
    pool del tipo è vuoto. Il cursore dell'ordine alternato è quello della sessione salvata. La
    domanda entra nella sessione web della lezione (aperta qui se non c'è, vedi
    rt.services.recall_sessions)."""
    question = pick_pending_question(lesson_dir, qtype, order=order, exclude_id=exclude_id, unit_id=unit_id)
    if question is not None:
        from rt.services.recall_sessions import record_web_question
        record_web_question(lesson_dir, question.id, type_value(qtype))
    return question


def pick_pending_question(lesson_dir: str, qtype, order: str = "alternato",
                          exclude_id: Optional[str] = None, current: bool = True, unit_id: Optional[str] = None):
    """Prossima domanda pendente della lezione (marcata come posta) con il cursore dell'ordine
    alternato della sessione salvata, senza registrarla in una sessione. current=False non la
    segna come domanda corrente della lezione (la sessione per materia non la occupa).
    Con "mista" i tipi si danno il turno a partire da quello dopo l'ultimo posto; unit_id
    limita alle domande di un'unità (Leggi e ripeti)."""
    from rt.pipeline.recall import get_next_pending_question
    state = load_recall_session_state(lesson_dir)
    types = resolve_types(qtype)
    if len(types) > 1:
        last = state.get("last_type")
        names = [t.value for t in types]
        start = names.index(last) + 1 if last in names else 0
        types = types[start:] + types[:start]
    question = None
    for candidate in types:
        question = get_next_pending_question(lesson_dir, candidate, order=order, unit_cursor=state.get("unit_cursor"),
                                             exclude_id=exclude_id, unit_id=unit_id)
        if question is not None:
            break
    if question is not None:
        state.update({"order": order, "last_type": question.type.value,
                      "unit_cursor": question.unit_ids[0] if order == "alternato" else state.get("unit_cursor")})
        if current:
            state["current_question_id"] = question.id
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
