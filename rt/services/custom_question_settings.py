"""Editor del registro e prove senza scritture nei file della lezione."""
from rt.core.config import CustomQuestionType, RecallConfig, load_config
from rt.core.filelock import file_lock
from rt.services.config_service import general_config_path, read_yaml, write_yaml_atomic
from rt.services.custom_question_types import templates
from rt.services.errors import NotFound


def view():
    from rt.services.lesson_service import list_lessons
    cfg = load_config()
    subjects = sorted({row['materia'] for row in list_lessons() if row.get('materia')}, key=str.casefold)
    return {'types': cfg.recall.custom_types, 'templates': templates(), 'materie': subjects}


def get(identifier):
    from rt.services.custom_question_types import find_type
    item = find_type(identifier)
    if item is None:
        raise NotFound('type_not_found', 'Tipo di domanda inesistente.')
    return item


def _unique_id(identifier, existing):
    if identifier not in existing:
        return identifier
    number = 2
    while True:
        suffix = f'-{number}'
        candidate = identifier[:64 - len(suffix)].rstrip('-') + suffix
        if candidate not in existing:
            return candidate
        number += 1


def save(item, identifier=None, *, actor=None):
    """Creazione/importazione rinomina gli id occupati; una modifica conserva l'id stabile."""
    path = general_config_path()
    with file_lock(str(path) + '.lock'):
        data = read_yaml(path)
        recall = RecallConfig.model_validate(data.get('recall', {}))
        if identifier is not None:
            if item.id != identifier:
                raise ValueError('L’identificativo di un tipo esistente non può cambiare.')
            if not any(t.id == identifier for t in recall.custom_types):
                raise NotFound('type_not_found', 'Tipo di domanda inesistente.')
            recall.custom_types = [item if t.id == identifier else t for t in recall.custom_types]
        else:
            item = item.model_copy(update={'id': _unique_id(item.id, {t.id for t in recall.custom_types})})
            recall.custom_types.append(item)
        data.setdefault('recall', {})['custom_types'] = [t.model_dump(mode='json') for t in recall.custom_types]
        write_yaml_atomic(path, data)
    if actor is not None and _automatic_labels():
        from rt.services.jobs import get_job_queue
        from rt.services.lesson_service import list_lessons, resolve_lesson_dir
        subjects = {m.casefold() for m in item.materie}
        for lesson in list_lessons():
            if (lesson.get('materia') or '').casefold() in subjects:
                get_job_queue().enqueue('classifier', resolve_lesson_dir(lesson['id']),
                                {'job': f'custom:{item.id}', 'force': False}, created_by=actor)
    return item


def _automatic_labels():
    """Con il classificatore manuale o spento il salvataggio non accoda chiamate."""
    from rt.core.config import classifier_job, load_config
    from rt.services.section_labels import mode
    return classifier_job(load_config(), 'section_labels').mode != 'manual' and mode() != 'disabled'


def delete(identifier):
    path = general_config_path()
    with file_lock(str(path) + '.lock'):
        data = read_yaml(path)
        recall = RecallConfig.model_validate(data.get('recall', {}))
        if not any(t.id == identifier for t in recall.custom_types):
            raise NotFound('type_not_found', 'Tipo di domanda inesistente.')
        data.setdefault('recall', {})['custom_types'] = [t.model_dump(mode='json') for t in recall.custom_types if t.id != identifier]
        write_yaml_atomic(path, data)


def trial(item: CustomQuestionType, lesson_id, unit_id, *, mock=False):
    from rt.services.lesson_service import resolve_lesson_dir
    from rt.services.recall_context import lesson_context
    from rt.pipeline.ledger import load_resolved_draft
    from rt.services import section_labels
    from rt.pipeline.recall_special import _mock_items, system_for
    from rt.core.models import RecallTextGenerationResult, RecallSpecialGenerationResult
    from rt.llm.client import LLMClient
    from rt.llm.prompts import build_recall_special_user_prompt
    path = resolve_lesson_dir(lesson_id)
    context = lesson_context(path)
    if str(context.get('materia', '')).strip().casefold() not in {m.casefold() for m in item.materie}:
        raise ValueError('Scegli una lezione di una delle materie del tipo.')
    unit = next((u for u in load_resolved_draft(path).units if u.unit_id == unit_id), None)
    if unit is None:
        raise NotFound('unit_not_found', 'Unità inesistente.')
    section = {'id': unit.unit_id, 'title': unit.title, 'units': [unit]}
    cfg = load_config()
    import os
    mock = mock or cfg.mock_llm or os.environ.get("RT_API_MOCK") == "1"
    if mock:
        labels = section_labels._mock_labels(section, [item])
    else:
        labels, _ = section_labels._classify(path, section, cfg, [item], persist_cost=False)
    present = labels[item.id] == 'presente'
    example = None
    if present:
        response_model = RecallTextGenerationResult if item.correzione == 'testo' else RecallSpecialGenerationResult
        if mock:
            result = response_model.model_validate(_mock_items(item.id, [section], 0, definition=item))
        else:
            result = LLMClient(force_mock=False).call_structured(
                prompt=build_recall_special_user_prompt(item.nome, [section], [], context,
                    text_correction=item.correzione == 'testo', labels={unit_id: 'presente'}),
                system_prompt=system_for(item), response_model=response_model, job_name='recall')
        if result.items:
            example = result.items[0].model_dump(mode='json')
    return {'label': labels[item.id], 'example': example}
