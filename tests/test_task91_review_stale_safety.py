"""
Test per Task 91: sicurezza rigenerazione review STALE e flag --no-regenerate.
"""
import os
import pytest
from unittest.mock import patch
from rt.cli import main
from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
from rt.pipeline.review import save_science_issues, load_science_issues
from rt.core.idempotency import PhaseStatus


def _setup_lesson_with_issues(lesson_dir: str, num_issues: int = 2):
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: TEST\ndata: '2026-03-14'\n")
    issues = [
        ScienceIssue(
            id=f"sci_{i}",
            type=ScienceType.ERR_CONCETTUALE,
            severity=ScienceSeverity.MEDIUM,
            unit_id=f"u_{i}",
            claim=f"claim {i}",
            reason=f"reason {i}",
            suggested_fix=f"fix {i}",
            status="pending",
        )
        for i in range(num_issues)
    ]
    save_science_issues(issues, lesson_dir)
    return issues


def test_review_stale_with_existing_issues_needs_yes(tmp_path, capsys):
    lesson_dir = str(tmp_path / "lesson")
    _setup_lesson_with_issues(lesson_dir, 3)

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.STALE, "stale")), \
         patch("rt.cli.run_review") as mock_run_review:
        with pytest.raises(SystemExit) as exc:
            main(["review", lesson_dir, "--mock"])
    assert exc.value.code == 1
    assert "--yes" in capsys.readouterr().err
    mock_run_review.assert_not_called()
    assert len(load_science_issues(lesson_dir)) == 3  # niente sovrascritto


def test_review_stale_with_yes_regenerates(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_lesson_with_issues(lesson_dir, 2)

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.STALE, "stale")), \
         patch("rt.cli.run_review", return_value={"action": "RUN"}) as mock_run_review, \
         patch("rt.cli._print_pending_issues") as mock_pending:
        main(["review", lesson_dir, "--mock", "--yes"])
    mock_run_review.assert_called_once()
    mock_pending.assert_called_once()


def test_review_missing_runs_and_points_to_the_web(tmp_path, capsys):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir)

    def fake_review(lesson_dir, **_kw):
        _setup_lesson_with_issues(lesson_dir, 2)
        return {"action": "RUN"}

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.MISSING, "missing")), \
         patch("rt.cli.run_review", side_effect=fake_review):
        main(["review", lesson_dir, "--mock"])
    out = capsys.readouterr().out
    assert "nella web" in out and "Da decidere: 2." in out
