"""Scarto, motivi, rigenerazione e risposta Non lo so."""
import json
import pytest
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from rt.pipeline import recall
from rt.core.models import RecallQuestionStatus, RecallQuestionType
from rt.services import recall_service as service

@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = _synthetic_lesson(root)
    from rt.services.lesson_service import ensure_indexed
    ensure_indexed([path])
    service.generate_pool(path, force_mock=True, qtypes=['quiz', 'mirata'])
    return path


def test_discard_blocks_selection_skip_and_counts_and_keeps_vote(lesson):
    q = recall.load_recall_bank(lesson).questions[0]
    before = recall.get_pool_count(lesson, q.type)
    service.vote_question(lesson, q.id, 'down', reasons=['ambigua'], comment='Due scelte corrette')
    assert recall.get_pool_count(lesson, q.type) == before - 1
    service.skip_question(lesson, q.id)
    recall.record_recall_answer(lesson, q.id, 'risposta tardiva')
    bank = recall.load_recall_bank(lesson)
    assert bank.questions[0].status == RecallQuestionStatus.DISCARDED
    assert bank.answers[0].vote == 'down' and bank.answers[0].vote_reasons == ['ambigua']
    assert service.recall_overview(lesson)['questions']['quiz'].get('discarded', 0) == 0
    assert service.question_list(lesson)['questions'][0]['discard_reasons'] == ['ambigua']
    assert all(recall.get_next_pending_question(lesson, q.type).id != q.id for _ in range(before - 1))
    assert recall.get_next_pending_question(lesson, q.type) is None
    service.vote_question(lesson, q.id, 'up')
    assert service.find_question(lesson, q.id).status == RecallQuestionStatus.ANSWERED


def test_old_negative_votes_are_discarded_on_load(lesson):
    bank = recall.load_recall_bank(lesson)
    q = bank.questions[0]
    recall.record_recall_answer(lesson, q.id, '', vote='down')
    assert service.find_question(lesson, q.id).status == RecallQuestionStatus.DISCARDED


def test_fewshot_groups_and_prompt_keep_reasons(tmp_path):
    from rt.llm.prompts import build_recall_quiz_user_prompt
    root = str(tmp_path)
    for vote, text in [('up', 'Buona?'), ('down', 'Da evitare?')]:
        recall.record_fewshot_vote(RecallQuestionType.QUIZ, text, vote, state_dir=root, reasons=['ambigua'], comment='Due risposte')
    with open(recall.get_fewshot_path(root)) as f: data = json.load(f)
    assert len(data['quiz']['good']) == len(data['quiz']['avoid']) == 1
    prompt = build_recall_quiz_user_prompt('1.1', 'Titolo', 'Testo', recall.load_fewshot_examples(RecallQuestionType.QUIZ, root))
    assert prompt.index('Buona?') < prompt.index('ESEMPI DA EVITARE') < prompt.index('Da evitare?')
    assert 'ambigua' in prompt and 'Due risposte' in prompt
    recall.record_fewshot_vote(RecallQuestionType.QUIZ, 'Da evitare?', 'up', state_dir=root)
    assert not recall._load_fewshot(root)['quiz']['avoid']


def test_regeneration_job_uses_original_units_comment_and_is_idempotent(api_client, lesson, rt_db):
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.services.jobs import DbJobQueue
    q = recall.load_recall_bank(lesson).questions[0]
    url = f'/api/v1/lessons/{lesson_id_for_dir(lesson)}/recall'
    res = api_client.post(url + '/regenerate', json={'question_id': q.id, 'comment': 'Chiedi di ragionare', 'mock': True})
    assert res.status_code == 202, res.text
    queue = DbJobQueue(rt_db)
    payload = queue.get(res.json()['job_id']).payload
    assert payload['comment'] == 'Chiedi di ragionare'
    assert service.find_question(lesson, q.id).status == RecallQuestionStatus.DISCARDED
    from rt.services.api_jobs import recall_regenerate_job
    from rt.services.context import RunContext
    job = queue.get(res.json()['job_id'])
    result = recall_regenerate_job(job, RunContext()).result['question']
    assert result['unit_ids'] == q.unit_ids and result['type'] == q.type.value and result['id'] != q.id
    assert recall_regenerate_job(job, RunContext()).result['question']['id'] == result['id']
    assert api_client.post(url + '/regenerate', json={'question_id': q.id, 'comment': '  '}).status_code == 422


def test_non_lo_so_quiz_and_open_answer(api_client, lesson, rt_db):
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.services.jobs import DbJobQueue
    from rt.services.api_jobs import recall_evaluate_job
    from rt.services.context import RunContext
    qs = recall.load_recall_bank(lesson).questions
    quiz = next(q for q in qs if q.type == RecallQuestionType.QUIZ)
    mirata = next(q for q in qs if q.type == RecallQuestionType.MIRATA)
    url = f'/api/v1/lessons/{lesson_id_for_dir(lesson)}/recall/answer'
    res = api_client.post(url, json={'question_id': quiz.id, 'dont_know': True})
    assert res.status_code == 200 and res.json()['correct'] is False
    assert res.json()['question']['correct_index'] == quiz.correct_index
    res = api_client.post(url, json={'question_id': mirata.id, 'dont_know': True, 'mock': True})
    assert res.status_code == 202, res.text
    job = DbJobQueue(rt_db).get(res.json()['job_id'])
    result = recall_evaluate_job(job, RunContext()).result
    assert 'Correttezza: 0%' in result['evaluation']
    assert all(a.dont_know and a.answer_text == '[Non lo so]' for a in recall.load_recall_bank(lesson).answers)


def test_regeneration_prompt_contains_original_comment_and_resolved_units(lesson, monkeypatch):
    from rt.services.recall_regeneration import regenerate
    from rt.llm.client import LLMClient
    q = next(q for q in recall.load_recall_bank(lesson).questions if q.type == RecallQuestionType.MIRATA)
    captured = {}
    def generate(self, **kwargs):
        captured.update(kwargs)
        return kwargs['response_model'].model_validate({'type': 'mirata', 'question_text': 'Nuova domanda di ragionamento?'})
    monkeypatch.setattr(LLMClient, 'call_structured', generate)
    replacement = regenerate(lesson, q.id, 'Confronta due situazioni', job_id='prova-prompt')
    assert q.question_text in captured['prompt'] and 'Confronta due situazioni' in captured['prompt']
    assert "Testo dell'unità" in captured['prompt'] and replacement.unit_ids == q.unit_ids
