"""Contratto variabile, contesto, adattamento score e checkpoint del recall."""
import json
import threading
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from rt.core.config import RTConfig, JevConfig
from rt.core.lesson_paths import lesson_path
from rt.core.models import RecallQuestionType, RecallQuizGenerationResult, RecallMirataGenerationResult, RecallVastaGenerationResult
from rt.llm.jev_client import JevResponse, JevScoreAnswer
from rt.pipeline import recall
from rt.pipeline.rewrite import load_draft
from rt.services import unit_relevance as gate
from rt.services.recall_context import lesson_context
from tests.test_jev_prefilter import setup_mock_lesson


def score_response(level, confidence=.99, probabilities=None):
    return JevResponse(model="typesafe/jev-1.13", answers={"rilevanza": JevScoreAnswer(
        score=level, confidence=confidence, probabilities=probabilities if probabilities is not None else {str(i): float(i == level) for i in range(3)})})


def test_context_handles_yaml_list_and_fallback(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    with open(lesson_path(path, 'outline.json'), 'w') as stream:
        json.dump({'lesson_title': 'Cuore', 'generated_topics': ['Fallback']}, stream)
    with open(lesson_path(path, 'info.yaml'), 'w') as stream:
        stream.write('materia: Anatomia\nargomenti:\n - Cuore\n - Vasi\n - Cuore\n')
    assert lesson_context(path) == {'materia': 'Anatomia', 'titolo_lezione': 'Cuore', 'argomenti_lezione': ['Cuore', 'Vasi']}
    with open(lesson_path(path, 'info.yaml'), 'w') as stream:
        stream.write('materia: Anatomia\n')
    assert lesson_context(path)['argomenti_lezione'] == ['Fallback']


@pytest.mark.parametrize('level', [0, 1, 2])
def test_score_levels_are_guidance_and_never_exclude(tmp_path, level):
    path = setup_mock_lesson(tmp_path, num_units=1)
    cfg = RTConfig(jev=JevConfig(relevance_mode='active', relevance_model='typesafe/jev-1.13'))
    with patch.object(gate, 'load_config', return_value=cfg), patch('rt.llm.jev_client.call_jev', return_value=score_response(level)):
        gate.refresh(path, view='resolved')
        unit = load_draft(path).units[0]
        assert gate.included(path, unit, view='resolved')
        assert gate.recall_assessment(path, unit)['level'] == level
        with open(lesson_path(path, 'info.yaml'), 'w') as stream:
            stream.write('materia: Contesto diverso\n')
        assert gate.recall_assessment(path, unit)['level'] is None


@pytest.mark.parametrize('score,confidence,probabilities', [
    (0, .3, {'0': 1., '1': 0., '2': 0.}),
    (1, .99, {'0': .5, '1': .5, '2': 0.}),
    (1, .99, {'0': .1, '1': .7, '2': .2}),
    (1, .99, {'0': .1, '1': .9}),
    (1, .99, {'0': .2, '1': .9, '2': .1}),
])
def test_uncertainty_does_not_become_zero(tmp_path, score, confidence, probabilities):
    path = setup_mock_lesson(tmp_path, num_units=1)
    cfg = RTConfig(jev=JevConfig(relevance_mode='active', relevance_model='typesafe/jev-1.13'))
    with patch.object(gate, 'load_config', return_value=cfg), patch('rt.llm.jev_client.call_jev', return_value=score_response(score, confidence, probabilities)):
        gate.refresh(path, view='resolved')
        assert gate.recall_assessment(path, load_draft(path).units[0])['level'] is None


def test_identical_views_reuse_classification_and_shadow_is_neutral(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    cfg = RTConfig(jev=JevConfig(relevance_mode='shadow', relevance_model='typesafe/jev-1.13'))
    with patch.object(gate, 'load_config', return_value=cfg), patch('rt.llm.jev_client.call_jev', return_value=score_response(2)) as called:
        gate.refresh(path)
        gate.refresh(path, view='resolved')
        assert called.call_count == 1
        assert gate.recall_assessment(path, load_draft(path).units[0])['level'] is None


def test_prompt_suffix_and_fewshot_remain_intact():
    from rt.llm.prompts import build_recall_quiz_user_prompt, contextualize_recall_prompt, RICHNESS_GUIDANCE
    prompt = build_recall_quiz_user_prompt('2.1', 'Definizione', 'Una nozione breve.', [
        {'question_text': 'Esempio buono', 'vote': 'up'}, {'question_text': 'Esempio cattivo', 'vote': 'down'},
        {'question_text': 'Esempio banale', 'vote': 'lightning'}])
    context = {'materia': 'Anatomia', 'argomenti_lezione': ['Cuore']}
    low = contextualize_recall_prompt(prompt, context, {'level': 0}, [])
    high = contextualize_recall_prompt(prompt, context, {'level': 2}, [])
    assert low.split('VALUTAZIONE CLASSIFICATORE:')[0] == high.split('VALUTAZIONE CLASSIFICATORE:')[0]
    assert low.endswith(RICHNESS_GUIDANCE[0]) and high.endswith(RICHNESS_GUIDANCE[2])
    assert all(s in high for s in ['Esempio buono', 'Esempio cattivo', 'Esempio banale', 'Una nozione breve.'])
    assert high.index('Esempio buono') < high.index('CONTESTO DISCIPLINARE') < high.index('CONTENUTO:')


@pytest.mark.parametrize('model', [RecallQuizGenerationResult, RecallMirataGenerationResult, RecallVastaGenerationResult])
def test_empty_is_valid_but_missing_or_safe_is_invalid(model):
    assert model.model_validate({'questions': []}).questions == []
    with pytest.raises(ValidationError):
        model.model_validate({})
    for raw in ['safe', '"safe"', '{"status":"safe"}']:
        with pytest.raises(ValidationError):
            model.model_validate_json(raw)


@pytest.mark.parametrize('change', [{'options': ['A', 'A', 'B', 'C']}, {'correct_index': 4}, {'correct_index': True},
    {'options': ['A'*101, 'B', 'C', 'D']}, {'question_text': ' '}, {'pregenerated_material': None}, {'type': 'mirata'}])
def test_invalid_quiz_rejected(change):
    data = {'type': 'quiz', 'question_text': 'Domanda?', 'options': ['A', 'B', 'C', 'D'], 'correct_index': 0, 'pregenerated_material': 'Spiegazione'}
    with pytest.raises(ValidationError):
        RecallQuizGenerationResult.model_validate({'questions': [{**data, **change}]})


def test_empty_remembered_until_context_changes_or_explicit_regeneration(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    with patch('rt.llm.client.LLMClient.call_structured', side_effect=lambda **kw: kw['response_model'](questions=[])) as called:
        assert recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 5, []) == []
        assert recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 5, []) == []
        assert called.call_count == 1 and not recall.generation_available(path, RecallQuestionType.MIRATA)
        recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 5, [], regenerate=True)
        assert called.call_count == 2
        with open(lesson_path(path, 'info.yaml'), 'w') as stream:
            stream.write('materia: Nuova materia\n')
        assert recall.generation_available(path, RecallQuestionType.MIRATA)


def test_multiple_questions_unique_ids_deduplicate_and_keep_answers(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    def generate(**kw):
        return kw['response_model'].model_validate({'questions': [{'type': 'mirata', 'question_text': t} for t in ['Prima?', 'Seconda?', 'Prima?']]})
    with patch('rt.llm.client.LLMClient.call_structured', side_effect=generate):
        result = recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 1, [])
    assert [q.id for q in result] == ['recall_000001', 'recall_000002']
    recall.record_recall_answer(path, result[1].id, 'Risposta')
    bank = recall.load_recall_bank(path)
    assert bank.answers[0].question_id == result[1].id
    assert len(bank.questions) == 2 and all(q.generation_version for q in bank.questions)


def test_override_applies_to_both_identical_views_and_can_be_reset(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    cfg = RTConfig(jev=JevConfig(relevance_mode='active', relevance_model='typesafe/jev-1.13'))
    with patch.object(gate, 'load_config', return_value=cfg), patch('rt.llm.jev_client.call_jev', return_value=score_response(0)):
        gate.refresh(path)
        gate.refresh(path, view='resolved')
        unit = load_draft(path).units[0]
        gate.set_override(path, unit.unit_id, 'no_content')
        assert not gate.included(path, unit, view='resolved')
        gate.set_override(path, unit.unit_id, None)
        assert gate.included(path, unit, view='resolved')


def test_completed_unit_checkpoint_survives_later_failure(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=2)
    response = RecallMirataGenerationResult.model_validate({'questions': [{'type': 'mirata', 'question_text': 'Primo concetto?'}]})
    with patch('rt.llm.client.LLMClient.call_structured', side_effect=[response, RuntimeError('Job interrotto')]):
        with pytest.raises(RuntimeError, match='Job interrotto'):
            recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 10, [])
    bank = recall.load_recall_bank(path)
    assert len(bank.questions) == 1
    assert bank.generation_attempts['mirata:1.1']['question_ids'] == [bank.questions[0].id]


def test_concurrent_generations_deduplicate_and_remember_exhaustion(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    barrier = threading.Barrier(2)
    errors = []
    def generate(**kw):
        barrier.wait(timeout=5)
        return kw['response_model'].model_validate({'questions': [{'type': 'mirata', 'question_text': 'Stesso concetto?'}]})
    def worker():
        try:
            recall.generate_recall_batch(path, RecallQuestionType.MIRATA, 1, [])
        except Exception as exc:
            errors.append(exc)
    with patch('rt.llm.client.LLMClient.call_structured', side_effect=generate):
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
    assert not errors
    bank = recall.load_recall_bank(path)
    assert len(bank.questions) == 1 and bank.questions[0].id == 'recall_000001'
    assert bank.generation_attempts['mirata:1.1']['exhausted']
    assert not recall.generation_available(path, RecallQuestionType.MIRATA)
