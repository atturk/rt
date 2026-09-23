"""
Test per Task 91: sicurezza rigenerazione review STALE e flag --no-regenerate.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock
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


def test_review_no_regenerate_skips_run_review_and_provider_check(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_lesson_with_issues(lesson_dir)

    with patch("rt.cli._ensure_config_ready") as mock_cfg_ready, \
         patch("rt.cli.run_review") as mock_run_review, \
         patch("rt.cli.run_interactive_review") as mock_interactive:

        main(["review", lesson_dir, "--no-regenerate"])

        mock_cfg_ready.assert_not_called()
        mock_run_review.assert_not_called()
        mock_interactive.assert_called_once()
        args, kwargs = mock_interactive.call_args
        assert args[0] == lesson_dir
        assert args[1] == "science"


def test_review_stale_with_existing_issues_prompt_rejected(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    issues = _setup_lesson_with_issues(lesson_dir, 3)

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.STALE, "stale")):
        with patch("sys.stdin.isatty", return_value=True):
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = False
            with patch("questionary.confirm", return_value=mock_confirm) as mock_q_confirm, \
                 patch("rt.cli.run_review") as mock_run_review, \
                 patch("rt.cli.run_interactive_review") as mock_interactive:

                main(["review", lesson_dir, "--mock"])

                mock_q_confirm.assert_called_once()
                mock_run_review.assert_not_called()
                mock_interactive.assert_not_called()

                # Verify science_issues.json was not wiped
                saved = load_science_issues(lesson_dir)
                assert len(saved) == 3


def test_review_stale_with_existing_issues_prompt_accepted(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_lesson_with_issues(lesson_dir, 2)

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.STALE, "stale")):
        with patch("sys.stdin.isatty", return_value=True):
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = True
            with patch("questionary.confirm", return_value=mock_confirm) as mock_q_confirm, \
                 patch("rt.cli.run_review", return_value={"total_science_issues": 1, "status": "review_completed"}) as mock_run_review, \
                 patch("rt.cli.run_interactive_review") as mock_interactive:

                main(["review", lesson_dir, "--mock"])

                mock_q_confirm.assert_called_once()
                mock_run_review.assert_called_once()
                mock_interactive.assert_called_once()


def test_review_missing_does_not_prompt_and_runs_review(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: TEST\ndata: '2026-03-14'\n")

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.MISSING, "missing")):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("questionary.confirm") as mock_q_confirm, \
                 patch("rt.cli.run_review", return_value={"total_science_issues": 0, "status": "review_completed"}) as mock_run_review, \
                 patch("rt.cli.run_interactive_review") as mock_interactive:

                main(["review", lesson_dir, "--mock"])

                mock_q_confirm.assert_not_called()
                mock_run_review.assert_called_once()
                mock_interactive.assert_called_once()


def test_review_stale_non_interactive_proceeds_without_prompt(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_lesson_with_issues(lesson_dir, 2)

    with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.STALE, "stale")):
        with patch("sys.stdin.isatty", return_value=False):
            with patch("questionary.confirm") as mock_q_confirm, \
                 patch("rt.cli.run_review", return_value={"total_science_issues": 2, "status": "review_completed"}) as mock_run_review, \
                 patch("rt.cli.run_interactive_review") as mock_interactive:

                main(["review", lesson_dir, "--mock"])

                mock_q_confirm.assert_not_called()
                mock_run_review.assert_called_once()
                mock_interactive.assert_called_once()
