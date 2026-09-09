"""
rt.pipeline.recall
Motore di generazione e gestione delle domande di Active Recall (Fase D1).
Gestisce: persistenza del bank per lezione, selezione della prossima domanda pendente,
registrazione di risposte/voti, pool few-shot globale, generazione batch via LLM.
"""

import os
import json
import random as _random
from datetime import datetime
from typing import List, Optional, Dict

from rt.core.models import RecallBank, RecallQuestion, RecallQuestionStatus, RecallQuestionType, RecallAnswer
from rt.pipeline.rewrite import load_draft
from rt.llm.client import LLMClient
from rt.core.config import load_config
from rt.core.lesson_paths import lesson_path

# -----------------------------------------------------------------------
# Atomic write helper (same pattern as ledger.py / save_asr_issues)
# -----------------------------------------------------------------------

def _atomic_write(path: str, data: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

# -----------------------------------------------------------------------
# Recall bank persistence per lesson
# -----------------------------------------------------------------------

def get_recall_bank_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "recall_questions.json")


def load_recall_bank(lesson_dir: str) -> RecallBank:
    path = get_recall_bank_path(lesson_dir)
    if not os.path.isfile(path):
        return RecallBank()
    try:
        with open(path, "r", encoding="utf-8") as f:
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
    return sum(1 for q in bank.questions if q.type == qtype and q.status == RecallQuestionStatus.PENDING)

# -----------------------------------------------------------------------
# Pending question selection
# -----------------------------------------------------------------------

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
    bank = load_recall_bank(lesson_dir)
    pending = [q for q in bank.questions if q.type == qtype and q.status == RecallQuestionStatus.PENDING]
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
        for q in bank.questions:
            if q.id == selected.id:
                q.status = RecallQuestionStatus.ASKED
                break
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
    if not os.path.isfile(path):
        return {"quiz": [], "mirata": [], "vasta": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
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

def generate_recall_batch(
    lesson_dir: str,
    qtype: RecallQuestionType,
    count: int,
    few_shot_examples: List[dict],
    force_mock: bool = False,
) -> List[RecallQuestion]:
    """Genera `count` nuove domande di tipo qtype e le appende al recall bank.

    - Carica draft.json per ricavare le unita' didattiche.
    - Per quiz/mirata: una chiamata LLM per unita' (batch piccoli, <= count unita').
    - Per vasta: raggruppa 2-4 unita' contigue per chiamata.
    - Se count supera il numero di unita' disponibili per quiz/mirata, permette piu'
      domande sulla stessa unita' (mai solleva eccezione per lezioni corte).
    - AGGIUNGE al bank esistente, non rigenera da zero.
    - Supporta force_mock per test offline senza costi reali.
    """
    from rt.llm.prompts import (
        RECALL_QUIZ_SYSTEM_PROMPT, build_recall_quiz_user_prompt,
        RECALL_MIRATA_SYSTEM_PROMPT, build_recall_mirata_user_prompt,
        RECALL_VASTA_SYSTEM_PROMPT, build_recall_vasta_user_prompt,
    )

    draft = load_draft(lesson_dir)
    bank = load_recall_bank(lesson_dir)
    new_questions: List[RecallQuestion] = []
    client = LLMClient(force_mock=force_mock)
    units = draft.units

    # ---- Build list of unit index groups to generate questions for ----
    def _pick_unit_groups(num: int) -> List[List[int]]:
        """Restituisce i gruppi di indici di unità su cui generare domande.

        Per quiz/mirata: favorisce le unità MENO rappresentate nel bank esistente per
        quel qtype (conteggio domande in qualsiasi stato: pending/asked/answered),
        ordinando per conteggio crescente e scegliendo le prime `num`.

        Per vasta: favorisce le finestre (gruppi di 2-4 unità contigue) che coprono
        le unità meno rappresentate da domande vasta esistenti, scegliendo il punto
        di partenza basandosi sul conteggio minimo anziché sempre da i=0.
        """
        if qtype == RecallQuestionType.VASTA:
            # Conta copertura per unità (ogni domanda vasta copre un gruppo di unità)
            unit_count: Dict[str, int] = {u.unit_id: 0 for u in units}
            for q in bank.questions:
                if q.type == RecallQuestionType.VASTA:
                    for uid in q.unit_ids:
                        if uid in unit_count:
                            unit_count[uid] += 1
            # Scegli il punto di partenza come l'unità con minimo conteggio
            if units:
                min_uid = min(unit_count, key=lambda uid: unit_count[uid])
                start_i = next((i for i, u in enumerate(units) if u.unit_id == min_uid), 0)
            else:
                start_i = 0
            groups: List[List[int]] = []
            i = start_i
            seen_start = set()
            while len(groups) < num:
                if i >= len(units):
                    i = 0  # wrap-around
                if i in seen_start:
                    break  # evita loop infinito
                seen_start.add(i)
                size = min(4, max(2, len(units) - i))
                group = list(range(i, min(i + size, len(units))))
                groups.append(group)
                i += size
            return groups
        else:
            if not units:
                return []
            # Conta quante domande (qualsiasi stato) già coprono ciascuna unità
            covered: Dict[str, int] = {u.unit_id: 0 for u in units}
            for q in bank.questions:
                if q.type == qtype:
                    uid = q.unit_ids[0] if q.unit_ids else None
                    if uid and uid in covered:
                        covered[uid] += 1
            # Ordina le unità per conteggio crescente (a parità: ordine naturale del draft)
            sorted_units = sorted(range(len(units)), key=lambda i: covered[units[i].unit_id])
            groups_idx: List[List[int]] = []
            pool_idx = 0
            while len(groups_idx) < num:
                idx = sorted_units[pool_idx % len(sorted_units)]
                groups_idx.append([idx])
                pool_idx += 1
            return groups_idx

    unit_index_groups = _pick_unit_groups(count)

    for group_idxs in unit_index_groups:
        qid = _next_id(bank)

        # ---- Mock path ----
        if force_mock:
            ug_ids = [units[i].unit_id for i in group_idxs]
            qtext = f"Domanda mock {qtype.value} per unita' {', '.join(ug_ids)}"
            options = None
            correct_index = None
            pregenerated = None
            if qtype == RecallQuestionType.QUIZ:
                options = ["Opzione A (corretta)", "Opzione B", "Opzione C", "Opzione D"]
                correct_index = 0
                pregenerated = "Opzione A e' corretta perche'... Le altre tre sono sbagliate perche'..."
            elif qtype == RecallQuestionType.VASTA:
                pregenerated = "Scaletta ideale: 1) Punto essenziale; 2) Punto essenziale; 3) Punto essenziale."
            question = RecallQuestion(
                id=qid,
                type=qtype,
                unit_ids=ug_ids,
                question_text=qtext,
                options=options,
                correct_index=correct_index,
                pregenerated_material=pregenerated,
            )
            bank.questions.append(question)
            new_questions.append(question)
            continue

        # ---- Real LLM path ----
        if qtype == RecallQuestionType.QUIZ:
            u = units[group_idxs[0]]
            system_prompt = RECALL_QUIZ_SYSTEM_PROMPT
            user_prompt = build_recall_quiz_user_prompt(
                unit_id=u.unit_id,
                unit_title=u.title,
                unit_content=u.content,
                few_shot_examples=few_shot_examples or [],
            )
        elif qtype == RecallQuestionType.MIRATA:
            u = units[group_idxs[0]]
            system_prompt = RECALL_MIRATA_SYSTEM_PROMPT
            user_prompt = build_recall_mirata_user_prompt(
                unit_id=u.unit_id,
                unit_title=u.title,
                unit_content=u.content,
                few_shot_examples=few_shot_examples or [],
            )
        else:  # VASTA
            grp_units = [units[i] for i in group_idxs]
            system_prompt = RECALL_VASTA_SYSTEM_PROMPT
            user_prompt = build_recall_vasta_user_prompt(
                unit_ids=[u.unit_id for u in grp_units],
                unit_titles=[u.title for u in grp_units],
                unit_contents=[u.content for u in grp_units],
                few_shot_examples=few_shot_examples or [],
            )

        generated: RecallQuestion = client.call_structured(
            prompt=user_prompt,
            system_prompt=system_prompt,
            response_model=RecallQuestion,
            job_name=f"recall_{qtype.value}",
            unit_id=", ".join(units[i].unit_id for i in group_idxs),
            lesson_dir=lesson_dir,
        )
        generated.id = qid
        generated.type = qtype
        generated.unit_ids = [units[i].unit_id for i in group_idxs]
        bank.questions.append(generated)
        new_questions.append(generated)

    save_recall_bank(bank, lesson_dir)
    return new_questions

# -----------------------------------------------------------------------
# Valutazione LLM delle risposte a domande mirate/vaste (Fase D3)
# -----------------------------------------------------------------------

def evaluate_recall_answer(lesson_dir: str, question_id: str, answer_text: str, force_mock: bool = False) -> str:
    """Valuta con l'LLM la risposta a una domanda mirata o vasta e ritorna il testo di valutazione pronto da mostrare.

    Mirata: "Correttezza: X%\\nCompletezza: Y%\\n\\n[commento]".
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

    # Mock deterministico gestito qui direttamente (stesso pattern di generate_recall_batch):
    # _generate_mock_response() non conosce RecallEvalMirataResult/RecallEvalVastaResult.
    if force_mock:
        if question.type == RecallQuestionType.MIRATA:
            return "Correttezza: 75%\nCompletezza: 70%\n\n[MOCK] Risposta plausibile ma incompleta rispetto al riferimento."
        return "[MOCK] Risposta concettualmente corretta, ma non copre tutti i punti della scaletta ideale."

    client = LLMClient(force_mock=force_mock)

    if question.type == RecallQuestionType.MIRATA:
        draft = load_draft(lesson_dir)
        unit = next((u for u in draft.units if u.unit_id == question.unit_ids[0]), None)
        unit_title = unit.title if unit else question.unit_ids[0]
        unit_content = unit.content if unit else ""
        user_prompt = build_recall_eval_mirata_user_prompt(
            question_text=question.question_text,
            unit_title=unit_title,
            unit_content=unit_content,
            answer_text=answer_text,
        )
        result: "RecallEvalMirataResult" = client.call_structured(
            prompt=user_prompt,
            system_prompt=RECALL_EVAL_MIRATA_SYSTEM_PROMPT,
            response_model=RecallEvalMirataResult,
            job_name="recall_eval_mirata",
            unit_id=question.unit_ids[0],
            lesson_dir=lesson_dir,
        )
        return f"Correttezza: {result.correttezza}%\nCompletezza: {result.completezza}%\n\n{result.commento}"

    elif question.type == RecallQuestionType.VASTA:
        user_prompt = build_recall_eval_vasta_user_prompt(
            question_text=question.question_text,
            scaletta_ideale=question.pregenerated_material or "",
            answer_text=answer_text,
        )
        result_v: "RecallEvalVastaResult" = client.call_structured(
            prompt=user_prompt,
            system_prompt=RECALL_EVAL_VASTA_SYSTEM_PROMPT,
            response_model=RecallEvalVastaResult,
            job_name="recall_eval_vasta",
            unit_id=", ".join(question.unit_ids),
            lesson_dir=lesson_dir,
        )
        return result_v.commento
