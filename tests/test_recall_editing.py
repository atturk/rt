"""Modifica a mano delle domande (4.2.2b3): testo e alternative, stato posta/da porre,
ripescaggio delle domande già poste e rigenerazione del solo commento dell'IA."""
import pytest

from rt.core.models import RecallQuestionStatus, RecallQuestionType
from rt.pipeline import recall
from rt.services import recall_editing as editing
from rt.services import recall_service as service
from rt.services.errors import Conflict, NotFound
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = _synthetic_lesson(root)
    from rt.services.lesson_service import ensure_indexed
    ensure_indexed([path])
    service.generate_pool(path, force_mock=True, qtypes=['quiz', 'mirata'])
    return path


def _first(lesson, qtype):
    return next(q for q in recall.load_recall_bank(lesson).questions if q.type == qtype)


def test_edit_quiz_rewrites_it_and_puts_it_back_among_the_pending(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    recall.get_next_pending_question(lesson, RecallQuestionType.QUIZ)  # la prima diventa 'posta'
    service.answer_quiz(lesson, quiz.id, 0)
    assert service.find_question(lesson, quiz.id).status == RecallQuestionStatus.ANSWERED

    edited = editing.edit_question(lesson, quiz.id, question_text='Quale misura è ammessa sui nominali?',
                                   options=['Moda', 'Mediana', 'Media', 'Varianza'], correct_index=0,
                                   explanation='Sui nominali si può solo contare.')
    assert edited.question_text == 'Quale misura è ammessa sui nominali?'
    assert edited.correct_index == 0 and edited.options[1] == 'Mediana'
    assert edited.status == RecallQuestionStatus.PENDING
    # la risposta già data resta nello storico
    assert [a.question_id for a in recall.load_recall_bank(lesson).answers] == [quiz.id]


def test_edit_refuses_what_the_model_would_refuse(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    with pytest.raises(ValueError):
        editing.edit_question(lesson, quiz.id, question_text='Domanda', options=['A', 'B'], correct_index=0,
                              explanation='Spiegazione')
    with pytest.raises(ValueError):  # quiz senza spiegazione
        editing.edit_question(lesson, quiz.id, question_text='Domanda', options=['A', 'B', 'C', 'D'],
                              correct_index=0, explanation='')
    mirata = _first(lesson, RecallQuestionType.MIRATA)
    # Su una mirata opzioni e commento si ignorano: il modello non li prevede.
    edited = editing.edit_question(lesson, mirata.id, question_text='Spiega la differenza.',
                                   options=['A', 'B', 'C', 'D'], correct_index=1, explanation='no')
    assert edited.options is None and edited.correct_index is None and edited.pregenerated_material is None
    with pytest.raises(NotFound):
        editing.edit_question(lesson, 'recall_999999', question_text='Boh')


def test_status_marks_asked_or_pending(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    assert editing.set_question_status(lesson, quiz.id, 'asked').status == RecallQuestionStatus.ASKED
    assert service.pending_count(lesson, RecallQuestionType.QUIZ) < len(
        [q for q in recall.load_recall_bank(lesson).questions if q.type == RecallQuestionType.QUIZ])
    assert editing.set_question_status(lesson, quiz.id, 'pending').status == RecallQuestionStatus.PENDING
    with pytest.raises(ValueError):
        editing.set_question_status(lesson, quiz.id, 'discarded')


def test_restore_brings_back_all_the_asked_or_only_the_wrong_ones(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    other = [q for q in recall.load_recall_bank(lesson).questions if q.type == RecallQuestionType.QUIZ][1]
    wrong = 0 if quiz.correct_index != 0 else 1
    service.answer_quiz(lesson, quiz.id, wrong)  # sbagliata
    service.answer_quiz(lesson, other.id, other.correct_index)  # corretta
    assert editing.restorable(lesson) == {'asked': 2, 'wrong': 1}

    assert editing.restore_questions(lesson, 'wrong') == 1
    assert service.find_question(lesson, quiz.id).status == RecallQuestionStatus.PENDING
    assert service.find_question(lesson, other.id).status == RecallQuestionStatus.ANSWERED
    assert editing.restore_questions(lesson, 'asked') == 1
    assert service.find_question(lesson, other.id).status == RecallQuestionStatus.PENDING
    with pytest.raises(ValueError):
        editing.restore_questions(lesson, 'scartate')


def test_restore_leaves_the_discarded_ones_out(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    service.vote_question(lesson, quiz.id, 'down', reasons=['ambigua'])
    assert editing.restorable(lesson)['asked'] == 0
    assert editing.restore_questions(lesson, 'asked') == 0
    assert service.find_question(lesson, quiz.id).status == RecallQuestionStatus.DISCARDED


def test_comment_is_regenerated_only_where_the_model_has_one(lesson):
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    before = quiz.question_text
    question = editing.regenerate_comment(lesson, quiz.id, force_mock=True)
    assert question.question_text == before and question.options == quiz.options
    assert quiz.id in question.pregenerated_material
    with pytest.raises(Conflict):
        editing.regenerate_comment(lesson, _first(lesson, RecallQuestionType.MIRATA).id, force_mock=True)


def test_endpoints(api_client, lesson):
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    base = f'/api/v1/lessons/{lesson_id}/recall'
    quiz = _first(lesson, RecallQuestionType.QUIZ)

    edited = api_client.post(f'{base}/questions/{quiz.id}/edit', json={
        'question_text': 'Domanda corretta a mano?', 'options': ['Uno', 'Due', 'Tre', 'Quattro'],
        'correct_index': 2, 'explanation': 'Perché tre.'})
    assert edited.status_code == 200, edited.text
    assert edited.json()['question_text'] == 'Domanda corretta a mano?'
    assert edited.json()['correct_index'] == 2 and edited.json()['explanation'] == 'Perché tre.'

    bad = api_client.post(f'{base}/questions/{quiz.id}/edit', json={'question_text': 'Senza opzioni'})
    assert bad.status_code == 422 and bad.json()['error']['code'] == 'validation_error'

    assert api_client.post(f'{base}/questions/{quiz.id}/status', json={'status': 'asked'}).json()['status'] == 'asked'
    assert api_client.get(f'{base}/questions/restorable').json() == {'asked': 1, 'wrong': 0}
    assert api_client.post(f'{base}/questions/restore', json={'scope': 'asked'}).json() == {'restored': 1}

    accepted = api_client.post(f'{base}/questions/{quiz.id}/comment?mock=true')
    assert accepted.status_code == 202 and accepted.json()['job_id']
    mirata = _first(lesson, RecallQuestionType.MIRATA)
    refused = api_client.post(f'{base}/questions/{mirata.id}/comment?mock=true')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'comment_not_supported'
    assert api_client.post(f'{base}/questions/recall_999999/comment').status_code == 404


def test_comment_job(api_client, lesson, rt_db):
    from rt.services.api_jobs import recall_comment_job
    from rt.services.context import RunContext
    from rt.services.jobs import DbJobQueue
    from rt.services.lesson_service import lesson_id_for_dir
    quiz = _first(lesson, RecallQuestionType.QUIZ)
    accepted = api_client.post(f'/api/v1/lessons/{lesson_id_for_dir(lesson)}/recall/questions/{quiz.id}/comment?mock=true')
    job = DbJobQueue(rt_db).get(accepted.json()['job_id'])
    result = recall_comment_job(job, RunContext()).result['question']
    assert result['id'] == quiz.id and quiz.id in result['explanation']
    assert result['question_text'] == quiz.question_text
