"""Test della verifica manuale delle unità/parti in parallelo (review_unit_job e review_part_job)."""
import threading
import time
from types import SimpleNamespace

import pytest

from rt.core.models import ScienceIssue, ScienceSeverity, ScienceType
from rt.pipeline import review as review_mod
from rt.pipeline.anchors import make_anchor
from rt.pipeline.rewrite import load_draft
from rt.services.api_jobs import review_part_job, review_unit_job
from rt.services.context import CancelToken, RunCancelled, RunContext
from rt.services.events import ListReporter, ReviewUnitDone, ReviewUnitStarted
from tests.test_jev_prefilter import setup_mock_lesson


def _set_parallel(monkeypatch, parallel: int) -> None:
    from rt.core import config as config_mod
    real_load = config_mod.load_config

    def patched(*args, **kwargs):
        cfg = real_load(*args, **kwargs)
        cfg.review.parallel_units = parallel
        return cfg

    monkeypatch.setattr(config_mod, "load_config", patched)


def test_review_unit_job_runs_in_parallel_and_preserves_order_and_ledger(tmp_path, monkeypatch):
    lesson = setup_mock_lesson(tmp_path, num_units=6)
    units = [u.unit_id for u in load_draft(lesson).units]
    assert len(units) == 6
    _set_parallel(monkeypatch, 3)

    lock = threading.Lock()
    active = 0
    max_active = 0
    spans = {}

    def fake_review_unit(client, unit, idx, total_units, seg_by_id, st_issues_by_unit,
                         all_science_issues, _cfg, lesson_dir, asr_llm, shadow_jev, **kwargs):
        nonlocal active, max_active
        start = time.monotonic()
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.15)
            all_science_issues.append(ScienceIssue(
                id="sci_000000",
                unit_id=unit.unit_id,
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.LOW,
                claim=unit.content[:20],
                reason=f"Issue per {unit.unit_id}",
                suggested_fix="Correzione",
                unanchored=True,
            ))
            return "issues"
        finally:
            with lock:
                active -= 1
                spans[unit.unit_id] = (start, time.monotonic())

    monkeypatch.setattr(review_mod, "_review_unit", fake_review_unit)

    reporter = ListReporter()
    ctx = RunContext(lesson_dir=lesson, reporter=reporter)
    job = SimpleNamespace(
        id="job-par-units",
        type="review_unit",
        lesson_path=lesson,
        payload={"units": units, "options": {"mock": True, "force": True}},
    )
    outcome = review_unit_job(job, ctx)

    assert outcome.state.value == "succeeded"
    assert [row["unit"] for row in outcome.result["units"]] == units
    assert max_active >= 2 and max_active <= 3
    started_events = reporter.of_type(ReviewUnitStarted)
    assert any(len(e.running_units) >= 2 for e in started_events)
    assert len(reporter.of_type(ReviewUnitDone)) == 6

    saved_issues = review_mod.load_science_issues(lesson)
    assert {iss.unit_id for iss in saved_issues} == set(units)


def test_review_part_job_runs_in_parallel_and_preserves_order(tmp_path, monkeypatch):
    lesson = setup_mock_lesson(tmp_path, num_units=6)
    draft_units = load_draft(lesson).units
    parts = [
        {"unit_id": u.unit_id, "anchor": make_anchor(u.content, 0, min(20, len(u.content))).model_dump()}
        for u in draft_units
    ]
    _set_parallel(monkeypatch, 3)

    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_validated(client, unit, prompt, lesson_dir, unit_label, seg_by_id=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.15)
            return [ScienceIssue(
                id="sci_000000",
                unit_id=unit.unit_id,
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.LOW,
                claim=unit.content[:15],
                reason=f"Parte {unit.unit_id}",
                suggested_fix="Fix",
            )]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(review_mod, "_validated_review_issues", fake_validated)

    reporter = ListReporter()
    ctx = RunContext(lesson_dir=lesson, reporter=reporter)
    job = SimpleNamespace(
        id="job-par-parts",
        type="review_part",
        lesson_path=lesson,
        payload={"parts": parts, "options": {"mock": True}},
    )
    outcome = review_part_job(job, ctx)

    assert outcome.state.value == "succeeded"
    assert [row["unit_id"] for row in outcome.result["units"]] == [u.unit_id for u in draft_units]
    assert max_active >= 2 and max_active <= 3
    assert {iss.unit_id for iss in review_mod.load_science_issues(lesson)} == {u.unit_id for u in draft_units}


def test_review_unit_job_cancellation_stops_new_units(tmp_path, monkeypatch):
    lesson = setup_mock_lesson(tmp_path, num_units=6)
    units = [u.unit_id for u in load_draft(lesson).units]
    _set_parallel(monkeypatch, 2)

    token = CancelToken()
    called = []
    called_lock = threading.Lock()

    def slow_unit(lesson_dir, unit_id, **kwargs):
        with called_lock:
            called.append(unit_id)
        time.sleep(0.12)
        token.cancel()
        return {"unit": unit_id, "issues": 0}

    monkeypatch.setattr(review_mod, "run_review_unit", slow_unit)

    ctx = RunContext(lesson_dir=lesson, reporter=ListReporter(), cancel_token=token)
    job = SimpleNamespace(
        id="job-cancel",
        type="review_unit",
        lesson_path=lesson,
        payload={"units": units, "options": {"mock": True}},
    )
    with pytest.raises(RunCancelled):
        review_unit_job(job, ctx)

    assert len(called) <= 2
