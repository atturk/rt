"""
tests/test_tui_manual.py
Test per la schermata 'Manuale' di RT (Task 89):
- Apertura tramite '?' e chiusura tramite 'escape' / 'q'
- Verifica che tutti i 15 sottocomandi da build_parser() siano inclusi nel Markdown generato
- Verifica che tutti i keybinding attivi in RTApp.BINDINGS siano presenti nel Markdown
"""
import pytest

from rt.cli import build_parser
from rt.tui.app import RTApp
from rt.tui.manual import ManualScreen, build_manual_markdown


class TestManualScreenUnit:
    def test_build_manual_markdown_includes_all_subcommands(self):
        _, sub_dict = build_parser()
        bindings = RTApp.BINDINGS
        md_text = build_manual_markdown(bindings, sub_dict)

        # Tutti i 15 sottocomandi devono comparire nel manuale
        for name in sub_dict.keys():
            assert f"### `rt {name}`" in md_text

        # Tutti i keybinding in RTApp.BINDINGS devono comparire
        for b in bindings:
            key = b[0] if isinstance(b, tuple) else b.key
            assert f"`{key}`" in md_text

        # ctrl+p per la command palette deve essere presente
        assert "`ctrl+p`" in md_text


class TestManualScreenIntegration:
    @pytest.mark.anyio
    async def test_pressing_question_mark_opens_manual_and_escape_dismisses(self):
        app = RTApp()
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            assert not isinstance(app.screen, ManualScreen)

            # Premi '?' per aprire il manuale
            await pilot.press("?")
            await pilot.pause(0.3)
            assert isinstance(app.screen, ManualScreen)

            # Premi 'escape' per chiudere il manuale
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ManualScreen)

            # Riapri e chiudi con 'q'
            await pilot.press("?")
            await pilot.pause(0.3)
            assert isinstance(app.screen, ManualScreen)

            await pilot.press("q")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ManualScreen)
