"""
tests/test_review_service.py
RT4-A5: review delle issue come servizio unico (rt.services.review_service).
"""
import json
import os
import subprocess
import sys

import pytest

from rt.pipeline.ledger import load_ledger
from rt.services import review_service as rs
from tests.golden_support import PROJECT_ROOT
from tests.test_integration import temp_lesson_dir  # noqa: F401  (fixture)


@pytest.fixture
def reviewed_lesson(temp_lesson_dir):
    from rt.pipeline.outline import run_outline
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.review import run_review
    from rt.pipeline.rewrite import run_rewrite
    run_prepare(temp_lesson_dir)
    run_outline(temp_lesson_dir, force_mock=True)
    run_rewrite(temp_lesson_dir, force_mock=True)
    run_review(temp_lesson_dir, force_mock=True)
    return temp_lesson_dir


def test_pending_issues_with_context_are_serializable(reviewed_lesson):
    pending = rs.list_pending_issues(reviewed_lesson)
    assert pending
    json.dumps(pending)
    assert pending[0]["context"]["unit_info"].startswith("1.1")
    assert not rs.is_review_complete(reviewed_lesson)


def test_record_and_undo_keep_channel_and_actor(reviewed_lesson):
    issue_id = rs.list_pending_issues(reviewed_lesson, with_context=False)[0]["issue"]["id"]
    rs.record_review_decision(reviewed_lesson, issue_id, "rejected", "originale", channel="telegram", actor="42")
    (dec,) = load_ledger(reviewed_lesson).decisions
    assert (dec.channel, dec.actor, dec.resolved_by) == ("telegram", "42", "user")

    with pytest.raises(rs.ReviewDecisionError) as exc:
        rs.undo_last_decision(reviewed_lesson, issue_id, only_channel="web")
    assert exc.value.reason == "not_allowed"
    assert rs.undo_last_decision(reviewed_lesson, issue_id).issue_id == issue_id
    assert load_ledger(reviewed_lesson).decisions == []


def test_legacy_decisions_keep_the_historic_format(reviewed_lesson):
    from rt.pipeline.ledger import get_ledger_path, record_decision
    record_decision(reviewed_lesson, "sci_000001", "accepted", resolved_text="x")
    with open(get_ledger_path(reviewed_lesson), encoding="utf-8") as f:
        data = json.load(f)
    assert "channel" not in data["decisions"][0] and "actor" not in data["decisions"][0]


def test_validate_rejects_duplicates_and_unknown_issues(reviewed_lesson):
    issue_id = rs.list_pending_issues(reviewed_lesson, with_context=False)[0]["issue"]["id"]
    rs.record_review_decision(reviewed_lesson, issue_id, "rejected", channel="api", validate=True)
    with pytest.raises(rs.ReviewDecisionError, match="già una decisione"):
        rs.record_review_decision(reviewed_lesson, issue_id, "rejected", channel="api", validate=True)
    with pytest.raises(rs.ReviewDecisionError, match="non esiste più"):
        rs.record_review_decision(reviewed_lesson, "sci_999999", "rejected", channel="api", validate=True)
    with pytest.raises(ValueError):
        rs.record_review_decision(reviewed_lesson, issue_id, "rejected", channel="fax")


def test_auto_accept_completes_review(reviewed_lesson):
    accepted, remaining = rs.auto_accept_pending(reviewed_lesson, "all", channel="cli")
    assert accepted and not remaining
    assert rs.is_review_complete(reviewed_lesson)
    assert {d.actor for d in load_ledger(reviewed_lesson).decisions} == {"auto_accept"}


_WORKER = """
import sys
from rt.services.review_service import record_review_decision
lesson_dir, prefix, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
for i in range(n):
    record_review_decision(lesson_dir, f"{prefix}_{i:03d}", "accepted", "x", channel="cli")
"""


def test_concurrent_decisions_from_two_processes_are_not_lost(tmp_path):
    lesson_dir = str(tmp_path / "lezione")
    os.makedirs(lesson_dir)
    n = 25
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    procs = [
        subprocess.Popen([sys.executable, "-c", _WORKER, lesson_dir, prefix, str(n)], env=env)
        for prefix in ("a", "b")
    ]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    ids = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    assert len(ids) == 2 * n
