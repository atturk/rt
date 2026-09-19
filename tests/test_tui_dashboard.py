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

    def test_placeholder_when_nothing_available(self, tmp_path):
        lesson_dir = str(tmp_path)
        _write_lesson(lesson_dir, with_draft=False)

        preview = load_markdown_preview(lesson_dir)
        assert "Nessuna anteprima disponibile" in preview


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
