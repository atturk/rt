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
