"""Domande personalizzate dal registro, strutture astratte e varianti verificate."""

import logging
import random
import time
from datetime import datetime
from typing import Callable, List, Optional
from pydantic import BaseModel, Field

from rt.core.models import (RecallQuestion, RecallQuestionType, RecallSpecialGenerationResult, RecallTemplate,
                            GeneratedVariant, GeneratedTextVariant, RecallTextGenerationResult,
                            RecallEvaluation, VariantCheck)
from rt.llm.client import LLMClient
from rt.services.prompt_settings import effective_system
from rt.services.custom_question_types import find_type, active_types, type_key, question_key

_LOG = logging.getLogger(__name__)
MAX_VARIANTS_PER_CALL = 5


class TextVariantBatch(BaseModel):
    items: list[GeneratedTextVariant] = Field(max_length=MAX_VARIANTS_PER_CALL)


class VariantBatch(BaseModel):
    items: list[GeneratedVariant] = Field(max_length=MAX_VARIANTS_PER_CALL)


def _definition(qtype, lesson_dir=None):
    identifier = type_key(qtype)
    definition = find_type(identifier)
    if definition is None or lesson_dir is not None and identifier not in {t.id for t in active_types(lesson_dir=lesson_dir)}:
        raise ValueError("Tipo personalizzato non disponibile nella materia")
    return definition


def _system(qtype) -> str:
    return system_for(_definition(qtype))


def system_for(definition) -> str:
    from rt.llm import prompts
    output = prompts._TEXT_OUTPUT if definition.correzione == "testo" else prompts._SPECIAL_OUTPUT
    return effective_system("recall", definition.chiedi + "\n\n" + output +
                            "\nLa risposta dello studente è sempre testuale; non richiedere file o risposte interattive.")


def groups(lesson_dir: str, qtype: RecallQuestionType, sections=None, labels=None) -> List[list]:
    """Gruppi di sezioni da mandare al recaller per il tipo speciale, nell'ordine della lezione."""
    from rt.services import section_labels
    sections = section_labels.sections(lesson_dir) if sections is None else sections
    labels = section_labels.labels(lesson_dir, sections=sections) if labels is None else labels
    definition = _definition(qtype, lesson_dir)
    kind = definition.id
    out: List[list] = []
    previous_positive = False
    for section in sections:
        value = (labels.get(section["id"]) or {}).get(kind)
        positive = value == "presente"
        if not positive:
            previous_positive = False
            continue
        if (definition.continua and previous_positive and out and len(out[-1]) < 2):
            out[-1].append(section)
        else:
            out.append([section])
        previous_positive = True
    return out


def group_key(qtype: RecallQuestionType, group: list) -> str:
    return type_key(qtype) + ":sezioni:" + ",".join(s["id"] for s in group)


def _policy(qtype: RecallQuestionType, mock: bool) -> dict:
    from rt.core.config import load_config
    from rt.services.recall_context import POLICY_VERSION
    from rt.services.section_labels import LABEL_VERSION
    cfg = load_config()
    from rt.pipeline.recall import load_fewshot_examples
    examples = load_fewshot_examples(qtype, cfg.telegram.state_dir)
    routing = cfg.jobs.get("recall") or cfg.llm.get("recall") or cfg.jobs.get("default") or cfg.llm.get("default")
    return {"version": POLICY_VERSION, "labels": LABEL_VERSION, "style": type_key(qtype), "system": _system(qtype),
            "definition": _definition(qtype).model_dump(mode="json"), "fewshot": examples, "routing": routing.model_dump(mode="json") if routing else None, "mock": mock}


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
    definition = find_type(type_key(qtype))
    if definition is None or definition.id not in {t.id for t in active_types(lesson_dir=lesson_dir)}:
        return False
    bank = load_recall_bank(lesson_dir)
    if definition.varianti and any(t.custom_type == definition.id for t in bank.templates):
        return True
    if section_labels.mode(force_mock) == "disabled":
        return False
    policy = _policy(qtype, _mock(force_mock))
    sections = section_labels.sections(lesson_dir)
    current = section_labels.labels(lesson_dir, sections=sections)
    for group in groups(lesson_dir, qtype, sections=sections, labels=current):
        row = bank.generation_attempts.get(group_key(qtype, group), {})
        if not row.get("exhausted") or row.get("fingerprint") != _digest(lesson_dir, group, policy):
            return True
    # Sezioni non ancora classificate: la prossima generazione le valuta.
    return any(s["id"] not in current for s in sections)


def _mock_items(qtype: RecallQuestionType, group: list, existing: int, *, definition=None) -> dict:
    units = [u.unit_id for s in group for u in s["units"]]
    n = existing + 1
    definition = definition or _definition(qtype)
    what = definition.nome
    result = {"items": [{
        "question_text": f"{what} mock n. {n} per l'unità {', '.join(s['id'] for s in group)}: interpreta i dati e motiva.",
        "pregenerated_material": "Passaggi attesi: 1) lettura dei dati; 2) ragionamento; 3) conclusione.",
        "unit_ids": units,
        "tipo": {"scenario": f"{what} mock", "variabili": [{"nome": "valore", "valore": "1", "intervallo": "1-9"}],
                 "obiettivo": "Verificare il ragionamento", "procedimento": "Leggere i dati, ragionare, concludere.",
                 "esplicito": True}}]}
    if definition.correzione == "testo":
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
        known = {(question_key(q), q.question_text.strip().casefold()) for q in bank.questions}
        for question, template in pairs:
            text_key = (question_key(question), question.question_text.strip().casefold())
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
    definition = _definition(qtype, lesson_dir)
    label = definition.nome
    if unit_ids is not None:
        wanted_uids = set(unit_ids)
        from rt.services import section_labels
        from rt.pipeline.ledger import load_resolved_draft
        all_secs = section_labels.sections(lesson_dir, list(load_resolved_draft(lesson_dir).units))
        filtered = [{**s, "units": [u for u in s["units"] if u.unit_id in wanted_uids]}
                    for s in all_secs if any(u.unit_id in wanted_uids for u in s["units"])]
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
    active = todo
    for round_index in range(3):
        next_groups = []
        for position, group in enumerate(active):
            raise_if_cancelled()
            bank = load_recall_bank(lesson_dir)
            key = group_key(qtype, group)
            fingerprint = _digest(lesson_dir, group, policy)
            old = bank.generation_attempts.get(key, {})
            ids = [s["id"] for s in group]
            head = f"{label} · unità {', '.join(ids)}"
            where = {"unit_id": ", ".join(ids), "unit_title": group[0]["title"] if len(group) == 1 else None}
            if round_index == 0 and not regenerate and old.get("fingerprint") == fingerprint:
                report(position + 1, len(todo), f"{head}: già valutata", **where)
                continue
            all_units = [u.unit_id for s in group for u in s["units"]]
            existing = [t for t in bank.templates if t.custom_type == definition.id and set(t.section_ids) & set(ids)]
            started = time.monotonic()
            report(position, len(todo), f"{head}: chiedo {label.lower()} al recaller", **where)
            try:
                response_model = RecallTextGenerationResult if definition.correzione == "testo" else RecallSpecialGenerationResult
                if mock:
                    generated = response_model.model_validate(_mock_items(qtype, group, len(existing))).items
                else:
                    prompt = prompts.build_recall_special_user_prompt(
                        label, group, [t.tipo.model_dump() for t in existing], context,
                        instructions=instructions, selection=selection, text_correction=definition.correzione == "testo",
                        labels={s["id"]: "selezionata" if unit_ids is not None else "presente" for s in group})
                    from rt.pipeline.recall import load_fewshot_examples, previous_questions_on_units
                    prompt += prompts.recall_previous_block(previous_questions_on_units(bank, all_units))
                    from rt.core.config import load_config
                    prompt = prompts.recall_fewshot_block(load_fewshot_examples(qtype, load_config().telegram.state_dir)) + prompt
                    generated = client.call_structured(prompt=prompt, system_prompt=_system(qtype),
                                                       response_model=response_model, job_name="recall",
                                                       unit_id=", ".join(all_units), lesson_dir=lesson_dir).items
            except Exception as exc:
                if not is_unit_failure(exc):
                    raise
                failures.failed(", ".join(ids), type_key(qtype), exc)
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
                item_units = [u for u in item.unit_ids if u in all_units] or all_units
                template = RecallTemplate(id="temporary", kind=RecallQuestionType.PERSONALIZZATA, custom_type=definition.id, section_ids=ids, unit_ids=item_units,
                                          tipo=item.tipo, fingerprint=fingerprint)
                question = RecallQuestion(id="temporary", type=RecallQuestionType.PERSONALIZZATA, custom_type=definition.id, unit_ids=item_units, question_text=item.question_text,
                                          pregenerated_material=None if definition.correzione == "testo" else item.pregenerated_material,
                                          content_fingerprint=_compute_units_fingerprint(lesson_dir, item_units),
                                          generation_version=POLICY_VERSION, generation_fingerprint=fingerprint, variant=0)
                pairs.append((question, template))
            attempt = {"fingerprint": fingerprint, "exhausted": not pairs, "outcome": "questions" if pairs else "empty",
                       "generated_at": datetime.now().isoformat(), "question_ids": []}
            saved = _persist(lesson_dir, pairs, key, attempt)
            results.extend(saved)
            if saved:
                next_groups.append(group)
            report(position + 1, len(todo), f"{head}: " + (f"{len(saved)} {'domanda nuova' if len(saved) == 1 else 'domande nuove'}"
                   if saved else "nessuna domanda nuova") + f" ({time.monotonic() - started:.0f}s)", **where)
            if count is not None and len(results) >= count:
                break
        if count is None or len(results) >= count or not next_groups or failures.too_many():
            break
        active = next_groups
    if last_error is not None and not succeeded:
        raise last_error
    return results


def generate_variants(lesson_dir: str, template_id: str, count: int, *, force_mock=False,
                      summary=None) -> List[RecallQuestion]:
    """Un lotto per tipo, verifica indipendente per traccia e nessun nuovo tentativo."""
    from rt.llm import prompts
    from rt.llm.cancel import raise_if_cancelled
    from rt.pipeline.recall import _compute_units_fingerprint, load_recall_bank, load_fewshot_examples
    from rt.services.recall_context import POLICY_VERSION
    mock = _mock(force_mock)
    bank = load_recall_bank(lesson_dir)
    template = next((t for t in bank.templates if t.id == template_id), None)
    if template is None:
        raise KeyError(template_id)
    previous = [q.question_text for q in bank.questions if q.template_id == template.id]
    tipo = template.tipo.model_dump()
    definition = _definition(template.custom_type, lesson_dir)
    if not definition.varianti or count <= 0:
        return []
    text_correction = definition.correzione == "testo"
    model = TextVariantBatch if text_correction else VariantBatch
    system = prompts.RECALL_TEXT_VARIANT_SYSTEM_PROMPT if text_correction else prompts.RECALL_VARIANT_SYSTEM_PROMPT
    count = min(count, MAX_VARIANTS_PER_CALL)
    client = LLMClient(force_mock=mock)
    raise_if_cancelled()
    if mock:
        items = []
        for n in range(template.variants + 1, template.variants + count + 1):
            data = {'question_text': f"Variante mock n. {n} di {template.id}: {template.tipo.scenario}"}
            if not text_correction:
                data['pregenerated_material'] = template.tipo.procedimento
            items.append(data)
        candidates = model.model_validate({'items': items}).items
    else:
        prompt = prompts.recall_fewshot_block(load_fewshot_examples(template.custom_type)) + prompts.build_recall_variant_user_prompt(
            definition.nome, tipo, previous, text_correction=text_correction, batch_size=count)
        candidates = client.call_structured(prompt=prompt,
            system_prompt=effective_system("recall", definition.chiedi + "\n\n" + system + "\nLa risposta dello studente è testuale."),
            response_model=model, job_name="recall", unit_id=", ".join(template.unit_ids), lesson_dir=lesson_dir).items
    saved = []
    for candidate in candidates:
        raise_if_cancelled()
        if not mock:
            check = client.call_structured(
                prompt=prompts.build_recall_variant_check_user_prompt(tipo, candidate.question_text,
                    None if text_correction else candidate.pregenerated_material),
                system_prompt=prompts.RECALL_TEXT_VARIANT_CHECK_SYSTEM_PROMPT if text_correction else prompts.RECALL_VARIANT_CHECK_SYSTEM_PROMPT,
                response_model=VariantCheck, job_name="recall", unit_id=", ".join(template.unit_ids), lesson_dir=lesson_dir)
            if not check.coerente:
                if summary is not None:
                    summary['verification_discarded'] = summary.get('verification_discarded', 0) + 1
                _LOG.info("Variante di %s scartata: %s", template.id, check.problemi)
                continue
        question = RecallQuestion(id="temporary", type=template.kind, custom_type=template.custom_type,
            unit_ids=template.unit_ids, question_text=candidate.question_text,
            pregenerated_material=None if text_correction else candidate.pregenerated_material,
            content_fingerprint=_compute_units_fingerprint(lesson_dir, template.unit_ids),
            generation_version=POLICY_VERSION, template_id=template.id)
        saved.extend(_persist(lesson_dir, [(question, None)], None, None))
    return saved


def generate_variant(lesson_dir: str, template_id: str, *, force_mock=False) -> Optional[RecallQuestion]:
    saved = generate_variants(lesson_dir, template_id, 1, force_mock=force_mock)
    return saved[0] if saved else None


def generate_special_batch(
    lesson_dir: str, qtype: RecallQuestionType, count: Optional[int], *, force_mock: bool = False,
    regenerate: bool = False, shuffle: bool = False, progress: Optional[Callable[..., None]] = None,
    unit_ids: Optional[List[str]] = None, instructions: Optional[str] = None,
    selection: Optional[str] = None,
) -> List[RecallQuestion]:
    """Classifica le sezioni, genera dai gruppi nuovi e crea eventuali varianti verificate."""
    from rt.llm.cancel import raise_if_cancelled
    from rt.pipeline.recall import load_recall_bank
    from rt.services import section_labels
    report = progress or (lambda *args, **kwargs: None)
    if count is not None and count <= 0:
        return []
    mock = _mock(force_mock)
    definition = _definition(qtype, lesson_dir)
    label = definition.nome
    if unit_ids is None and section_labels.mode(force_mock) == "disabled":
        report(None, None, f"{label}: classificatore spento, nessuna domanda speciale")
        templates = [t for t in load_recall_bank(lesson_dir).templates if t.custom_type == definition.id]
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
    templates = [t for t in load_recall_bank(lesson_dir).templates if t.custom_type == definition.id
                 and (unit_ids is None or set(t.unit_ids) <= set(unit_ids))]
    if wanted > 0 and templates and definition.varianti:
        # Ogni passaggio distribuisce a turno i lotti fra i tipi della selezione.
        for round_index in range(3):
            found = 0
            for position, template in enumerate(templates):
                raise_if_cancelled()
                remaining = count - len(results)
                if remaining <= 0:
                    break
                size = min(MAX_VARIANTS_PER_CALL, max(1, -(-remaining // (len(templates) - position))))
                report(None, None, f"{label}: nuove varianti da {template.id}")
                saved = generate_variants(lesson_dir, template.id, size, force_mock=mock)
                results.extend(saved)
                found += len(saved)
            if len(results) >= count or not found:
                break
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
    definition = find_type(question.custom_type)
    if (definition and definition.correzione == "testo") or (definition is None and not question.pregenerated_material):
        from rt.pipeline.ledger import load_resolved_draft
        units = [u for u in load_resolved_draft(lesson_dir).units if u.unit_id in question.unit_ids]
        prompt = prompts.build_recall_eval_text_user_prompt(question.question_text, units, answer_text, dont_know=dont_know)
        system = prompts.RECALL_EVAL_TEXT_SYSTEM_PROMPT
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
