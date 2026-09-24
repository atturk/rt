"""
tests/test_tui_dashboard.py
Copertura per la dashboard principale (rt.tui): scansione lezioni, mapping stato→badge,
anteprima Markdown, e wiring del comando CLI bare ('rt' senza sottocomando).
"""
import json
import os
import time
from unittest.mock import patch

import pytest

from rt.core.config import RTConfig, TelegramRuntimeConfig
from rt.core.state import WorkflowState
from rt.tui.data import (
    LessonSummary,
    badge_for_state,
    discover_lessons,
    load_lesson_summary,
    load_markdown_preview,
)


def _write_lesson(lesson_dir: str, materia: str = "BIOCHIMICA", with_draft: bool = False) -> None:
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(f"data: '2026-03-14'\nmateria: {materia}\nargomenti: test\n")

    if with_draft:
        draft_data = {
            "schema_version": "1.0",
            "units": [
                {
                    "unit_id": "1.1", "title": "Unità 1",
                    "start_segment_id": "seg_000001", "end_segment_id": "seg_000001",
                    "source_segment_ids": ["seg_000001"], "content": "Contenuto di prova.",
                }
            ],
        }
        with open(os.path.join(state_dir, "draft.json"), "w", encoding="utf-8") as f:
            json.dump(draft_data, f)


class TestDiscoverLessons:
    def test_no_root_returns_empty(self):
        assert discover_lessons(None) == []
        assert discover_lessons("") == []

    def test_nonexistent_root_returns_empty(self, tmp_path):
        assert discover_lessons(str(tmp_path / "does-not-exist")) == []

    def test_finds_only_real_lesson_dirs(self, tmp_path):
        _write_lesson(str(tmp_path / "lezione-1"))
        os.makedirs(tmp_path / "cartella-vuota-non-lezione")
        (tmp_path / "un-file.txt").write_text("ciao")

        summaries = discover_lessons(str(tmp_path))
        assert [s.title for s in summaries] == ["lezione-1"]

    def test_sorted_most_recent_first(self, tmp_path):
        _write_lesson(str(tmp_path / "vecchia"))
        old_info = tmp_path / "vecchia" / "_state" / "info.yaml"
        old_time = time.time() - 3600
        os.utime(old_info, (old_time, old_time))

        _write_lesson(str(tmp_path / "recente"))

        summaries = discover_lessons(str(tmp_path))
        assert [s.title for s in summaries] == ["recente", "vecchia"]

    def test_broken_lesson_does_not_break_the_whole_scan(self, tmp_path):
        # Ogni loader di RT (info.yaml, ledger, science issues) è già difensivo e non
        # propaga eccezioni su file corrotti/mancanti: per esercitare davvero il ramo
        # difensivo di load_lesson_summary serve un guasto iniettato, non un file rotto.
        good_dir = tmp_path / "lezione-ok"
        _write_lesson(str(good_dir))

        broken_dir = tmp_path / "lezione-rotta"
        _write_lesson(str(broken_dir))

        def flaky_state(lesson_dir: str):
            if "lezione-rotta" in lesson_dir:
                raise RuntimeError("stato illeggibile")
            return WorkflowState.SETUP_COMPLETED

        with patch("rt.tui.data.compute_effective_workflow_state", side_effect=flaky_state):
            summaries = discover_lessons(str(tmp_path))

        titles = {s.title for s in summaries}
        assert titles == {"lezione-ok", "lezione-rotta"}
        broken = next(s for s in summaries if s.title == "lezione-rotta")
        assert broken.error is not None
        assert broken.state is None
        ok = next(s for s in summaries if s.title == "lezione-ok")
        assert ok.error is None


class TestBadgeForState:
    def test_known_states_map_to_semantic_tokens(self):
        label, token = badge_for_state(WorkflowState.HUMAN_REVIEW_REQUIRED)
        assert label == "REVISIONE"
        assert token == "warning"

        label, token = badge_for_state(WorkflowState.COMPLETED)
        assert label == "COMPLETATA"
        assert token == "success"

        label, token = badge_for_state(WorkflowState.FAILED)
        assert token == "error"

    def test_unknown_state_has_a_safe_fallback(self):
        label, token = badge_for_state(None)
        assert token == "secondary"
        assert label


class TestMarkdownPreview:
    def test_reads_real_rielaborato_when_built(self, tmp_path):
        lesson_dir = str(tmp_path)
        _write_lesson(lesson_dir)
        state_dir = os.path.join(lesson_dir, "_state")
        content = "# Lezione finale\n\nContenuto vero e proprio."
        with open(os.path.join(state_dir, "rielaborato.md"), "w", encoding="utf-8") as f:
            f.write(content)

        assert load_markdown_preview(lesson_dir) == content

    def test_strips_frontmatter_from_real_rielaborato(self, tmp_path):
        lesson_dir = str(tmp_path)
        _write_lesson(lesson_dir)
        state_dir = os.path.join(lesson_dir, "_state")
        content = (
            "---\n"
            "titolo: 'Patologia Generale: Adattamenti'\n"
            "materia: 'PATOLOGIA GENERALE 1'\n"
            "data: '2025-02-26'\n"
            "argomenti:\n"
            "  - ''\n"
            "---\n\n"
            "# [2025-02-26] PATOLOGIA GENERALE 1 - Patologia Generale\n\n"
            "Corpo della lezione."
        )
        with open(os.path.join(state_dir, "rielaborato.md"), "w", encoding="utf-8") as f:
            f.write(content)

        preview = load_markdown_preview(lesson_dir)
        assert preview == "# [2025-02-26] PATOLOGIA GENERALE 1 - Patologia Generale\n\nCorpo della lezione."
        assert "titolo:" not in preview
        assert "argomenti:" not in preview

    def test_placeholder_when_nothing_available(self, tmp_path):
        lesson_dir = str(tmp_path)
        _write_lesson(lesson_dir, with_draft=False)

        preview = load_markdown_preview(lesson_dir)
        assert "Nessuna anteprima disponibile" in preview


class TestStripYamlFrontmatter:
    def test_strips_valid_frontmatter(self):
        from rt.tui.data import strip_yaml_frontmatter
        text = "---\ntitolo: 'Test'\nmateria: 'BIO'\n---\n\n# Titolo\nCorpo"
        assert strip_yaml_frontmatter(text) == "# Titolo\nCorpo"

    def test_preserves_content_without_frontmatter(self):
        from rt.tui.data import strip_yaml_frontmatter
        text = "# Titolo\n\n---\nSeparatore\n---\nTesto"
        assert strip_yaml_frontmatter(text) == text

    def test_strips_frontmatter_with_empty_yaml_list(self):
        from rt.tui.data import strip_yaml_frontmatter
        text = "---\ntitolo: 'T'\nargomenti:\n  - ''\n---\n\n# Titolo"
        assert strip_yaml_frontmatter(text) == "# Titolo"

    def test_empty_or_none_safe(self):
        from rt.tui.data import strip_yaml_frontmatter
        assert strip_yaml_frontmatter("") == ""
        assert strip_yaml_frontmatter(None) is None



class TestLessonCost:
    def test_cost_total_reads_the_real_field_from_compute_lesson_cost(self, tmp_path):
        # Regressione: compute_lesson_cost restituisce 'total_estimated_cost_usd', non
        # 'total_cost' — una prima versione leggeva la chiave sbagliata e mostrava
        # sempre costo assente anche con un llm_debug.log popolato.
        lesson_dir = str(tmp_path)
        _write_lesson(lesson_dir)
        state_dir = os.path.join(lesson_dir, "_state")
        entries = [
            {"job": "outline", "status": "success", "estimated_cost": 0.05},
            {"job": "rewrite", "status": "success", "estimated_cost": 0.09},
        ]
        with open(os.path.join(state_dir, "llm_debug.log"), "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        summary = load_lesson_summary(lesson_dir)
        assert summary.cost_total == pytest.approx(0.14)


class TestBareCliLaunchesTui:
    def test_subcommand_still_works_normally(self):
        # Non deve lanciare la TUI quando viene passato un sottocomando reale
        # (vedi test_version_and_update.py per il caso senza sottocomando).
        from rt.cli import main

        with patch("rt.tui.app.run_app") as mock_run:
            with pytest.raises(SystemExit):
                main(["status"])  # manca l'argomento posizionale lesson_dir -> argparse esce
        mock_run.assert_not_called()


@pytest.mark.anyio
async def test_dashboard_end_to_end_with_fixture_lessons(tmp_path):
    """Mount reale della RTApp (Textual headless) su due lezioni finte: verifica
    scansione, selezione e aggiornamento del pannello di dettaglio."""
    _write_lesson(str(tmp_path / "lezione-a"), materia="ANATOMIA", with_draft=True)
    _write_lesson(str(tmp_path / "lezione-b"), materia="BIOCHIMICA", with_draft=False)

    cfg = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=str(tmp_path)))

    with patch("rt.core.config.load_config", return_value=cfg):
        from rt.tui.app import LessonRow, RTApp
        from textual.widgets import ListView

        app = RTApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.lessons) == 2
            assert app.selected_lesson is not None

            list_view = app.query_one("#lesson-list", ListView)
            assert len(list_view.children) == 2

            await pilot.press("down")
            await pilot.pause()
            assert isinstance(list_view.highlighted_child, LessonRow)
            assert app.selected_lesson.dir_path == list_view.highlighted_child.lesson.dir_path

            from textual.widgets import MarkdownViewer
            viewer = app.query_one(MarkdownViewer)
            assert viewer.show_table_of_contents is True

            await pilot.press("t")
            await pilot.pause()
            assert viewer.show_table_of_contents is False

            await pilot.press("t")
            await pilot.pause()
            assert viewer.show_table_of_contents is True



class TestDashboardSubprocessRun:
    def test_run_cli_invokes_subprocess(self, monkeypatch):
        from unittest.mock import MagicMock
        from rt.tui.app import RTApp
        import subprocess

        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("rt.telegram.daemon_status.get_rt_executable_path", lambda: "/mock/bin/rt")

        app = RTApp()
        with patch.object(app, "suspend"):
            app._run_cli(["config"])

        mock_run.assert_called_once_with(["/mock/bin/rt", "config"])

    def test_run_cli_handles_nonzero_exit_without_crashing(self, monkeypatch, capsys):
        from unittest.mock import MagicMock
        from rt.tui.app import RTApp
        import subprocess

        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=1))
        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("rt.telegram.daemon_status.get_rt_executable_path", lambda: "/mock/bin/rt")

        app = RTApp()
        with patch.object(app, "suspend"):
            app._run_cli(["review", "/path/to/lesson"])

        captured = capsys.readouterr()
        assert "terminato con codice 1" in captured.out

    def test_run_cli_handles_exceptions_gracefully(self, monkeypatch, capsys):
        from unittest.mock import MagicMock
        from rt.tui.app import RTApp
        import subprocess

        monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError))
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("rt.telegram.daemon_status.get_rt_executable_path", lambda: "/mock/bin/rt")

        app = RTApp()
        with patch.object(app, "suspend"):
            app._run_cli(["config"])

        captured = capsys.readouterr()
        assert "Eseguibile non trovato" in captured.out

    @pytest.mark.anyio
    async def test_action_methods_pass_correct_argv(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from rt.tui.app import RTApp

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path="/path/to/lesson",
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        app.selected_lesson = dummy_lesson
        monkeypatch.setattr(app, "refresh_lessons", AsyncMock())

        mock_run_cli = MagicMock()
        monkeypatch.setattr(app, "_run_cli", mock_run_cli)
        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            if hasattr(screen, "argv"):
                return 0
            return ["run", "/path/to/lesson"]

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)

        async with app.run_test():
            await app.action_run().wait()
            mock_run_cli.assert_called_with(["run", "/path/to/lesson"])

        await app.action_recall()
        mock_run_cli.assert_called_with(["recall", "/path/to/lesson"])

        await app.action_configure()
        mock_run_cli.assert_called_with(["config"])


class TestPhaseButtons:
    @pytest.mark.anyio
    async def test_phase_button_non_valid_executes_directly(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock
        from rt.core.idempotency import PhaseStatus
        from rt.tui.app import RTApp

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "stale_lesson"),
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("build", PhaseStatus.STALE), ("outline", PhaseStatus.MISSING)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [dummy_lesson])
        mock_execute = AsyncMock()
        monkeypatch.setattr(app, "_execute", mock_execute)

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-build")
            await pilot.pause()
            mock_execute.assert_awaited_once_with(["build", str(tmp_path / "stale_lesson")])

    @pytest.mark.anyio
    async def test_phase_button_valid_shows_confirm_modal_and_forces(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock
        from rt.core.idempotency import PhaseStatus
        from rt.tui.app import RTApp
        from rt.tui.command_form import ConfirmModal

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "valid_lesson"),
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("build", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [dummy_lesson])
        mock_execute = AsyncMock()
        monkeypatch.setattr(app, "_execute", mock_execute)

        # 1. Confirm with 'y'
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-build")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.press("y")
            await pilot.pause()
            mock_execute.assert_awaited_once_with(["build", str(tmp_path / "valid_lesson"), "--force"])

        # 2. Cancel with 'n'
        app2 = RTApp()
        mock_execute2 = AsyncMock()
        monkeypatch.setattr(app2, "_execute", mock_execute2)
        async with app2.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-build")
            await pilot.pause()
            assert isinstance(app2.screen, ConfirmModal)
            await pilot.press("n")
            await pilot.pause()
            mock_execute2.assert_not_called()

    @pytest.mark.anyio
    async def test_review_issues_button_visibility_and_execution(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock
        from textual.widgets import Button
        from rt.core.idempotency import PhaseStatus
        from rt.tui.app import RTApp

        lesson_with_issues = LessonSummary(
            dir_path=str(tmp_path / "issues_lesson"),
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("review", PhaseStatus.VALID)],
            pending_issues=4,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        lesson_no_issues = LessonSummary(
            dir_path=str(tmp_path / "clean_lesson"),
            title="lezione 2",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("review", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )

        app = RTApp()
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [lesson_with_issues, lesson_no_issues])
        mock_execute = AsyncMock()
        monkeypatch.setattr(app, "_execute", mock_execute)

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            from rt.tui.app import IssuesLink
            link = app.query_one("#issues-link", IssuesLink)
            assert link.display is True
            assert "4" in str(link.render())

            await pilot.click("#issues-link")
            await pilot.pause()
            mock_execute.assert_awaited_once_with(["review", str(tmp_path / "issues_lesson"), "--no-regenerate"])

            # Switch to lesson without issues
            app.query_one("#lesson-list").focus()
            await pilot.press("down")
            await pilot.pause()
            assert link.display is False

    @pytest.mark.anyio
    async def test_phase_link_review_stale_with_existing_issues_shows_confirm_modal(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock
        from rt.core.idempotency import PhaseStatus
        from rt.tui.app import RTApp
        from rt.tui.command_form import ConfirmModal
        from rt.core.models import ScienceIssue

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "stale_review_lesson"),
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("review", PhaseStatus.STALE)],
            pending_issues=2,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        from rt.core.models import ScienceType, ScienceSeverity
        fake_issues = [
            ScienceIssue(
                id="sci_1",
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.MEDIUM,
                unit_id="u1",
                claim="claim text",
                reason="c",
                suggested_fix="d",
                status="pending",
            )
        ]
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [dummy_lesson])
        monkeypatch.setattr("rt.pipeline.review.load_science_issues", lambda path: fake_issues)
        mock_execute = AsyncMock()
        monkeypatch.setattr(app, "_execute", mock_execute)

        # 1. Confirm with 'y' -> executes without --no-regenerate
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-review")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.press("y")
            await pilot.pause()
            mock_execute.assert_awaited_once_with(["review", str(tmp_path / "stale_review_lesson")])

        # 2. Cancel with 'n' -> does not execute
        app2 = RTApp()
        mock_execute2 = AsyncMock()
        monkeypatch.setattr(app2, "_execute", mock_execute2)
        async with app2.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-review")
            await pilot.pause()
            assert isinstance(app2.screen, ConfirmModal)
            await pilot.press("n")
            await pilot.pause()
            mock_execute2.assert_not_called()

    @pytest.mark.anyio
    async def test_phase_link_build_stale_executes_directly_without_modal(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock
        from rt.core.idempotency import PhaseStatus
        from rt.tui.app import RTApp
        from rt.tui.command_form import ConfirmModal

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "stale_build_lesson"),
            title="lezione",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("build", PhaseStatus.STALE)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [dummy_lesson])
        mock_execute = AsyncMock()
        monkeypatch.setattr(app, "_execute", mock_execute)

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#phase-link-build")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmModal)
            mock_execute.assert_awaited_once_with(["build", str(tmp_path / "stale_build_lesson")])

    @pytest.mark.anyio
    async def test_phase_buttons_update_on_selection_change(self, monkeypatch, tmp_path):
        from rt.tui.app import RTApp, PhaseLink
        from rt.core.idempotency import PhaseStatus

        lesson1 = LessonSummary(
            dir_path=str(tmp_path / "l1"),
            title="lezione 1",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("prepare", PhaseStatus.VALID), ("build", PhaseStatus.MISSING)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )
        lesson2 = LessonSummary(
            dir_path=str(tmp_path / "l2"),
            title="lezione 2",
            subject="materia",
            recorded="2026-03-14",
            when="oggi",
            state=None,
            phase_status=[("prepare", PhaseStatus.STALE), ("build", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=0.0,
            error=None,
        )

        app = RTApp()
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [lesson1, lesson2])

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            link_prep = app.query_one("#phase-link-prepare", PhaseLink)
            link_build = app.query_one("#phase-link-build", PhaseLink)

            assert "✓" in str(link_prep.render())
            assert "○" in str(link_build.render())

            await pilot.press("down")
            await pilot.pause()

            assert "⚠" in str(link_prep.render())
            assert "✓" in str(link_build.render())

    @pytest.mark.anyio
    async def test_lesson_row_phase_strip_vertical_stacking(self, tmp_path, monkeypatch):
        from rt.tui.app import RTApp, LessonRow
        from rt.tui.data import LessonSummary, PhaseStatus
        from rt.core.state import WorkflowState

        lesson_dir = str(tmp_path / "lesson")
        os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

        lesson = LessonSummary(
            dir_path=lesson_dir,
            title="Patologia",
            subject="Medicina",
            recorded="2026-03-14",
            when="oggi",
            state=WorkflowState.PREPARED,
            phase_status=[
                ("prepare", PhaseStatus.VALID),
                ("outline", PhaseStatus.VALID),
                ("rewrite", PhaseStatus.VALID),
                ("review", PhaseStatus.PARTIAL),
                ("build", PhaseStatus.MISSING),
            ],
            pending_issues=0,
            cost_total=1.2,
            mtime=100.0,
            error=None,
        )

        app = RTApp()
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [lesson])

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            row = app.query_one(LessonRow)
            segs = list(row.query(".phase-seg"))
            assert len(segs) == 5

            # Verifica che le classi di colore siano corrette
            assert "phase-seg-success" in segs[0].classes
            assert "phase-seg-success" in segs[1].classes
            assert "phase-seg-success" in segs[2].classes
            assert "phase-seg-warning" in segs[3].classes
            assert "phase-seg-missing" in segs[4].classes

            # Verifica disposizione verticale: stessa X, Y strettamente crescente
            xs = [s.region.x for s in segs]
            ys = [s.region.y for s in segs]
            assert len(set(xs)) == 1
            assert ys == sorted(ys)
            assert len(set(ys)) == len(ys)


class TestDashboardSearchFilter:
    @pytest.mark.anyio
    async def test_search_filters_by_title_and_subject_and_restores(self, tmp_path, monkeypatch):
        from rt.tui.app import RTApp, LessonRow
        from rt.tui.data import LessonSummary, PhaseStatus
        from rt.core.state import WorkflowState
        from textual.widgets import ListView, Input, Static

        dir1 = str(tmp_path / "lesson1")
        dir2 = str(tmp_path / "lesson2")
        dir3 = str(tmp_path / "lesson3")
        for d in (dir1, dir2, dir3):
            os.makedirs(os.path.join(d, "_state"), exist_ok=True)

        l1 = LessonSummary(
            dir_path=dir1,
            title="BIOCHIMICA GENERALE 1",
            subject="Chimica",
            recorded="2026-03-14",
            when="oggi",
            state=WorkflowState.PREPARED,
            phase_status=[("prepare", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=100.0,
        )
        l2 = LessonSummary(
            dir_path=dir2,
            title="ANATOMIA UMANA 2",
            subject="Medicina",
            recorded="2026-03-14",
            when="oggi",
            state=WorkflowState.PREPARED,
            phase_status=[("prepare", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=200.0,
        )
        l3 = LessonSummary(
            dir_path=dir3,
            title="FISIOLOGIA 1",
            subject="Biochimica Medica",
            recorded="2026-03-14",
            when="oggi",
            state=WorkflowState.PREPARED,
            phase_status=[("prepare", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=300.0,
        )

        app = RTApp()
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [l1, l2, l3])

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            lv = app.query_one("#lesson-list", ListView)
            search_input = app.query_one("#search", Input)
            assert len(lv.children) == 3

            # 1. Filtro per titolo (case-insensitive): "biochimic" trova solo BIOCHIMICA (l1) e FISIOLOGIA (subject: Biochimica Medica, l3)
            # Digita "ANATOM"
            search_input.value = "ANATOM"
            await pilot.pause()
            assert len(lv.children) == 1
            assert lv.children[0].lesson.title == "ANATOMIA UMANA 2"

            # 2. Filtro per materia: "medicina" trova ANATOMIA (subject: Medicina)
            search_input.value = "medicina"
            await pilot.pause()
            assert len(lv.children) == 1
            assert lv.children[0].lesson.title == "ANATOMIA UMANA 2"

            # 3. Filtro che non trova nulla
            search_input.value = "inesistente"
            await pilot.pause()
            assert len(lv.children) == 0
            assert app.selected_lesson is None
            assert "Nessuna lezione corrisponde" in str(app.query_one("#detail-header", Static).render())

            # 4. Cancellazione ricerca ripristina tutte le 3 lezioni
            search_input.value = ""
            await pilot.pause()
            assert len(lv.children) == 3
            assert app.selected_lesson is not None


class TestDashboardMarkdownTOC:
    @pytest.mark.anyio
    async def test_toc_click_after_refresh_does_not_crash(self, tmp_path, monkeypatch):
        from rt.tui.app import RTApp
        from rt.tui.data import LessonSummary, PhaseStatus
        from rt.core.state import WorkflowState
        from textual.widgets import MarkdownViewer, Tree

        lesson_dir = str(tmp_path / "lesson_toc")
        os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

        md_content = (
            "# Introduzione Generale\n\nContenuto introduttivo.\n\n"
            "## Sezione Uno: Concetti Base\n\nTesto della sezione 1.\n\n"
            "## Sezione Due: Dettagli Avanzati\n\nTesto della sezione 2.\n"
        )
        with open(os.path.join(lesson_dir, "rielaborato.md"), "w", encoding="utf-8") as f:
            f.write(md_content)

        lesson = LessonSummary(
            dir_path=lesson_dir,
            title="Lezione TOC Test",
            subject="Medicina",
            recorded="2026-03-14",
            when="oggi",
            state=WorkflowState.COMPLETED,
            phase_status=[("build", PhaseStatus.VALID)],
            pending_issues=0,
            cost_total=0.0,
            mtime=100.0,
        )

        app = RTApp()
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [lesson])

        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()

            # 1. Simula un refresh/re-show della lezione (come dopo l'uscita da una review o refresh)
            await app._show_lesson(lesson)
            await pilot.pause()

            viewer = app.query_one(MarkdownViewer)
            tree = viewer.query_one(Tree)
            assert len(tree.root.children) > 0

            # 2. Clicca / seleziona il primo nodo della TOC
            first_node = tree.root.children[0]
            tree.select_node(first_node)
            await pilot.pause()

            # 3. Secondo refresh con nuovo show_lesson e selezione nodo figlio
            await app._show_lesson(lesson)
            await pilot.pause()

            viewer2 = app.query_one(MarkdownViewer)
            tree2 = viewer2.query_one(Tree)
            assert len(tree2.root.children) >= 1
            top_node = tree2.root.children[0]
            tree2.select_node(top_node)
            await pilot.pause()

            if top_node.children:
                sub_node = top_node.children[0]
                tree2.select_node(sub_node)
                await pilot.pause()







