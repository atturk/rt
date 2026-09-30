"""
rt.pipeline.recall
Motore di generazione e gestione delle domande di Active Recall (Fase D1).
Gestisce: persistenza del bank per lezione, selezione della prossima domanda pendente,
registrazione di risposte/voti, pool few-shot globale, generazione batch via LLM.
"""

import logging
import os
import json
import random as _random
from datetime import datetime
from typing import List, Optional, Dict

from rt.core.models import RecallBank, RecallQuestion, RecallQuestionStatus, RecallQuestionType, RecallAnswer
from rt.pipeline.ledger import load_resolved_draft
from rt.llm.client import LLMClient
from rt.services.prompt_settings import effective_system
from rt.core.config import load_config
from rt.core.lesson_paths import lesson_path
from rt.pipeline.unit_failures import UnitFailureTracker, is_unit_failure
from rt.storage import fs

_LOG = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Atomic write helper (same pattern as ledger.py / save_asr_issues)
# -----------------------------------------------------------------------

def _atomic_write(path: str, data: dict) -> None:
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)

# -----------------------------------------------------------------------
# Recall bank persistence per lesson
# -----------------------------------------------------------------------

def get_recall_bank_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "recall_questions.json")


def get_recall_bank_lock_path(lesson_dir: str) -> str:
    return get_recall_bank_path(lesson_dir) + ".lock"


def recall_bank_lock(lesson_dir: str, retries: int = 30, backoff: float = 0.1, stale_sec: float = 30.0):
    from rt.core.filelock import file_lock
    return file_lock(fs.lock_path(get_recall_bank_lock_path(lesson_dir)), retries=retries, backoff=backoff, stale_sec=stale_sec)


def load_recall_bank(lesson_dir: str) -> RecallBank:
    path = get_recall_bank_path(lesson_dir)
    if not fs.isfile(path):
        return RecallBank()
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RecallBank.model_validate(data)
    except Exception:
        return RecallBank()


def save_recall_bank(bank: RecallBank, lesson_dir: str) -> None:
    path = get_recall_bank_path(lesson_dir)
    data = bank.model_dump(mode="json")
    _atomic_write(path, data)


# -----------------------------------------------------------------------
# Reserve count utilities
# -----------------------------------------------------------------------

def get_reserve_count(lesson_dir: str, qtype: RecallQuestionType) -> int:
    """Conta le domande PENDING di un tipo specifico nel bank."""
    bank = load_recall_bank(lesson_dir)
    allowed = _allowed_units(lesson_dir)
    return sum(1 for q in bank.questions if q.type == qtype and q.status == RecallQuestionStatus.PENDING
               and _question_allowed(q, allowed))


def _allowed_units(lesson_dir: str) -> Optional[set]:
    """Unità da cui si possono fare domande (None = tutte), calcolate una volta per chiamata:
    prima bozza e classificazioni si rileggevano per ogni domanda del bank."""
    from rt.services.unit_relevance import included, mode
    if mode() != "active":
        return None
    try:
        draft = load_resolved_draft(lesson_dir)
    except (FileNotFoundError, ValueError):
        return None
    return {unit.unit_id for unit in draft.units if included(lesson_dir, unit, view="resolved")}


def _question_allowed(question: RecallQuestion, allowed: Optional[set]) -> bool:
    return allowed is None or all(uid in allowed for uid in question.unit_ids)


def repair_duplicate_ids(bank: RecallBank) -> int:
    """Rinumera le domande con ID già usato (bank scritti prima della correzione degli ID).
    La prima occorrenza tiene l'ID e le risposte; se però una sola delle copie è stata
    risposta, le risposte sono sue. Restituisce quante domande ha rinumerato."""
    groups: Dict[str, List[RecallQuestion]] = {}
    for question in bank.questions:
        groups.setdefault(question.id, []).append(question)
    renamed = 0
    for qid, copies in groups.items():
        if len(copies) < 2:
            continue
        answered = [q for q in copies if q.status == RecallQuestionStatus.ANSWERED]
        keeper = answered[0] if len(answered) == 1 else copies[0]
        for question in copies:
            if question is not keeper:
                question.id = _next_id(bank)
                renamed += 1
    return renamed

# -----------------------------------------------------------------------
# Pending question selection
# -----------------------------------------------------------------------

def _compute_units_fingerprint(lesson_dir: str, unit_ids: list) -> Optional[str]:
    from rt.pipeline.ledger import load_resolved_draft
    from rt.core.idempotency import compute_string_sha256
    try:
        draft = load_resolved_draft(lesson_dir)
    except Exception:
        return None
    contents = []
    for uid in unit_ids:
        unit = next((u for u in draft.units if u.unit_id == uid), None)
        if unit is None:
            return None
        contents.append(unit.content)
    return compute_string_sha256("|".join(contents))


def get_next_pending_question(
    lesson_dir: str,
    qtype: RecallQuestionType,
    order: str = "alternato",
    unit_cursor: Optional[str] = None,
    exclude_id: Optional[str] = None,
) -> Optional[RecallQuestion]:
    """Seleziona la prossima domanda pendente del tipo richiesto secondo l'ordine specificato.

    order:
        'sequenziale' - ordina per unit_ids[0] poi created_at; restituisce la prima.
        'alternato'   - round-robin tra le unità distinte; unit_cursor e' l'ultima unità servita.
        'casuale'     - scelta random tra le pending.

    exclude_id: se specificato, esclude quella domanda dal pool PRIMA di applicare l'ordine,
        così una domanda appena saltata non viene immediatamente riproposta. Se è l'unica
        pending disponibile, viene comunque restituita (fallback: meglio che bloccare).

    Marca la domanda restituita come ASKED e salva il bank.
    """
    allowed = _allowed_units(lesson_dir)
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        if repair_duplicate_ids(bank):
            save_recall_bank(bank, lesson_dir)
        pending = [q for q in bank.questions if q.type == qtype and q.status == RecallQuestionStatus.PENDING
                   and _question_allowed(q, allowed)]
        if not pending:
            return None

        # Applica exclude_id solo se ci sono altre opzioni disponibili
        if exclude_id:
            filtered = [q for q in pending if q.id != exclude_id]
            if filtered:
                pending = filtered
            # else: exclude_id è l'unica pending → viene comunque riproposta (fallback)

        selected: Optional[RecallQuestion] = None

        if order == "sequenziale":
            pending.sort(key=lambda q: (q.unit_ids[0], q.created_at))
            selected = pending[0]

        elif order == "alternato":
            unit_ids_sorted = sorted({q.unit_ids[0] for q in pending})
            if unit_cursor and unit_cursor in unit_ids_sorted:
                idx = (unit_ids_sorted.index(unit_cursor) + 1) % len(unit_ids_sorted)
            else:
                idx = 0
            target_unit = unit_ids_sorted[idx]
            for q in pending:
                if q.unit_ids[0] == target_unit:
                    selected = q
                    break
            if not selected:
                selected = pending[0]

        elif order == "casuale":
            selected = _random.choice(pending)

        else:
            selected = pending[0]

        if selected:
            selected.status = RecallQuestionStatus.ASKED  # è l'oggetto del bank, non una copia
            save_recall_bank(bank, lesson_dir)

        return selected

# -----------------------------------------------------------------------
# Answer / vote recording
# -----------------------------------------------------------------------

def record_recall_answer(
    lesson_dir: str,
    question_id: str,
    answer_text: str,
    is_voice: bool = False,
    evaluation: Optional[str] = None,
    vote: Optional[str] = None,
) -> RecallAnswer:
    """Crea o aggiorna la RecallAnswer per question_id; marca la domanda come ANSWERED."""
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        for q in bank.questions:
            if q.id == question_id:
                q.status = RecallQuestionStatus.ANSWERED
                break
        existing = next((a for a in bank.answers if a.question_id == question_id), None)
        if existing:
            existing.answer_text = answer_text
            existing.is_voice = is_voice
            existing.evaluation = evaluation
            existing.vote = vote
            existing.answered_at = datetime.now().isoformat()
            ans = existing
        else:
            ans = RecallAnswer(
                question_id=question_id,
                answer_text=answer_text,
                is_voice=is_voice,
                evaluation=evaluation,
                vote=vote,
            )
            bank.answers.append(ans)
        save_recall_bank(bank, lesson_dir)
        return ans


def skip_recall_question(lesson_dir: str, question_id: str) -> None:
    """Riporta una domanda ASKED → PENDING dopo uno skip, così non viene persa definitivamente.

    No-op se la domanda è in stato diverso da ASKED (es. già ANSWERED — non toccarla)
    o se non esiste nel bank. Centralizzata qui così sia il daemon che il terminale
    riusano la stessa logica senza duplicarla.
    """
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        for q in bank.questions:
            if q.id == question_id:
                if q.status == RecallQuestionStatus.ASKED:
                    q.status = RecallQuestionStatus.PENDING
                    save_recall_bank(bank, lesson_dir)
                return


def record_recall_vote(lesson_dir: str, question_id: str, vote: str) -> None:
    """Aggiorna solo il campo vote della RecallAnswer.

    Se non esiste ancora una RecallAnswer per question_id, ne crea una parziale
    (answer_text='', is_voice=False) per portare il voto; D3/D2 la completeranno
    quando arriva la risposta vera.
    """
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        answer = next((a for a in bank.answers if a.question_id == question_id), None)
        if not answer:
            answer = RecallAnswer(question_id=question_id, answer_text="", is_voice=False, vote=vote)
            bank.answers.append(answer)
        else:
            answer.vote = vote
        save_recall_bank(bank, lesson_dir)


# -----------------------------------------------------------------------
# Global few-shot storage  (<state_dir>/recall_fewshot.json)
# -----------------------------------------------------------------------

def get_fewshot_path(state_dir: Optional[str] = None) -> str:
    if state_dir is None:
        cfg = load_config()
        state_dir = cfg.telegram.state_dir
    return os.path.join(state_dir, "recall_fewshot.json")


def _load_fewshot(state_dir: Optional[str] = None) -> dict:
    path = get_fewshot_path(state_dir)
    if not fs.isfile(path):
        return {"quiz": [], "mirata": [], "vasta": []}
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"quiz": [], "mirata": [], "vasta": []}


def _save_fewshot(data: dict, state_dir: Optional[str] = None) -> None:
    path = get_fewshot_path(state_dir)
    _atomic_write(path, data)


def record_fewshot_vote(
    qtype: RecallQuestionType,
    question_text: str,
    vote: str,
    state_dir: Optional[str] = None,
) -> None:
    """Aggiunge un'entry al pool few-shot globale per qtype.

    Mantiene al massimo 5 voci per tipo (FIFO: la piu' vecchia esce quando se ne
    aggiunge una nuova oltre il limite). I tre pool (quiz/mirata/vasta) sono
    completamente separati: mai iniettare esempi di un tipo nel prompt di un altro.
    """
    data = _load_fewshot(state_dir)
    key = qtype.value
    entry = {"question_text": question_text, "vote": vote, "voted_at": datetime.now().isoformat()}
    lst: List[dict] = data.get(key, [])
    lst.append(entry)
    if len(lst) > 5:
        lst = lst[-5:]
    data[key] = lst
    _save_fewshot(data, state_dir)


def load_fewshot_examples(
    qtype: RecallQuestionType,
    state_dir: Optional[str] = None,
) -> List[dict]:
    """Ritorna la lista corrente di esempi few-shot per qtype.

    Puo' essere vuota (nessun esempio votato): in tal caso il prompt non include esempi.
    """
    data = _load_fewshot(state_dir)
    return data.get(qtype.value, [])

# -----------------------------------------------------------------------
# ID sequenziale (same schema as asr_NNNNNN / sci_NNNNNN)
# -----------------------------------------------------------------------

def _next_id(bank: RecallBank) -> str:
    existing = [int(q.id.split("_")[1]) for q in bank.questions if q.id.startswith("recall_")]
    nxt = max(existing, default=0) + 1
    return f"recall_{nxt:06d}"

# -----------------------------------------------------------------------
# Batch generation (mockable)
# -----------------------------------------------------------------------

def _generation_policy(qtype, few_shot_examples, force_mock=False):
    from rt.llm import prompts
    from rt.services.recall_context import POLICY_VERSION
    from rt.services.jev_mapping import effective_decision
    cfg = load_config()
    routing = cfg.jobs.get("recall") or cfg.llm.get("recall") or cfg.jobs.get("default") or cfg.llm.get("default")
    return {"version": POLICY_VERSION, "style": qtype.value, "fewshot": few_shot_examples,
            "system": effective_system("recall", getattr(prompts, "RECALL_" + qtype.value.upper() + "_SYSTEM_PROMPT")),
            "routing": routing.model_dump(mode="json") if routing else None,
            "guidance": prompts.RICHNESS_GUIDANCE, "neutral": prompts.NEUTRAL_GUIDANCE,
            "decision": effective_decision("relevance", cfg.jev).model_dump(mode="json"),
            "mode": cfg.jev.relevance_mode, "classifier": cfg.jev.relevance_model,
            "confidence_threshold": cfg.jev.relevance_threshold, "mock": force_mock or cfg.mock_llm}


def _generation_groups(units, bank, qtype):
    covered = {u.unit_id: 0 for u in units}
    for question in bank.questions:
        if question.type == qtype:
            for uid in question.unit_ids:
                if uid in covered:
                    covered[uid] += 1
    if qtype != RecallQuestionType.VASTA:
        return [[u] for u in sorted(units, key=lambda u: covered[u.unit_id])]
    groups = [units[i:i + 4] for i in range(0, len(units), 4)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-1].insert(0, groups[-2].pop())
    return sorted(groups, key=lambda group: sum(covered[u.unit_id] for u in group))


def _generation_key(qtype, group):
    return qtype.value + ":" + ",".join(u.unit_id for u in group)


def _generation_digest(lesson_dir, group, policy):
    from rt.services.recall_context import digest, lesson_context
    from rt.services.unit_relevance import recall_assessment
    return digest({"units": [(u.unit_id, u.title, u.content) for u in group],
                   "context": lesson_context(lesson_dir), "policy": policy,
                   "assessments": [recall_assessment(lesson_dir, u) for u in group]})


def generation_available(lesson_dir: str, qtype: RecallQuestionType, *, force_mock=False) -> bool:
    """Consulta checkpoint senza LLM: un'astensione invariata non avvia altri refill."""
    from rt.services.unit_relevance import included
    draft = load_resolved_draft(lesson_dir)
    units = [u for u in draft.units if included(lesson_dir, u, view="resolved")]
    bank = load_recall_bank(lesson_dir)
    examples = load_fewshot_examples(qtype, load_config().telegram.state_dir)
    policy = _generation_policy(qtype, examples, force_mock)
    for group in _generation_groups(units, bank, qtype):
        row = bank.generation_attempts.get(_generation_key(qtype, group), {})
        if not row.get("exhausted") or row.get("fingerprint") != _generation_digest(lesson_dir, group, policy):
            return True
    return False


def _persist_generation(lesson_dir, questions, key, attempt):
    """Checkpoint atomico dopo ogni risposta valida, anche se il job viene interrotto."""
    persisted = []
    with recall_bank_lock(lesson_dir):
        latest = load_recall_bank(lesson_dir)
        repair_duplicate_ids(latest)
        known = {(q.type, q.question_text.strip().casefold()) for q in latest.questions}
        for question in questions:
            text_key = (question.type, question.question_text.strip().casefold())
            if text_key in known:
                continue
            known.add(text_key)
            question.id = _next_id(latest)
            latest.questions.append(question)
            persisted.append(question)
        attempt["question_ids"] = [q.id for q in persisted]
        if not persisted:
            attempt["exhausted"] = True
            attempt["outcome"] = "empty"
        latest.generation_attempts[key] = attempt
        save_recall_bank(latest, lesson_dir)
    return persisted


def generate_recall_batch(
    lesson_dir: str, qtype: RecallQuestionType, count: int, few_shot_examples: List[dict],
    force_mock: bool = False, *, regenerate: bool = False,
) -> List[RecallQuestion]:
    """Zero o più domande per chiamata; count è un obiettivo, mai una quota del modello.

    Ogni gruppo viene visitato al massimo una volta nel job. Un esito vuoto è valido e
    viene ricordato nello storage del bank; regenerate è una richiesta esplicita.
    """
    from rt.llm import prompts
    from rt.core.models import (RecallQuizGenerationResult, RecallMirataGenerationResult,
                                RecallVastaGenerationResult)
    from rt.services.recall_context import lesson_context, POLICY_VERSION
    from rt.services.unit_relevance import refresh, included, recall_assessment
    if count <= 0:
        return []
    client = LLMClient(force_mock=force_mock)
    mock = client.force_mock
    refresh(lesson_dir, force_mock=mock, view="resolved")
    draft = load_resolved_draft(lesson_dir)
    units = [u for u in draft.units if included(lesson_dir, u, view="resolved")]
    bank = load_recall_bank(lesson_dir)
    context = lesson_context(lesson_dir)
    policy = _generation_policy(qtype, few_shot_examples or [], mock)
    results = []
    failures = UnitFailureTracker()
    last_error = None
    succeeded = False
    system = getattr(prompts, "RECALL_" + qtype.value.upper() + "_SYSTEM_PROMPT")
    response_model = {RecallQuestionType.QUIZ: RecallQuizGenerationResult,
                      RecallQuestionType.MIRATA: RecallMirataGenerationResult,
                      RecallQuestionType.VASTA: RecallVastaGenerationResult}[qtype]
    for group in _generation_groups(units, bank, qtype):
        key = _generation_key(qtype, group)
        fingerprint = _generation_digest(lesson_dir, group, policy)
        old = bank.generation_attempts.get(key, {})
        if not regenerate and old.get("exhausted") and old.get("fingerprint") == fingerprint:
            continue
        ids = [u.unit_id for u in group]
        assessment = recall_assessment(lesson_dir, group[0]) if qtype != RecallQuestionType.VASTA else {"state": "group", "level": None}
        previous = [q.question_text for q in bank.questions if q.type == qtype and set(q.unit_ids) & set(ids)]
        if mock:
            data = {"type": qtype, "question_text": f"Domanda mock {qtype.value} per unita' {', '.join(ids)}"}
            if qtype == RecallQuestionType.QUIZ:
                data.update(options=["Opzione A (corretta)", "Opzione B", "Opzione C", "Opzione D"],
                            correct_index=0, pregenerated_material="La A è corretta; B, C e D sono errate.")
            elif qtype == RecallQuestionType.VASTA:
                data["pregenerated_material"] = "Scaletta ideale: 1) Punto essenziale; 2) Collegamento."
            generated = response_model.model_validate({"questions": [data]}).questions
        else:
            if qtype == RecallQuestionType.VASTA:
                prompt = prompts.build_recall_vasta_user_prompt(ids, [u.title for u in group],
                         [u.content for u in group], few_shot_examples or [])
            else:
                u = group[0]
                builder = getattr(prompts, "build_recall_" + qtype.value + "_user_prompt")
                prompt = builder(u.unit_id, u.title, u.content, few_shot_examples or [])
            prompt = prompts.contextualize_recall_prompt(prompt, context, assessment, previous)
            try:
                generated = client.call_structured(prompt=prompt, system_prompt=effective_system("recall", system),
                    response_model=response_model, job_name="recall", unit_id=", ".join(ids), lesson_dir=lesson_dir).questions
            except Exception as exc:
                if not is_unit_failure(exc):
                    raise
                failures.failed(", ".join(ids), qtype.value, exc)
                last_error = exc
                if failures.too_many():
                    break
                continue
        failures.succeeded()
        succeeded = True
        known = {q.question_text.strip().casefold() for q in bank.questions if q.type == qtype}
        group_results = []
        for question in generated:
            text_key = question.question_text.strip().casefold()
            if text_key in known:
                continue
            known.add(text_key)
            question = RecallQuestion(id="temporary", unit_ids=ids,
                **question.model_dump(), content_fingerprint=_compute_units_fingerprint(lesson_dir, ids),
                generation_version=POLICY_VERSION, generation_fingerprint=fingerprint,
                classifier_level=assessment.get("level"))
            group_results.append(question)
        attempt = {"fingerprint": fingerprint, "exhausted": not group_results,
                   "outcome": "questions" if group_results else "empty",
                   "generated_at": datetime.now().isoformat(), "question_ids": []}
        results.extend(_persist_generation(lesson_dir, group_results, key, attempt))
        bank = load_recall_bank(lesson_dir)
        if len(results) >= count:
            break
    if last_error is not None:
        _LOG.warning("Recall %s: %d gruppi non generati; restano riprovabili", qtype.value, len(failures.failures))
        if not succeeded:
            raise last_error
    return results


# -----------------------------------------------------------------------
# Valutazione LLM delle risposte a domande mirate/vaste (Fase D3)
# -----------------------------------------------------------------------

def evaluate_recall_answer(lesson_dir: str, question_id: str, answer_text: str, force_mock: bool = False) -> str:
    """Valuta con l'LLM la risposta a una domanda mirata o vasta e ritorna il testo di valutazione pronto da mostrare.

    Mirata: "Correttezza: X%\nCompletezza: Y%\n\n[commento]".
    Vasta: solo il commento (valuta correttezza + aderenza alla scaletta ideale pregenerata).
    Le domande quiz non passano da qui: la valutazione è il pregenerated_material, già pronto in D1.
    """
    from rt.llm.prompts import (
        RECALL_EVAL_MIRATA_SYSTEM_PROMPT, build_recall_eval_mirata_user_prompt, RecallEvalMirataResult,
        RECALL_EVAL_VASTA_SYSTEM_PROMPT, build_recall_eval_vasta_user_prompt, RecallEvalVastaResult,
    )

    bank = load_recall_bank(lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        raise ValueError(f"Domanda '{question_id}' non trovata nel recall bank di '{lesson_dir}'.")

    if question.type not in (RecallQuestionType.MIRATA, RecallQuestionType.VASTA):
        raise ValueError(f"evaluate_recall_answer() non gestisce il tipo '{question.type}' (i quiz usano pregenerated_material, nessuna chiamata LLM).")

    is_dont_know = answer_text.strip() == "[Non lo so]"

    # Mock deterministico gestito qui direttamente (stesso pattern di generate_recall_batch):
    # _generate_mock_response() non conosce RecallEvalMirataResult/RecallEvalVastaResult.
    if force_mock:
        if question.type == RecallQuestionType.MIRATA:
            if is_dont_know:
                return "Correttezza: 0%\nCompletezza: 0%\n\n[MOCK] Spiegazione automatica per risposta non nota."
            return "Correttezza: 75%\nCompletezza: 70%\n\n[MOCK] Risposta plausibile ma incompleta rispetto al riferimento."
        if is_dont_know:
            return "[MOCK] Spiegazione automatica per risposta non nota."
        return "[MOCK] Risposta concettualmente corretta, ma non copre tutti i punti della scaletta ideale."

    client = LLMClient(force_mock=force_mock)

    if question.type == RecallQuestionType.MIRATA:
        draft = load_resolved_draft(lesson_dir)
        unit = next((u for u in draft.units if u.unit_id == question.unit_ids[0]), None)
        unit_title = unit.title if unit else question.unit_ids[0]
        unit_content = unit.content if unit else ""
        user_prompt = build_recall_eval_mirata_user_prompt(
            question_text=question.question_text,
            unit_title=unit_title,
            unit_content=unit_content,
            answer_text=answer_text,
            dont_know=is_dont_know,
        )
        result: "RecallEvalMirataResult" = client.call_structured(
            prompt=user_prompt,
            system_prompt=effective_system("recall", RECALL_EVAL_MIRATA_SYSTEM_PROMPT),
            response_model=RecallEvalMirataResult,
            job_name="recall",
            unit_id=question.unit_ids[0],
            lesson_dir=lesson_dir,
        )
        if is_dont_know:
            result.correttezza = 0
            result.completezza = 0
        return f"Correttezza: {result.correttezza}%\nCompletezza: {result.completezza}%\n\n{result.commento}"

    elif question.type == RecallQuestionType.VASTA:
        user_prompt = build_recall_eval_vasta_user_prompt(
            question_text=question.question_text,
            scaletta_ideale=question.pregenerated_material or "",
            answer_text=answer_text,
            dont_know=is_dont_know,
        )
        result_v: "RecallEvalVastaResult" = client.call_structured(
            prompt=user_prompt,
            system_prompt=effective_system("recall", RECALL_EVAL_VASTA_SYSTEM_PROMPT),
            response_model=RecallEvalVastaResult,
            job_name="recall",
            unit_id=", ".join(question.unit_ids),
            lesson_dir=lesson_dir,
        )
        return result_v.commento


def purge_recall_by_type(lesson_dir: str, qtype: Optional[RecallQuestionType] = None) -> int:
    """Rimuove dal recall bank le domande (e le relative risposte) del tipo specificato,
    o tutte se qtype è None. Ritorna il numero di domande rimosse."""
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        if qtype is None:
            removed_ids = {q.id for q in bank.questions}
            bank.questions = []
        else:
            removed_ids = {q.id for q in bank.questions if q.type == qtype}
            bank.questions = [q for q in bank.questions if q.type != qtype]
        bank.answers = [a for a in bank.answers if a.question_id not in removed_ids]
        old_attempts = len(bank.generation_attempts)
        bank.generation_attempts = {k: v for k, v in bank.generation_attempts.items()
                                    if qtype is not None and not k.startswith(qtype.value + ":")}
        if removed_ids or len(bank.generation_attempts) != old_attempts:
            save_recall_bank(bank, lesson_dir)
        return len(removed_ids)
