"""V2b: parallelismo, checkpoint nel coordinatore e annullamento cooperativo."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from rt.core.config import RTConfig
from rt.core.idempotency import get_phase_checkpoint
from rt.pipeline import review
from rt.pipeline.rewrite import load_draft, save_draft
from rt.pipeline.review_units import load_review_units
from rt.services.context import RunContext, RunCancelled
from rt.services.events import ListReporter, ReviewUnitDone
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from tests.test_review_anchor_application import issue
from rt.pipeline.anchors import make_anchor


def setup_six(tmp_path, monkeypatch, parallel=4):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    draft = load_draft(lesson)
    draft.units = [draft.units[i % 3].model_copy(update={'unit_id': f'1.{i+1}', 'content': f'Passaggio {i+1} errato.'}) for i in range(6)]
    save_draft(draft, lesson)
    cfg = RTConfig(review={'parallel_units': parallel})
    monkeypatch.setattr(review, 'load_config', lambda: cfg)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    monkeypatch.setattr('rt.services.unit_relevance.refresh', lambda *a, **kw: None)
    monkeypatch.setattr('rt.services.unit_relevance.included_ids', lambda path, units: {u.unit_id for u in units})
    return lesson, cfg


def finding(client, unit, *args, **kwargs):
    return [issue('model', unit.unit_id, make_anchor(unit.content, 0, len(unit.content)))]


def test_four_workers_equal_one_and_checkpoint_on_main_thread(tmp_path, monkeypatch):
    lesson, cfg = setup_six(tmp_path, monkeypatch, 1)
    monkeypatch.setattr(review, '_validated_review_issues', finding)
    review.run_review(lesson, force_mock=True, force=True)
    def findings():
        return sorted((i.unit_id, i.claim, i.type, i.anchor.model_dump_json()) for i in review.load_science_issues(lesson))
    serial = findings()
    serial_registry = {uid: (r['text_hash'], r['issues'], r['result']) for uid, r in load_review_units(lesson).items()}
    cfg.review.parallel_units = 4
    barrier = threading.Barrier(4)
    active, maximum = 0, 0
    lock = threading.Lock()
    def parallel_critic(client, unit, *args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        if unit.unit_id in {'1.1', '1.2', '1.3', '1.4'}:
            barrier.wait(timeout=10)
        result = finding(client, unit)
        with lock:
            active -= 1
        return result
    main = threading.get_ident()
    checkpoint = review.record_phase_checkpoint
    def checked_checkpoint(*args, **kwargs):
        assert threading.get_ident() == main
        return checkpoint(*args, **kwargs)
    monkeypatch.setattr(review, '_validated_review_issues', parallel_critic)
    monkeypatch.setattr(review, 'record_phase_checkpoint', checked_checkpoint)
    reporter = ListReporter()
    ctx = RunContext(reporter=reporter)
    review.run_review(lesson, force_mock=True, force=True, ctx=ctx)
    assert maximum == 4
    assert findings() == serial
    assert {uid: (r['text_hash'], r['issues'], r['result']) for uid, r in load_review_units(lesson).items()} == serial_registry
    done = reporter.of_type(ReviewUnitDone)
    assert {e.unit_id for e in done} == {f'1.{i}' for i in range(1, 7)}
    assert len(done) == 6 and all(e.issues == 1 for e in done)
    assert len(get_phase_checkpoint(lesson, 'review')[0]['completed_items']) == 6


def test_cancel_stops_submission_and_saves_started_units(tmp_path, monkeypatch):
    lesson, _ = setup_six(tmp_path, monkeypatch)
    started = threading.Barrier(5)
    finish = threading.Event()
    calls = []
    def slow(client, unit, *args, **kwargs):
        calls.append(unit.unit_id)
        started.wait(timeout=10)
        assert finish.wait(timeout=10)
        return finding(client, unit)
    monkeypatch.setattr(review, '_validated_review_issues', slow)
    ctx = RunContext(reporter=ListReporter())
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(review.run_review, lesson, force_mock=True, force=True, ctx=ctx)
        started.wait(timeout=10)
        ctx.cancel_token.cancel()
        finish.set()
        with pytest.raises(RunCancelled):
            result.result(timeout=15)
    assert len(calls) == 4
    assert len(load_review_units(lesson)) == 4
    assert len(get_phase_checkpoint(lesson, 'review')[0]['completed_items']) == 4
    assert len(ctx.reporter.of_type(ReviewUnitDone)) == 4


def test_parallel_failure_limit_drains_started_units_without_submitting_more(tmp_path, monkeypatch):
    from rt.llm.errors import SchemaFailure
    from rt.services.events import CallbackReporter
    lesson, _ = setup_six(tmp_path, monkeypatch)
    draft = load_draft(lesson)
    draft.units.extend(draft.units[-1].model_copy(update={'unit_id': f'1.{i}'}) for i in [7, 8])
    save_draft(draft, lesson)
    started = threading.Barrier(4)
    failures_saved = threading.Event()
    calls, completed = [], []
    def critic(client, unit, *args, **kwargs):
        calls.append((unit.unit_id, failures_saved.is_set()))
        if unit.unit_id in {'1.1', '1.2', '1.3', '1.4'}:
            started.wait(timeout=10)
        if unit.unit_id in {'1.1', '1.2', '1.3'}:
            raise SchemaFailure('Risposta fuori schema')
        assert failures_saved.wait(timeout=10)
        return finding(client, unit)
    def emitted(event):
        if isinstance(event, ReviewUnitDone):
            completed.append(event.unit_id)
            if len(completed) == 3:
                failures_saved.set()
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    result = review.run_review(lesson, force_mock=True, force=True,
                               ctx=RunContext(reporter=CallbackReporter(emitted)))
    assert 4 <= len(calls) <= 6
    assert not any(after_limit for _, after_limit in calls)
    assert len(result['failed_units']) == 3 and result['stopped_early']
    assert completed[:3] and all(uid in {'1.1', '1.2', '1.3'} for uid in completed[:3])
    assert len(load_review_units(lesson)) == len(calls)
    assert len(get_phase_checkpoint(lesson, 'review')[0]['completed_items']) == len(calls) - 3


def test_workers_inherit_context_and_consume_mock_failure_only_once(tmp_path, monkeypatch):
    from rt.llm.client import mock_failure_once
    lesson, _ = setup_six(tmp_path, monkeypatch)
    with mock_failure_once('review'):
        result = review.run_review(lesson, force_mock=True, force=True)
    assert len(result['failed_units']) == 1
    assert result['completed_units'] == 5
    with mock_failure_once('review'):
        resumed = review.run_review(lesson, force_mock=True)
    assert resumed['failed_units'] == [] and resumed['completed_units'] == 6


def test_actual_mock_has_same_findings_with_four_or_one_worker(tmp_path, monkeypatch):
    snapshots = []
    for parallel in [1, 4]:
        lesson, _ = setup_six(tmp_path / str(parallel), monkeypatch, parallel)
        result = review.run_review(lesson, force_mock=True, force=True)
        assert result['total_science_issues'] > 0
        snapshots.append([item.model_dump() for item in review.load_science_issues(lesson)])
    assert snapshots[0] == snapshots[1]
