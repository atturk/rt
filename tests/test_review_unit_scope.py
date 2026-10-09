from rt.pipeline.review import load_science_issues, run_review, run_review_unit, save_science_issues
from tests.test_jev_prefilter import setup_mock_lesson


def test_refresh_one_unit_preserves_other_unit_issues(tmp_path):
    lesson = setup_mock_lesson(tmp_path, num_units=2)
    run_review(lesson, force=True, force_mock=True)
    before = load_science_issues(lesson)
    saved_other = before[0].model_copy(update={"id": "sci_999999", "unit_id": "1.2"})
    save_science_issues(before + [saved_other], lesson)
    others = [saved_other]
    assert others
    result = run_review_unit(lesson, "1.1", force_mock=True)
    after = load_science_issues(lesson)
    assert result["other_issues_preserved"] >= 1
    assert all(any(issue.id == old.id and issue.claim == old.claim for issue in after) for old in others)




def test_reviewing_one_rewritten_unit_leaves_other_rewritten_units_to_review(tmp_path):
    """Riscrivo 1.1 e 1.2, rivedo solo 1.1: la 1.2 non deve risultare già revisionata."""
    from rt.core.idempotency import get_phase_checkpoint
    from rt.core.manifest import init_or_update_manifest
    from rt.pipeline.rewrite import load_draft, save_draft
    lesson = setup_mock_lesson(tmp_path, num_units=3)
    init_or_update_manifest(lesson, "lezione", "2026-09-28", "BIOCHIMICA", "draft_ready")
    run_review(lesson, force=True, force_mock=True)
    draft = load_draft(lesson)
    for unit in draft.units[:2]:
        unit.content += " Testo riscritto dopo la revisione."
    save_draft(draft, lesson)

    run_review_unit(lesson, "1.1", force_mock=True)
    checkpoint, _, _ = get_phase_checkpoint(lesson, "review")
    assert sorted(checkpoint["completed_items"]) == ["1.1", "1.3"]

    result = run_review(lesson, force_mock=True)  # riprende: rivede solo la 1.2
    assert result["status"] == "review_completed" and result["completed_units"] == 3


def test_rereviewing_a_unit_keeps_decisions_on_issues_found_again(tmp_path):
    """Decido una issue, rivedo la sua unità: la issue ritrovata tiene id e decisione,
    quella che la nuova revisione non trova più viene segnalata invece di sparire in silenzio."""
    from rt.pipeline.ledger import load_ledger, record_decision
    lesson = setup_mock_lesson(tmp_path, num_units=2)
    run_review(lesson, force=True, force_mock=True)
    issues = [issue for issue in load_science_issues(lesson) if issue.unit_id == "1.1"]
    assert issues
    found_again = issues[0]
    vanished = issues[0].model_copy(update={"id": "sci_900000", "claim": "Affermazione che la revisione non ritrova."})
    save_science_issues(load_science_issues(lesson) + [vanished], lesson)
    record_decision(lesson, found_again.id, "rejected", actor="test")
    record_decision(lesson, vanished.id, "accepted", resolved_text="x", actor="test")

    result = run_review_unit(lesson, "1.1", force_mock=True)

    after = {issue.id: issue for issue in load_science_issues(lesson)}
    assert after[found_again.id].claim == found_again.claim
    assert found_again.id in {decision.issue_id for decision in load_ledger(lesson).decisions}
    assert result["orphaned_decisions"] == [vanished.id]


    assert vanished.id not in {decision.issue_id for decision in load_ledger(lesson).decisions}
