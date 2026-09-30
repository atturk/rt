"""Pool del recall: unità selezionate (predefinite: le rilevanti), pool dell'intera lezione e
rifornimento casuale alle soglie 2 vaste / 3 mirate / 5 quiz."""
from unittest.mock import patch

from rt.core.config import JevConfig, RTConfig
from rt.core.models import RecallQuestionStatus, RecallQuestionType
from rt.pipeline import recall
from rt.services import recall_service, recall_units
from rt.services import unit_relevance as gate
from tests.test_jev_prefilter import setup_mock_lesson
from tests.test_recall_richness import score_response

SHADOW = RTConfig(jev=JevConfig(relevance_mode='shadow', relevance_model='typesafe/jev-1.13'))


def classified(tmp_path, levels):
    """Lezione con un'unità per livello, classificata col gate in ombra."""
    path = setup_mock_lesson(tmp_path, num_units=len(levels))
    with patch.object(gate, 'load_config', return_value=SHADOW), \
            patch('rt.llm.jev_client.call_jev', side_effect=[score_response(level) for level in levels]):
        gate.refresh(path, view='resolved')
    return path


def ids(rows, key='selected'):
    return [row['unit_id'] for row in rows if row[key]]


def test_default_selection_is_the_relevant_units_even_in_shadow(tmp_path):
    path = classified(tmp_path, [0, 2, 1])
    with patch.object(gate, 'load_config', return_value=SHADOW):
        rows = recall_units.unit_rows(path)
        assert ids(rows) == ['1.2', '1.3']
        assert [(r['unit_id'], r['score'], r['level']) for r in rows] == [('1.1', 0, 0), ('1.2', 2, 2), ('1.3', 1, 1)]
        gate.set_override(path, '1.3', 'organizational')
        rows = recall_units.unit_rows(path)
        assert ids(rows) == ['1.2'] and rows[2]['category'] == 'organizational'


def test_without_classifier_every_unit_is_selected(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=3)
    view = recall_units.selection_view(path)
    assert view['classifier'] == 'disabled' and view['selected'] == 3 and not view['custom']
    assert all(row['level'] is None and row['score'] is None for row in view['units'])


def test_user_selection_persists_and_new_units_start_from_default(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=3)
    rows = recall_units.set_selection(path, ['1.3', 'inesistente'])
    assert ids(rows) == ['1.3']
    bank = recall.load_recall_bank(path)
    assert bank.unit_selection == {'selected': ['1.3'], 'known': ['1.1', '1.2', '1.3']}
    bank.unit_selection['known'] = ['1.1', '1.3']  # 1.2 comparsa dopo la scelta
    recall.save_recall_bank(bank, path)
    assert ids(recall_units.unit_rows(path)) == ['1.2', '1.3']
    assert ids(recall_units.set_selection(path, None)) == ['1.1', '1.2', '1.3']
    assert recall.load_recall_bank(path).unit_selection is None


def test_pool_covers_every_selected_unit_and_replaces_only_pending(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=6)
    recall_units.set_selection(path, ['1.1', '1.2', '1.3', '1.4', '1.5'])
    first = recall_service.generate_pool(path, force_mock=True)
    bank = recall.load_recall_bank(path)
    quiz_units = {q.unit_ids[0] for q in bank.questions if q.type == RecallQuestionType.QUIZ}
    assert quiz_units == {'1.1', '1.2', '1.3', '1.4', '1.5'}  # non solo le prime unità
    assert first['quiz'] == first['mirata'] == 10 and first['vasta'] > 0
    assert all('1.6' not in q.unit_ids for q in bank.questions)

    asked = recall.get_next_pending_question(path, RecallQuestionType.QUIZ, order='sequenziale')
    recall.record_recall_answer(path, asked.id, 'A')
    highest = max(int(q.id.split('_')[1]) for q in recall.load_recall_bank(path).questions)
    recall_service.generate_pool(path, force_mock=True, qtypes=['quiz'])
    bank = recall.load_recall_bank(path)
    kept = next(q for q in bank.questions if q.id == asked.id)
    assert kept.status == RecallQuestionStatus.ANSWERED and bank.answers[0].question_id == asked.id
    new_quiz = [q for q in bank.questions if q.type == RecallQuestionType.QUIZ and q.status == RecallQuestionStatus.PENDING]
    assert new_quiz and all(int(q.id.split('_')[1]) > highest for q in new_quiz)  # ID mai riusati
    assert len({q.id for q in bank.questions}) == len(bank.questions)
    assert sum(q.type == RecallQuestionType.MIRATA for q in bank.questions) == 10  # le mirate restano


def test_failed_pool_generation_restores_the_previous_pool(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=2)
    recall_service.generate_pool(path, force_mock=True, qtypes=['quiz'])
    before = [q.id for q in recall.load_recall_bank(path).questions]
    with patch('rt.pipeline.recall.generate_recall_batch', side_effect=RuntimeError('provider giù')):
        try:
            recall_service.generate_pool(path, force_mock=True, qtypes=['quiz'])
        except RuntimeError:
            pass
    assert sorted(q.id for q in recall.load_recall_bank(path).questions) == sorted(before)


def test_pool_count_and_questions_follow_the_selection(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=3)
    recall_service.generate_pool(path, force_mock=True, qtypes=['mirata'])
    assert recall.get_pool_count(path, RecallQuestionType.MIRATA) == 6
    recall_units.set_selection(path, ['1.2'])
    assert recall.get_pool_count(path, RecallQuestionType.MIRATA) == 2
    asked = recall.get_next_pending_question(path, RecallQuestionType.MIRATA, order='casuale')
    assert asked.unit_ids == ['1.2']


def test_refill_thresholds_are_inclusive_and_refill_picks_random_selected_units(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=8)
    assert {t.value: recall_service.refill_threshold(t) for t in RecallQuestionType} == {'quiz': 5, 'mirata': 3, 'vasta': 2}
    recall_units.set_selection(path, ['1.2', '1.4', '1.6', '1.8'])
    recall_service.generate_pool(path, force_mock=True, qtypes=['vasta'])
    assert recall.get_pool_count(path, RecallQuestionType.VASTA) == 2  # 4 unità: un gruppo, due domande
    assert recall_service.is_low(path, RecallQuestionType.VASTA)

    orders = []
    real_shuffle = recall._random.shuffle
    with patch.object(recall._random, 'shuffle', side_effect=lambda items: (orders.append(1), real_shuffle(items))):
        recall_service.refill_if_low(path, RecallQuestionType.QUIZ, 3, None, force_mock=True)
    assert orders, 'il rifornimento visita le unità in ordine casuale'
    quiz = [q for q in recall.load_recall_bank(path).questions if q.type == RecallQuestionType.QUIZ]
    assert 3 <= len(quiz) and {q.unit_ids[0] for q in quiz} <= {'1.2', '1.4', '1.6', '1.8'}

    for _ in range(3):
        recall_service.refill_if_low(path, RecallQuestionType.QUIZ, 4, None, force_mock=True)
    count = recall.get_pool_count(path, RecallQuestionType.QUIZ)
    assert count > 5
    recall_service.refill_if_low(path, RecallQuestionType.QUIZ, 4, None, force_mock=True)
    assert recall.get_pool_count(path, RecallQuestionType.QUIZ) == count  # sopra soglia: niente


def test_initial_batch_generates_the_pool_only_once(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=3)
    recall_service.ensure_initial_batch(path, force_mock=True)
    total = len(recall.load_recall_bank(path).questions)
    assert total == 3 * 2 * 2 + 2  # quiz e mirate: 2 per unità; vaste: un gruppo
    recall_service.ensure_initial_batch(path, force_mock=True)
    assert len(recall.load_recall_bank(path).questions) == total


def test_cli_units_and_pool(tmp_path, capsys):
    from rt.cli import main
    path = setup_mock_lesson(tmp_path, num_units=3)
    from rt.core.idempotency import PhaseStatus
    with patch('rt.core.idempotency.check_phase_status', return_value=(PhaseStatus.VALID, '')):
        main(['recall', path, '--units', '1.2,1.3', '--pool', '--mock'])
    out = capsys.readouterr().out
    assert 'Unità per il recaller: 2 di 3 (1.2, 1.3)' in out and 'Pool rigenerato' in out
    assert {q.unit_ids[0] for q in recall.load_recall_bank(path).questions if q.type != RecallQuestionType.VASTA} == {'1.2', '1.3'}
    with patch('rt.core.idempotency.check_phase_status', return_value=(PhaseStatus.VALID, '')):
        main(['recall', path, '--units', 'rilevanti', '--pool', '--mock'])
    assert recall.load_recall_bank(path).unit_selection is None
