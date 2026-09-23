"""
tests/test_tui_commands_palette.py
Test per la Command Palette di RT (Task 87):
- CommandsProvider (discover e search per gli 8 comandi secondari)
- Esclusione dei comandi top-level/passivi (cost, status, run, config, recall, review)
- Dispatch end-to-end (ctrl+p -> selezione comando -> apertura CommandFormScreen)
- Prefill della lezione selezionata
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from rt.cli import build_parser
from rt.tui.app import RTApp
from rt.tui.command_form import CommandFormScreen
from rt.tui.commands_palette import CommandsProvider, PALETTE_SUBCOMMANDS
from rt.tui.data import LessonSummary


class TestCommandsProviderUnit:
    @pytest.mark.anyio
    async def test_discover_yields_all_8_subcommands(self):
        app = RTApp()
        async with app.run_test() as pilot:
            provider = CommandsProvider(app.screen)
            discovered = [hit async for hit in provider.discover()]
            assert len(discovered) == 8
            texts = [str(hit.text) for hit in discovered]

            for cmd in PALETTE_SUBCOMMANDS:
                assert f"Comando: {cmd}" in texts

            # Assicura che i comandi non previsti NON compaiano
            for forbidden in ["cost", "status", "run", "config", "recall", "review"]:
                assert f"Comando: {forbidden}" not in texts

    @pytest.mark.anyio
    async def test_search_fuzzy_query_filtering(self):
        app = RTApp()
        async with app.run_test() as pilot:
            provider = CommandsProvider(app.screen)

            # Query "outl" deve matchare solo "outline" (o eventuali contenenti "outl")
            results = [hit async for hit in provider.search("outl")]
            assert len(results) >= 1
            assert any("outline" in str(hit.text) for hit in results)
            assert not any("rewrite" in str(hit.text) for hit in results)

            # Query "prep"
            results_prep = [hit async for hit in provider.search("prep")]
            assert any("prepare" in str(hit.text) for hit in results_prep)

            # Query inesistente
            results_none = [hit async for hit in provider.search("xyz123nonexistent")]
            assert len(results_none) == 0


class TestCommandsPaletteIntegration:
    @pytest.mark.anyio
    async def test_palette_opens_and_submits_to_command_form(self, monkeypatch, tmp_path):
        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "my_lesson"),
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
        monkeypatch.setattr("rt.tui.app.discover_lessons", lambda root: [dummy_lesson])
        monkeypatch.setattr(app, "_lessons_root", lambda: str(tmp_path))

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            assert app.selected_lesson is not None

            # Apri la palette con ctrl+p
            await pilot.press("ctrl+p")
            await pilot.pause(0.5)

            # Digita "validate-outline"
            for char in "validate-outline":
                await pilot.press(char)
            await pilot.pause(0.5)

            # Premi invio per selezionare il comando filtrato
            await pilot.press("enter")
            await pilot.pause(0.5)

            # Deve aprirsi il CommandFormScreen per validate-outline
            assert isinstance(app.screen, CommandFormScreen)
            assert app.screen.subcommand_name == "validate-outline"
            # Prefill del campo lesson_dir con la lezione selezionata
            assert app.screen.prefill == {"lesson_dir": str(tmp_path / "my_lesson")}

            # Chiudi con Escape
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, CommandFormScreen)
