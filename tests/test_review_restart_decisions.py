"""4.2.3b3.1: quando la review riparte da zero (testo cambiato dopo la revisione) le issue nuove
riprendono i numeri da sci_000001 e le decisioni vecchie si attaccavano a issue diverse: il job
saltava dritto al documento e il build applicava decisioni sbagliate."""
from rt.core.idempotency import check_phase_status
from rt.pipeline.ledger import get_pending_issues, load_ledger, record_decision
from rt.pipeline.review import _drop_moved_decisions, load_science_issues, run_review
from rt.pipeline.rewrite import load_draft, save_draft
from tests.test_force_review_ledger_purge import _setup_test_lesson


def _decide_all(lesson_dir):
    _, pending = get_pending_issues(lesson_dir)
    assert pending
    for issue in pending:
        record_decision(lesson_dir, issue.id, "edited", resolved_text="TESTO INTERO SOSTITUITO")
    return pending


def test_review_restarted_from_scratch_drops_old_decisions(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    assert run_review(lesson_dir, force=True, force_mock=True)["status"] == "review_completed"
    _decide_all(lesson_dir)
    record_decision(lesson_dir, "custom_000001", "accepted", resolved_text="x")

    draft = load_draft(lesson_dir)
    draft.units[0].content += "\n\nFrase aggiunta dopo la revisione."
    save_draft(draft, lesson_dir)
    assert check_phase_status(lesson_dir, "review")[0].name in ("STALE", "INVALID")

    result = run_review(lesson_dir, force_mock=True)
    assert result["action"] == "RUN" and result["status"] == "review_completed"
    _, pending = get_pending_issues(lesson_dir)
    assert pending and len(pending) == len(load_science_issues(lesson_dir))
    ids = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    assert ids == {"custom_000001"}


def _identity(issue):
    return (issue.unit_id, issue.type, issue.segment_id, " ".join(issue.claim.split()))


def test_renumbered_issue_loses_decision_identical_keeps_it(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    run_review(lesson_dir, force=True, force_mock=True)
    issues = load_science_issues(lesson_dir)
    assert len(issues) >= 2
    _decide_all(lesson_dir)
    before = {i.id: _identity(i) for i in issues}
    # senza spostamenti tutte le decisioni restano
    _drop_moved_decisions(lesson_dir, before, issues)
    assert {d.issue_id for d in load_ledger(lesson_dir).decisions} == set(before)
    # la prima issue sparisce e le altre scalano di un numero: restano solo le decisioni il cui
    # id indica ancora la stessa issue
    shifted = [i.model_copy(update={"id": f"sci_{n:06d}"}) for n, i in enumerate(issues[1:], start=1)]
    _drop_moved_decisions(lesson_dir, before, shifted)
    expected = {i.id for i in shifted if before.get(i.id) == _identity(i)}
    assert {d.issue_id for d in load_ledger(lesson_dir).decisions} == expected
    assert len(expected) < len(issues)
