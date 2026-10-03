"""Una domanda sostitutiva dalla domanda originale, dalle unità e dal commento."""
import json

from rt.core.models import GeneratedRecallQuestion, RecallQuestion, RecallQuestionType, RecallQuestionStatus
from rt.llm.client import LLMClient
from rt.pipeline.ledger import load_resolved_draft
from rt.pipeline.recall import (_compute_units_fingerprint, _next_id, load_fewshot_examples,
                                load_recall_bank, recall_bank_lock, save_recall_bank)
from rt.services.errors import Conflict, NotFound
from rt.services.prompt_settings import effective_system


def regenerate(lesson_dir, question_id, comment, *, job_id, force_mock=False):
    bank = load_recall_bank(lesson_dir)
    previous = next((q for q in bank.questions if q.regeneration_job_id == job_id), None)
    if previous:
        return previous  # un worker ripreso dopo il salvataggio non crea duplicati
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        raise NotFound('question_not_found', 'Domanda inesistente.')
    units = [u for u in load_resolved_draft(lesson_dir).units if u.unit_id in question.unit_ids]
    if len(units) != len(set(question.unit_ids)):
        raise Conflict('unit_not_found', 'Una delle unità della domanda non esiste più.')
    from rt.core.config import load_config
    from rt.llm.prompts import recall_fewshot_block
    from rt.services.recall_context import POLICY_VERSION, lesson_context
    examples = load_fewshot_examples(question.type, load_config().telegram.state_dir)
    prompt = recall_fewshot_block(examples) + json.dumps({
        'domanda_originale': question.model_dump(mode='json'), 'commento': comment,
        'contesto': lesson_context(lesson_dir),
        'unita': [{'id': u.unit_id, 'titolo': u.title, 'testo': u.content} for u in units],
    }, ensure_ascii=False)
    system = ('Rigenera una sola domanda dello stesso tipo dell’originale usando esclusivamente le unità '
              'fornite e seguendo il commento dell’utente. Non ripetere l’originale. Restituisci il JSON '
              'GeneratedRecallQuestion. Quiz: domanda sotto 290 caratteri, quattro opzioni distinte '
              'sotto 100 caratteri, correct_index 0-3 e spiegazione in pregenerated_material. '
              'Mirata: nessun materiale pregenerato. Vasta: scaletta ideale. Esercizio: schema di risoluzione. '
              'Caso clinico: traccia senza pregenerated_material né soluzione. Niente opzioni o indice per le domande aperte.')
    client = LLMClient(force_mock=force_mock)
    if client.force_mock:
        data = {'type': question.type, 'question_text': f'Domanda rigenerata {question.type.value} {job_id}: ragiona sui dati.'}
        if question.type == RecallQuestionType.QUIZ:
            data.update(options=['A', 'B', 'C', 'D'], correct_index=0, pregenerated_material='Spiegazione della risposta A.')
        elif question.type not in (RecallQuestionType.MIRATA, RecallQuestionType.CASO):
            data['pregenerated_material'] = 'Schema atteso: analizza i dati, ragiona, concludi.'
        generated = GeneratedRecallQuestion.model_validate(data)
    else:
        generated = client.call_structured(prompt=prompt, system_prompt=effective_system('recall', system),
            response_model=GeneratedRecallQuestion, job_name='recall', unit_id=', '.join(question.unit_ids), lesson_dir=lesson_dir)
    if generated.type != question.type:
        raise ValueError('Il tipo della domanda rigenerata è diverso dall’originale.')
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        previous = next((q for q in bank.questions if q.regeneration_job_id == job_id), None)
        if previous:
            return previous
        if not any(q.id == question_id for q in bank.questions):
            raise NotFound('question_not_found', 'La domanda è stata eliminata durante la rigenerazione.')
        if any(q.type == question.type and q.question_text.strip().casefold() == generated.question_text.strip().casefold() for q in bank.questions):
            raise Conflict('question_duplicate', 'La domanda rigenerata è già nel pool.')
        replacement = RecallQuestion(id=_next_id(bank), unit_ids=question.unit_ids, **generated.model_dump(),
            content_fingerprint=_compute_units_fingerprint(lesson_dir, question.unit_ids), generation_version=POLICY_VERSION,
            regenerated_from=question.id, regeneration_job_id=job_id, classifier_level=question.classifier_level)
        original = next(q for q in bank.questions if q.id == question_id)
        original.status, original.comment = RecallQuestionStatus.DISCARDED, comment
        bank.questions.append(replacement)
        save_recall_bank(bank, lesson_dir)
    return replacement
