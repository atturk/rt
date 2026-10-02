"""Casi clinici ed esercizi: etichette nascoste delle unità (macro-sezioni), recaller speciale,
tipi rigenerabili in varianti verificate, tipo "mista" e ripasso di una sola unità."""
import json
import os
from unittest.mock import patch

import pytest

from rt.core.config import JevConfig, RTConfig
from rt.core.models import (GeneratedVariant, RecallQuestionStatus, RecallQuestionType, RecallSpecialGenerationResult,
                            VariantCheck)
from rt.llm.jev_client import JevChoiceAnswer, JevResponse
from rt.llm.prompts import RecallEvalMirataResult
from rt.pipeline import recall, recall_special
from rt.services import recall_service, section_labels
from tests.test_jev_prefilter import setup_mock_lesson

ACTIVE = RTConfig(jev=JevConfig(relevance_mode='shadow', relevance_model='typesafe/jev-1.13'))
CASO, ESERCIZIO = RecallQuestionType.CASO, RecallQuestionType.ESERCIZIO

UNITS = [
    ('1.1', 'Equilibrio acido-base', 'Il pH del sangue dipende dal rapporto tra bicarbonato e anidride carbonica.'),
    ('1.2', 'Pazienti in pronto soccorso', 'Arriva un paziente con pH 7,25 e pCO2 60: acidosi respiratoria. '
                                          'Un secondo paziente ha pH 7,50 e HCO3 35.'),
    ('2.1', 'Calcolo del gap anionico', 'Svolgiamo un esercizio: Na 140, Cl 100, HCO3 24, gap = 16.'),
    ('2.2', 'Verifica del risultato', 'Concludiamo l\'esercizio confrontando il gap con i valori normali.'),
    ('3.1', 'Organizzazione', 'Il ricevimento è il martedì.'),
]


def lesson(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=len(UNITS))
    with open(os.path.join(path, 'draft.json'), encoding='utf-8') as f:
        draft = json.load(f)
    for unit, (uid, title, content) in zip(draft['units'], UNITS):
        unit.update(unit_id=uid, title=title, content=content)
    with open(os.path.join(path, 'draft.json'), 'w', encoding='utf-8') as f:
        json.dump(draft, f)
    outline = {'schema_version': '1.0', 'macro_sections': [
        {'id': sid, 'title': title, 'units': [
            {'id': u[0], 'title': u[1], 'start_segment_id': 'seg_000001', 'end_segment_id': 'seg_000001'}
            for u in UNITS if u[0].startswith(sid + '.')]}
        for sid, title in (('1', 'Acido-base'), ('2', 'Gap anionico'), ('3', 'Avvisi'))]}
    with open(os.path.join(path, '_state', 'outline.json'), 'w', encoding='utf-8') as f:
        json.dump(outline, f)
    return path


def jev(esercizio, caso):
    return JevResponse(model='typesafe/jev-1.13', answers={
        'esercizio': JevChoiceAnswer(choice=esercizio, confidence=0.9),
        'caso_clinico': JevChoiceAnswer(choice=caso, confidence=0.8)})


def test_sections_follow_the_outline_and_mock_labels_use_keywords(tmp_path):
    path = lesson(tmp_path)
    sections = section_labels.sections(path)
    assert [(s['id'], [u.unit_id for u in s['units']]) for s in sections] == [
        ('1', ['1.1', '1.2']), ('2', ['2.1', '2.2']), ('3', ['3.1'])]
    section_labels.refresh(path, force_mock=True)
    assert section_labels.labels(path) == {
        '1': {'esercizio': 'nessuno', 'caso': 'esplicito'},
        '2': {'esercizio': 'svolto', 'caso': 'nessuno'},
        '3': {'esercizio': 'nessuno', 'caso': 'nessuno'}}


def test_classifier_reads_whole_sections_once_and_keeps_user_corrections(tmp_path):
    path = lesson(tmp_path)
    responses = [jev('nessuno', 'esplicito'), jev('svolto', 'nessuno'), jev('nessuno', 'nessuno')]
    with patch.object(section_labels, 'load_config', return_value=ACTIVE), \
            patch('rt.llm.jev_client.call_jev', side_effect=responses) as call:
        section_labels.refresh(path)
        assert call.call_count == 3  # una chiamata per sezione, due domande ciascuna
        state = call.call_args_list[0].kwargs['state']
        assert '[1.1]' in state and '[1.2]' in state
        assert set(call.call_args_list[0].kwargs['questions']) == {'esercizio', 'caso_clinico'}
        section_labels.refresh(path)  # testo invariato: nessuna nuova chiamata
        assert call.call_count == 3
        section_labels.set_override(path, '3', 'caso', 'adattabile')
        assert section_labels.labels(path)['3'] == {'esercizio': 'nessuno', 'caso': 'adattabile'}
        assert section_labels.view(path)['sections'][2]['override_caso'] == 'adattabile'
    with pytest.raises(ValueError):
        section_labels.set_override(path, '3', 'caso', 'svolto')


def test_without_classifier_there_are_no_special_questions(tmp_path):
    path = lesson(tmp_path)
    assert section_labels.mode() == 'disabled'
    assert recall.generate_recall_batch(path, CASO, None, []) == []
    assert not recall.generation_available(path, CASO)


def test_exercise_groups_merge_a_continuing_section_and_cases_stay_per_section(tmp_path):
    path = lesson(tmp_path)
    sections = section_labels.sections(path)
    labels = {'1': {'esercizio': 'svolto', 'caso': 'esplicito'}, '2': {'esercizio': 'continua', 'caso': 'adattabile'},
              '3': {'esercizio': 'continua', 'caso': 'nessuno'}}
    assert [[s['id'] for s in g] for g in recall_special.groups(path, ESERCIZIO, sections, labels)] == [['1', '2'], ['3']]
    assert [[s['id'] for s in g] for g in recall_special.groups(path, CASO, sections, labels)] == [['1'], ['2']]


def test_generation_saves_questions_and_templates_once_per_unchanged_section(tmp_path):
    path = lesson(tmp_path)
    first = recall.generate_recall_batch(path, CASO, None, [], force_mock=True)
    assert len(first) == 1 and first[0].unit_ids == ['1.1', '1.2'] and first[0].variant == 0
    bank = recall.load_recall_bank(path)
    template = bank.templates[0]
    assert template.kind == CASO and template.section_ids == ['1'] and first[0].template_id == template.id
    assert recall.generate_recall_batch(path, CASO, None, [], force_mock=True) == []  # già valutata
    exercise = recall.generate_recall_batch(path, ESERCIZIO, None, [], force_mock=True)
    assert [q.unit_ids for q in exercise] == [['2.1', '2.2']]
    assert len(recall.load_recall_bank(path).templates) == 2


def test_real_generation_passes_existing_templates_and_filters_unit_ids(tmp_path):
    path = lesson(tmp_path)
    section_labels.refresh(path, force_mock=True)
    item = {'question_text': 'Paziente con pH 7,25: quale disturbo?', 'pregenerated_material': 'Acidosi respiratoria.',
            'unit_ids': ['1.2', '9.9'], 'tipo': {'scenario': 'Paziente in PS', 'obiettivo': 'Interpretare EGA',
                                                'procedimento': 'pH, pCO2, HCO3', 'esplicito': True,
                                                'variabili': [{'nome': 'pH', 'valore': '7,25', 'intervallo': '7,1-7,6'}]}}
    second = dict(item, question_text='Secondo paziente con HCO3 35: quale disturbo?')
    with patch.object(section_labels, 'mode', return_value='active'), \
            patch.object(section_labels, 'refresh'), \
            patch.object(recall_special, '_mock', return_value=False), \
            patch('rt.llm.client.LLMClient.call_structured',
                  return_value=RecallSpecialGenerationResult.model_validate({'items': [item, second]})) as call:
        questions = recall.generate_recall_batch(path, CASO, None, [])
        assert [q.unit_ids for q in questions] == [['1.2'], ['1.2']]  # 9.9 non è nell'unità
        assert 'SUBUNITÀ 1.1' in call.call_args.kwargs['prompt']
        recall.generate_recall_batch(path, CASO, None, [], regenerate=True)
        assert 'GIÀ PRESENTI' in call.call_args.kwargs['prompt'] and 'Paziente in PS' in call.call_args.kwargs['prompt']


def test_variants_are_verified_and_discarded_when_the_solution_does_not_match(tmp_path):
    path = lesson(tmp_path)
    recall.generate_recall_batch(path, CASO, None, [], force_mock=True)
    template = recall.load_recall_bank(path).templates[0]
    variant = GeneratedVariant(question_text='Paziente con pH 7,30 e pCO2 55', pregenerated_material='Acidosi respiratoria')
    calls = [variant, VariantCheck(coerente=False, problemi='pCO2 incoerente'),
             variant.model_copy(update={'question_text': 'Paziente con pH 7,32 e pCO2 52'}), VariantCheck(coerente=True)]
    with patch.object(recall_special, '_mock', return_value=False), \
            patch('rt.llm.client.LLMClient.call_structured', side_effect=calls) as call:
        question = recall_special.generate_variant(path, template.id)
    assert question.question_text.endswith('pCO2 52') and question.variant == 1 and question.template_id == template.id
    assert 'pCO2 incoerente' in call.call_args_list[2].kwargs['prompt']
    with patch.object(recall_special, '_mock', return_value=False), \
            patch('rt.llm.client.LLMClient.call_structured', side_effect=[variant, VariantCheck(coerente=False)] * 2):
        assert recall_special.generate_variant(path, template.id) is None
    assert recall.load_recall_bank(path).templates[0].variants == 1


def test_refill_of_an_exhausted_pool_creates_variants(tmp_path):
    path = lesson(tmp_path)
    recall.generate_recall_batch(path, CASO, None, [], force_mock=True)
    asked = recall.get_next_pending_question(path, CASO)
    recall.record_recall_answer(path, asked.id, 'risposta')
    assert recall_service.is_low(path, CASO) and recall.generation_available(path, CASO, force_mock=True)
    refill = recall.generate_recall_batch(path, CASO, 4, [], force_mock=True, shuffle=True)
    assert len(refill) == 1 and refill[0].variant == 1 and 'Variante mock' in refill[0].question_text


def test_special_answers_are_evaluated_on_the_reasoning(tmp_path):
    path = lesson(tmp_path)
    question = recall.generate_recall_batch(path, ESERCIZIO, None, [], force_mock=True)[0]
    with patch.object(recall_special, '_mock', return_value=False), \
            patch('rt.llm.client.LLMClient.call_structured',
                  return_value=RecallEvalMirataResult(correttezza=80, completezza=50, commento='Manca la verifica.')) as call:
        text = recall.evaluate_recall_answer(path, question.id, 'gap 16')
    assert text.startswith('Correttezza: 80%\nCompletezza: 50%')
    assert 'PROCEDIMENTO DEL TIPO' in call.call_args.kwargs['prompt']


def test_mixed_sessions_rotate_types(tmp_path):
    path = lesson(tmp_path)
    recall_service.generate_pool(path, force_mock=True)
    bank = recall.load_recall_bank(path)
    assert {q.type for q in bank.questions} == set(RecallQuestionType)
    types = [recall_service.pick_pending_question(path, 'mista').type.value for _ in range(6)]
    assert types == ['quiz', 'mirata', 'vasta', 'caso', 'esercizio', 'quiz']


def test_unit_review_filters_questions(tmp_path):
    path = lesson(tmp_path)
    recall_service.generate_pool(path, force_mock=True)
    unit = []
    while (q := recall_service.pick_pending_question(path, 'mista', unit_id='1.2')) is not None:
        unit.append(q)
    assert unit and all(q.type != RecallQuestionType.VASTA for q in unit)
    assert all('1.2' in q.unit_ids for q in unit)
    assert any(q.type == CASO for q in unit)  # il caso arriva sull'ultima subunità
    assert recall_service.pick_pending_question(path, 'mista', unit_id='1.1').type != CASO
    assert recall_service.pending_count(path, 'mista', unit_id='1.2') == 0


def test_reset_of_a_special_type_drops_its_templates(tmp_path):
    path = lesson(tmp_path)
    recall.generate_recall_batch(path, CASO, None, [], force_mock=True)
    recall.generate_recall_batch(path, ESERCIZIO, None, [], force_mock=True)
    assert recall.purge_recall_by_type(path, CASO) == 1
    bank = recall.load_recall_bank(path)
    assert [t.kind for t in bank.templates] == [ESERCIZIO]
    assert all(q.status == RecallQuestionStatus.PENDING for q in bank.questions)
