"""V6: registro della verifica, anche quando non sono state trovate issue."""
import json
import pytest
from rt.core.lesson_paths import lesson_path
from rt.pipeline import review
from rt.pipeline.rewrite import load_draft, save_draft
from tests.test_review_stable_ids import reviewed  # noqa: F401


def test_full_and_single_review_write_registry(reviewed):
    lesson, _ = reviewed
    path = lesson_path(lesson, 'review_units.json')
    with open(path, encoding='utf8') as f:
        units = json.load(f)['units']
    assert set(units) == {'1.1','1.2','2.1'}
    assert all(entry['reviewed_at'] and entry['model'] and entry['result'] == 'issues' for entry in units.values())
    assert all(entry['issues'] == 1 and entry['text_hash'] for entry in units.values())
    previous = units['1.1']['reviewed_at']
    review.run_review_unit(lesson, '1.1', force_mock=True)
    with open(path, encoding='utf8') as f:
        assert json.load(f)['units']['1.1']['reviewed_at'] > previous


def test_review_units_states_and_legacy_checkpoint(reviewed, monkeypatch):
    from rt.services.review_service import review_units
    from rt.pipeline.review_units import load_review_units, save_review_units
    lesson, _ = reviewed
    registry = load_review_units(lesson)
    registry['1.1']['result'] = 'ok'
    registry['1.1']['issues'] = 0
    review.save_science_issues([i for i in review.load_science_issues(lesson) if i.unit_id != '1.1'], lesson)
    save_review_units(lesson, registry)
    assert [u['state'] for u in review_units(lesson)] == ['ok','issues','issues']
    draft = load_draft(lesson)
    draft.units[0].content += ' Modificato a mano.'
    save_draft(draft, lesson, manual=True)
    assert review_units(lesson)[0]['state'] == 'changed'
    registry.pop('1.2')
    registry['2.1']['result'] = 'failed'
    registry['2.1']['message'] = 'Timeout'
    save_review_units(lesson, registry)
    assert review_units(lesson)[2]['state'] == 'failed'
    # In assenza di registro, vale il checkpoint storico con impronta uguale.
    from rt.storage import fs
    fs.remove(lesson_path(lesson, 'review_units.json'))
    rows = review_units(lesson)
    assert rows[0]['state'] == 'changed' and rows[1]['state'] == 'issues'
    assert rows[1]['reviewed_at'] is None and rows[1]['model'] is None
    monkeypatch.setattr('rt.services.unit_relevance.included', lambda *a: False)
    assert all(u['state'] == 'excluded' for u in review_units(lesson))


def test_never_reviewed_units_and_api(tmp_path, monkeypatch, rt_db, api_client):
    from tests.api_support import isolated_workspace
    from tests.test_document_edit import _synthetic_lesson
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    response = api_client.get(f'/api/v1/lessons/{lesson_id}/review/units')
    assert response.status_code == 200
    rows = response.json()
    assert [u['unit_id'] for u in rows] == ['1.1','1.2','2.1']
    assert all(u['state'] == 'never' and u['issues_total'] == 0 for u in rows)


def test_empty_prefilter_and_failed_runs_leave_a_trace(reviewed, monkeypatch):
    from rt.pipeline.review_units import load_review_units
    from rt.llm.errors import TimeoutFailure
    lesson, _ = reviewed
    monkeypatch.setattr(review, '_validated_review_issues', lambda *a, **kw: [])
    review.run_review_unit(lesson, '1.1', force_mock=True)
    assert load_review_units(lesson)['1.1']['result'] == 'ok'
    monkeypatch.setattr(review, '_review_unit', lambda *a, **kw: 'skipped_by_prefilter')
    review.run_review_unit(lesson, '1.1', force_mock=True)
    assert load_review_units(lesson)['1.1']['result'] == 'skipped_by_prefilter'
    def fail(*a, **kw):
        raise TimeoutFailure('Tempo esaurito')
    monkeypatch.setattr(review, '_review_unit', fail)
    with pytest.raises(TimeoutFailure):
        review.run_review_unit(lesson, '1.1', force_mock=True)
    assert load_review_units(lesson)['1.1']['result'] == 'failed'
    assert 'Tempo esaurito' in load_review_units(lesson)['1.1']['message']
    review.run_review(lesson, force=True, force_mock=True)
    assert all(e['result'] == 'failed' for e in load_review_units(lesson).values())
