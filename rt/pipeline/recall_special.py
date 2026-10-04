"""
rt.pipeline.recall_special
Casi clinici ed esercizi: domande speciali generate solo dove il classificatore delle unità
(rt.services.section_labels) li riconosce.

- Esercizio: le sezioni con un esercizio svolto, unite alla precedente quando l'esercizio
  continua (al massimo due); una chiamata al recaller per gruppo.
- Caso clinico: una chiamata per sezione; il recaller restituisce da zero a N casi.

Ogni elemento restituito diventa una domanda (variante 0, dal testo della lezione) e un "tipo"
salvato nel bank (RecallBank.templates). Quando le domande da porre finiscono, il rifornimento
crea varianti dai tipi; una seconda chiamata verifica i dati clinici o risolve gli esercizi
in modo indipendente e scarta le varianti incoerenti.
"""

import logging
import random
import time
from datetime import datetime
from typing import Callable, List, Optional

from rt.core.models import (RecallQuestion, RecallQuestionType, RecallSpecialGenerationResult, RecallTemplate,
                            GeneratedVariant, GeneratedClinicalVariant, RecallClinicalGenerationResult,
                            RecallEvaluation, VariantCheck)
from rt.llm.client import LLMClient
from rt.services.prompt_settings import effective_system

_LOG = logging.getLogger(__name__)
MAX_EXERCISE_SECTIONS = 2
VARIANT_ATTEMPTS = 2


def _system(qtype: RecallQuestionType) -> str:
    from rt.llm import prompts
    return effective_system("recall", getattr(prompts, "RECALL_" + qtype.value.upper() + "_SYSTEM_PROMPT"))


def groups(lesson_dir: str, qtype: RecallQuestionType, sections=None, labels=None) -> List[list]:
    """Gruppi di sezioni da mandare al recaller per il tipo speciale, nell'ordine della lezione."""
    from rt.services import section_labels
    sections = section_labels.sections(lesson_dir) if sections is None else sections
    labels = section_labels.labels(lesson_dir) if labels is None else labels
    kind = qtype.value
    out: List[list] = []
    previous_positive = False
    for section in sections:
        value = (labels.get(section["id"]) or {}).get(kind)
        positive = value in section_labels.POSITIVE[kind]
        if not positive:
            previous_positive = False
            continue
        if (qtype == RecallQuestionType.ESERCIZIO and value == "continua" and previous_positive and out
                and len(out[-1]) < MAX_EXERCISE_SECTIONS):
            out[-1].append(section)
        else:
            out.append([section])
        previous_positive = True
    return out


def group_key(qtype: RecallQuestionType, group: list) -> str:
    return qtype.value + ":sezioni:" + ",".join(s["id"] for s in group)


def _policy(qtype: RecallQuestionType, mock: bool) -> dict:
    from rt.core.config import load_config
    from rt.services.recall_context import POLICY_VERSION
    from rt.services.section_labels import LABEL_VERSION
    cfg = load_config()
    from rt.pipeline.recall import load_fewshot_examples
    examples = load_fewshot_examples(qtype, cfg.telegram.state_dir)
    routing = cfg.jobs.get("recall") or cfg.llm.get("recall") or cfg.jobs.get("default") or cfg.llm.get("default")
    return {"version": POLICY_VERSION, "labels": LABEL_VERSION, "style": qtype.value, "system": _system(qtype),
            "fewshot": examples, "routing": routing.model_dump(mode="json") if routing else None, "mock": mock}


def _digest(lesson_dir: str, group: list, policy: dict) -> str:
    from rt.services.recall_context import digest, lesson_context
    return digest({"sections": [(s["id"], s["title"], [(u.unit_id, u.title, u.content) for u in s["units"]])
                                for s in group],
                   "context": lesson_context(lesson_dir), "policy": policy})


def _mock(force_mock: bool) -> bool:
    from rt.core.config import load_config
    return bool(force_mock or load_config().mock_llm)


def available(lesson_dir: str, qtype: RecallQuestionType, *, force_mock: bool = False) -> bool:
    """Senza LLM: c'è un gruppo ancora da valutare, oppure un tipo da cui creare varianti."""
    from rt.pipeline.recall import load_recall_bank
    from rt.services import section_labels
    bank = load_recall_bank(lesson_dir)
    if any(t.kind == qtype for t in bank.templates):
        return True
    if section_labels.mode(force_mock) == "disabled":
        return False
    policy = _policy(qtype, _mock(force_mock))
    for group in groups(lesson_dir, qtype):
        row = bank.generation_attempts.get(group_key(qtype, group), {})
        if not row.get("exhausted") or row.get("fingerprint") != _digest(lesson_dir, group, policy):
            return True
    # Sezioni non ancora classificate: la prossima generazione le valuta.
    current = section_labels.labels(lesson_dir)
    return any(s["id"] not in current for s in section_labels.sections(lesson_dir))


def _mock_items(qtype: RecallQuestionType, group: list, existing: int) -> dict:
    units = [u.unit_id for s in group for u in s["units"]]
    n = existing + 1
    what = "Caso clinico" if qtype == RecallQuestionType.CASO else "Esercizio"
    result = {"items": [{
        "question_text": f"{what} mock n. {n} per l'unità {', '.join(s['id'] for s in group)}: interpreta i dati e motiva.",
        "pregenerated_material": "Passaggi attesi: 1) lettura dei dati; 2) ragionamento; 3) conclusione.",
        "unit_ids": units,
        "tipo": {"scenario": f"{what} mock", "variabili": [{"nome": "valore", "valore": "1", "intervallo": "1-9"}],
                 "obiettivo": "Verificare il ragionamento", "procedimento": "Leggere i dati, ragionare, concludere.",
                 "esplicito": qtype == RecallQuestionType.CASO}}]}
    if qtype == RecallQuestionType.CASO:
        result['items'][0].pop('pregenerated_material')
    return result


def _persist(lesson_dir: str, pairs: list, key: Optional[str], attempt: Optional[dict]) -> List[RecallQuestion]:
    """Salva domande e tipi (pairs: [(RecallQuestion, RecallTemplate | None)]) in un'unica
    scrittura del bank; i tipi nuovi ricevono l'ID qui e le domande vi puntano."""
    from rt.pipeline.recall import _next_id, load_recall_bank, recall_bank_lock, repair_duplicate_ids, save_recall_bank
    persisted = []
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        repair_duplicate_ids(bank)
        known = {(q.type, q.question_text.strip().casefold()) for q in bank.questions}
        for question, template in pairs:
            text_key = (question.type, question.question_text.strip().casefold())
            if text_key in known:
                continue
            known.add(text_key)
            if template is not None and template.id == "temporary":
                number = max([bank.last_template_number] + [int(t.id.split("_")[1]) for t in bank.templates
                                                             if t.id.startswith("template_")]) + 1
                bank.last_template_number = number
                template.id = f"template_{number:06d}"
                bank.templates.append(template)
                question.template_id = template.id
            elif question.template_id:
                stored = next((t for t in bank.templates if t.id == question.template_id), None)
                if stored is not None:
                    stored.variants += 1
                    question.variant = stored.variants
            question.id = _next_id(bank)
            bank.questions.append(question)
            persisted.append(question)
        if key is not None and attempt is not None:
            attempt["question_ids"] = [q.id for q in persisted]
            if not persisted:
                attempt["exhausted"] = True
                attempt["outcome"] = "empty"
            bank.generation_attempts[key] = attempt
        save_recall_bank(bank, lesson_dir)
    return persisted


def _originals(lesson_dir, qtype, count, mock, regenerate, shuffle, report,
               unit_ids: Optional[List[str]] = None, instructions: Optional[str] = None,
               selection: Optional[str] = None) -> List[RecallQuestion]:
    from rt.llm import prompts
    from rt.llm.cancel import raise_if_cancelled
    from rt.pipeline.recall import _compute_units_fingerprint, load_recall_bank
    from rt.pipeline.unit_failures import UnitFailureTracker, is_unit_failure
    from rt.services.recall_context import POLICY_VERSION, lesson_context
    label = "Casi clinici" if qtype == RecallQuestionType.CASO else "Esercizi"
    if unit_ids is not None:
        wanted_uids = set(unit_ids)
        from rt.services import section_labels
        all_secs = section_labels.sections(lesson_dir)
        filtered = [s for s in all_secs if any(u.unit_id in wanted_uids for u in s.get("units", []))]
        if filtered:
            todo = [[s] for s in filtered]
        else:
            from rt.pipeline.ledger import load_resolved_draft
            draft = load_resolved_draft(lesson_dir)
            matched_units = [u for u in draft.units if u.unit_id in wanted_uids]
            if matched_units:
                todo = [[{"id": u.unit_id, "title": u.title, "units": [u]} for u in matched_units]]
            else:
                todo = []
    else:
        todo = groups(lesson_dir, qtype)
    if shuffle:
        random.shuffle(todo)
    policy = _policy(qtype, mock)
    context = lesson_context(lesson_dir)
    client = LLMClient(force_mock=mock)
    failures = UnitFailureTracker()
    results, last_error, succeeded = [], None, False
    report(0, len(todo), f"{label}: {len(todo)} {'unità' if len(todo) != 1 else 'unità'} riconosciute dal classificatore")
    for position, group in enumerate(todo):
        raise_if_cancelled()
        bank = load_recall_bank(lesson_dir)
        key = group_key(qtype, group)
        fingerprint = _digest(lesson_dir, group, policy)
        old = bank.generation_attempts.get(key, {})
        ids = [s["id"] for s in group]
        head = f"{label} · unità {', '.join(ids)}"
        where = {"unit_id": ", ".join(ids), "unit_title": group[0]["title"] if len(group) == 1 else None}
        if not regenerate and old.get("fingerprint") == fingerprint:
            report(position + 1, len(todo), f"{head}: già valutata", **where)
            continue
        all_units = [u.unit_id for s in group for u in s["units"]]
        existing = [t for t in bank.templates if t.kind == qtype and set(t.section_ids) & set(ids)]
        started = time.monotonic()
        report(position, len(todo), f"{head}: chiedo {label.lower()} al recaller", **where)
        try:
            response_model = RecallClinicalGenerationResult if qtype == RecallQuestionType.CASO else RecallSpecialGenerationResult
            if mock:
                generated = response_model.model_validate(_mock_items(qtype, group, len(existing))).items
            else:
                prompt = prompts.build_recall_special_user_prompt(
                    qtype.value, group, [t.tipo.model_dump() for t in existing], context,
                    instructions=instructions, selection=selection)
                from rt.pipeline.recall import load_fewshot_examples
                from rt.core.config import load_config
                prompt = prompts.recall_fewshot_block(load_fewshot_examples(qtype, load_config().telegram.state_dir)) + prompt
                generated = client.call_structured(prompt=prompt, system_prompt=_system(qtype),
                                                   response_model=response_model, job_name="recall",
                                                   unit_id=", ".join(all_units), lesson_dir=lesson_dir).items
        except Exception as exc:
            if not is_unit_failure(exc):
                raise
            failures.failed(", ".join(ids), qtype.value, exc)
            report(position + 1, len(todo), f"{head}: non riuscita ({type(exc).__name__}), si riprova alla prossima generazione",
                   failed=len(failures.failures), **where)
            last_error = exc
            if failures.too_many():
                break
            continue
        failures.succeeded()
        succeeded = True
        pairs = []
        for item in generated:
            unit_ids = [u for u in item.unit_ids if u in all_units] or all_units
            template = RecallTemplate(id="temporary", kind=qtype, section_ids=ids, unit_ids=unit_ids,
                                      tipo=item.tipo, fingerprint=fingerprint)
            question = RecallQuestion(id="temporary", type=qtype, unit_ids=unit_ids, question_text=item.question_text,
                                      pregenerated_material=None if qtype == RecallQuestionType.CASO else item.pregenerated_material,
                                      content_fingerprint=_compute_units_fingerprint(lesson_dir, unit_ids),
                                      generation_version=POLICY_VERSION, generation_fingerprint=fingerprint, variant=0)
            pairs.append((question, template))
        attempt = {"fingerprint": fingerprint, "exhausted": not pairs, "outcome": "questions" if pairs else "empty",
                   "generated_at": datetime.now().isoformat(), "question_ids": []}
        saved = _persist(lesson_dir, pairs, key, attempt)
        results.extend(saved)
        report(position + 1, len(todo), f"{head}: " + (f"{len(saved)} {'domanda nuova' if len(saved) == 1 else 'domande nuove'}"
               if saved else "nessuna domanda nuova") + f" ({time.monotonic() - started:.0f}s)", **where)
        if count is not None and len(results) >= count:
            break
    if last_error is not None and not succeeded:
        raise last_error
    return results


def generate_variant(lesson_dir: str, template_id: str, *, force_mock: bool = False) -> Optional[RecallQuestion]:
    """Una variante verificata del tipo, salvata nel pool; None se le verifiche falliscono."""
    from rt.llm import prompts
    from rt.pipeline.recall import _compute_units_fingerprint, load_recall_bank, load_fewshot_examples
    from rt.services.recall_context import POLICY_VERSION
    mock = _mock(force_mock)
    bank = load_recall_bank(lesson_dir)
    template = next((t for t in bank.templates if t.id == template_id), None)
    if template is None:
        raise KeyError(template_id)
    previous = [q.question_text for q in bank.questions if q.template_id == template.id]
    tipo = template.tipo.model_dump()
    clinical = template.kind == RecallQuestionType.CASO
    response_model = GeneratedClinicalVariant if clinical else GeneratedVariant
    system = prompts.RECALL_CLINICAL_VARIANT_SYSTEM_PROMPT if clinical else prompts.RECALL_VARIANT_SYSTEM_PROMPT
    variant = None
    if mock:
        data = {'question_text': f"Variante mock n. {template.variants + 1} di {template.id}: {template.tipo.scenario}"}
        if not clinical:
            data['pregenerated_material'] = template.tipo.procedimento
        variant = response_model.model_validate(data)
    else:
        client = LLMClient(force_mock=False)
        problems = ""
        for _ in range(VARIANT_ATTEMPTS):
            candidate = client.call_structured(
                prompt=prompts.recall_fewshot_block(load_fewshot_examples(template.kind)) + prompts.build_recall_variant_user_prompt(template.kind.value, tipo, previous, problems),
                system_prompt=effective_system("recall", system),
                response_model=response_model, job_name="recall", unit_id=", ".join(template.unit_ids),
                lesson_dir=lesson_dir)
            check = client.call_structured(
                prompt=prompts.build_recall_variant_check_user_prompt(tipo, candidate.question_text,
                                                                     None if clinical else candidate.pregenerated_material),
                system_prompt=prompts.RECALL_CLINICAL_VARIANT_CHECK_SYSTEM_PROMPT if clinical else prompts.RECALL_VARIANT_CHECK_SYSTEM_PROMPT, response_model=VariantCheck,
                job_name="recall", unit_id=", ".join(template.unit_ids), lesson_dir=lesson_dir)
            if check.coerente:
                variant = candidate
                break
            problems = check.problemi or "La soluzione non coincide con quella ricavata in modo indipendente."
            _LOG.info("Variante di %s scartata: %s", template.id, problems)
    if variant is None:
        return None
    question = RecallQuestion(id="temporary", type=template.kind, unit_ids=template.unit_ids,
                              question_text=variant.question_text, pregenerated_material=None if clinical else variant.pregenerated_material,
                              content_fingerprint=_compute_units_fingerprint(lesson_dir, template.unit_ids),
                              generation_version=POLICY_VERSION, template_id=template.id)
    saved = _persist(lesson_dir, [(question, None)], None, None)
    return saved[0] if saved else None


def generate_special_batch(
    lesson_dir: str, qtype: RecallQuestionType, count: Optional[int], *, force_mock: bool = False,
    regenerate: bool = False, shuffle: bool = False, progress: Optional[Callable[..., None]] = None,
    unit_ids: Optional[List[str]] = None, instructions: Optional[str] = None,
    selection: Optional[str] = None,
) -> List[RecallQuestion]:
    """Classifica le sezioni cambiate, genera casi o esercizi dai gruppi nuovi e, se servono altre
    domande (count), crea varianti dai tipi già salvati scelti a caso."""
    from rt.llm.cancel import raise_if_cancelled
    from rt.pipeline.recall import load_recall_bank
    from rt.services import section_labels
    report = progress or (lambda *args, **kwargs: None)
    if count is not None and count <= 0:
        return []
    mock = _mock(force_mock)
    label = "Casi clinici" if qtype == RecallQuestionType.CASO else "Esercizi"
    if unit_ids is None and section_labels.mode(force_mock) == "disabled":
        report(None, None, f"{label}: classificatore spento, nessuna domanda speciale")
        templates = [t for t in load_recall_bank(lesson_dir).templates if t.kind == qtype]
        if not templates:
            return []
    elif unit_ids is None:
        raise_if_cancelled()
        report(None, None, f"{label}: il classificatore valuta le unità")
        section_labels.refresh(lesson_dir, force_mock=mock)
    results = _originals(lesson_dir, qtype, count, mock, regenerate, shuffle, report,
                         unit_ids=unit_ids, instructions=instructions, selection=selection) \
        if (unit_ids is not None or section_labels.mode(force_mock) != "disabled") else []
    wanted = (count - len(results)) if count is not None else 0
    templates = [t for t in load_recall_bank(lesson_dir).templates if t.kind == qtype]
    if wanted > 0 and templates:
        random.shuffle(templates)
        for template in templates[:min(wanted, 2)]:  # ogni variante costa due chiamate
            raise_if_cancelled()
            report(None, None, f"{label}: nuova variante da {template.id}")
            question = generate_variant(lesson_dir, template.id, force_mock=mock)
            if question is not None:
                results.append(question)
    return results


def evaluate(lesson_dir: str, question, answer_text: str, *, force_mock: bool = False) -> str:
    """Valutazione del ragionamento, nello stesso formato delle mirate (Correttezza/Completezza)."""
    from rt.llm import prompts
    from rt.pipeline.recall import load_recall_bank
    dont_know = answer_text.strip() == "[Non lo so]"
    if _mock(force_mock):
        if dont_know:
            return RecallEvaluation("Correttezza: 0%\nCompletezza: 0%\n\n[MOCK] Ragionamento atteso spiegato passo per passo.", "sbagliata")
        return RecallEvaluation("Correttezza: 70%\nCompletezza: 60%\n\n[MOCK] Conclusione corretta, manca un passaggio del ragionamento.", "parziale")
    if question.type == RecallQuestionType.CASO:
        from rt.pipeline.ledger import load_resolved_draft
        units = [u for u in load_resolved_draft(lesson_dir).units if u.unit_id in question.unit_ids]
        prompt = prompts.build_recall_eval_caso_user_prompt(question.question_text, units, answer_text, dont_know=dont_know)
        system = prompts.RECALL_EVAL_CASO_SYSTEM_PROMPT
    else:
        template = next((t for t in load_recall_bank(lesson_dir).templates if t.id == question.template_id), None)
        prompt = prompts.build_recall_eval_ragionamento_user_prompt(
            question.question_text, question.pregenerated_material or "",
            template.tipo.procedimento if template else "", answer_text, dont_know=dont_know)
        system = prompts.RECALL_EVAL_RAGIONAMENTO_SYSTEM_PROMPT
    result = LLMClient(force_mock=False).call_structured(
        prompt=prompt,
        system_prompt=effective_system("recall", system),
        response_model=prompts.RecallEvalMirataResult, job_name="recall", unit_id=", ".join(question.unit_ids),
        lesson_dir=lesson_dir)
    if dont_know:
        result.correttezza = 0
        result.completezza = 0
    return RecallEvaluation(f"Correttezza: {result.correttezza}%\nCompletezza: {result.completezza}%\n\n{result.commento}",
                            "sbagliata" if dont_know else result.outcome)
