"""Bypass esplicito del prefiltro, esclusione singola e storico della verifica completa."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from rt.pipeline import review
from rt.pipeline.rewrite import load_draft, save_draft
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review_units import review_completed_once
from tests.test_review_stable_ids import reviewed as reviewed_base, decide_all  # noqa: F401
from tests.test_unit_relevance import _config


@pytest.fixture
def reviewed(rt_db, reviewed_base):
    return reviewed_base


def test_bypass_skips_only_prefilter_and_still_runs_drift(reviewed, monkeypatch):
    from rt.core.config import RTConfig, JevConfig
    lesson, _ = reviewed
    unit = load_draft(lesson).units[0]
    cfg = RTConfig(jev=JevConfig(enabled=True))
    a = Mock(return_value=SimpleNamespace(should_skip_expensive_llm=True))
    b = Mock(return_value=None)
    critic = Mock(return_value=[])
    monkeypatch.setattr(review, 'run_jev_task_a', a)
    monkeypatch.setattr(review, 'run_jev_task_b', b)
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    args = (SimpleNamespace(), unit, 1, 1, {}, {}, [], cfg, lesson, False, False)
    assert review._review_unit(*args) == 'skipped_by_prefilter'
    critic.assert_not_called()
    assert review._review_unit(*args, skip_prefilter=True) == 'ok'
    assert a.call_count == 1 and b.call_count == 2 and critic.call_count == 1


def test_single_bypass_reruns_current_text_without_losing_decisions(reviewed):
    lesson, calls = reviewed
    ids = decide_all(lesson)
    calls.clear()
    review.run_review_unit(lesson, '1.1', force_mock=True, skip_prefilter=True)
    assert calls == ['1.1']
    assert {i.unit_id: i.id for i in review.load_science_issues(lesson)} == ids
    assert {d.issue_id for d in load_ledger(lesson).decisions} == set(ids.values())


def test_excluded_unit_can_run_alone_but_stays_excluded_in_full_bypass(reviewed, monkeypatch):
    from rt.services import unit_relevance as gate
    lesson, calls = reviewed
    decide_all(lesson)
    decisions = load_ledger(lesson).decisions
    monkeypatch.setattr(gate, 'load_config', lambda: _config('active'))
    gate.set_override(lesson, '1.1', 'organizational', view='draft')
    calls.clear()
    assert review.run_review_unit(lesson, '1.1', force_mock=True, skip_prefilter=True)['status'] == 'skipped'
    assert calls == []
    review.run_review_unit(lesson, '1.1', force_mock=True, skip_prefilter=True, include_excluded=True)
    assert calls == ['1.1']
    assert gate.list_units(lesson)['units'][0]['review_included'] is False
    calls.clear()
    review.run_review(lesson, force_mock=True, skip_prefilter=True)
    assert sorted(calls) == ['1.2', '2.1']
    assert load_ledger(lesson).decisions == decisions


def test_completion_history_survives_changes_and_failed_rerun(reviewed, monkeypatch, api_client):
    lesson, _ = reviewed
    assert review_completed_once(lesson)
    draft = load_draft(lesson)
    draft.units[0].content += ' Una modifica.'
    save_draft(draft, lesson)
    from rt.llm.errors import TimeoutFailure
    def fail(*args, **kwargs):
        raise TimeoutFailure('Revisore indisponibile')
    monkeypatch.setattr(review, '_review_unit', fail)
    review.run_review(lesson, force=True, force_mock=True)
    assert review_completed_once(lesson)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    detail = api_client.get(f'/api/v1/lessons/{lid}').json()
    assert detail['phases']['review'] == 'PARTIAL'
    assert detail['review_progress']['completed_once'] is True


@pytest.mark.parametrize('payload', [
    {'type': 'run_pipeline', 'skip_prefilter': True},
    {'type': 'run_phase', 'phase': 'rewrite', 'skip_prefilter': True},
    {'type': 'run_phase', 'phase': 'review', 'include_excluded': True},
    {'type': 'run_phase', 'phase': 'review', 'units': ['1.1', '1.2'], 'include_excluded': True},
])
def test_api_rejects_bypass_outside_review_or_multiple_excluded_units(reviewed, api_client, payload):
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    response = api_client.post(f'/api/v1/lessons/{lid}/jobs', json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('single', [False, True])
def test_api_and_worker_forward_bypass_options(reviewed, monkeypatch, api_client, rt_db, single):
    from rt.services.worker import Worker
    from rt.services.jobs import DbJobQueue
    from tests.test_api_jobs import drain
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    called = Mock(return_value={'status': 'review_completed', 'unit': '1.1', 'issues': 0})
    monkeypatch.setattr(review, 'run_review_unit' if single else 'run_review', called)
    payload = {'type': 'run_phase', 'phase': 'review', 'mock': True, 'force': True, 'skip_prefilter': True}
    if single:
        payload.update(unit='1.1', include_excluded=True)
    response = api_client.post(f'/api/v1/lessons/{lid}/jobs', json=payload)
    assert response.status_code == 202, response.text
    jid = response.json()['job_id']
    queued = api_client.get(f'/api/v1/jobs/{jid}').json()
    assert queued['payload']['options']['skip_prefilter'] is True
    drain(Worker(DbJobQueue(rt_db), worker_id='test-bypass'))
    done = api_client.get(f'/api/v1/jobs/{jid}').json()
    assert done['state'] == 'succeeded', done
    assert called.call_count == 1
    assert called.call_args.kwargs['skip_prefilter'] is True
    if single:
        assert called.call_args.kwargs['include_excluded'] is True
