"""
tests/test_tui_command_output.py
Test per l'esecuzione in-app dei comandi a sola stampa (Task 83):
- CommandOutputScreen (cattura output, auto-close su codice 0, resta aperto su codice non zero)
- RTApp._execute() (routing tra comandi catturati e _run_cli sospeso)
- Test di regressione sui binding reali (pilot.press 'b' e 'c' per verificare l'assenza di NoActiveWorker)
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual import work
from textual.app import App
from textual.widgets import RichLog, Static

from rt.tui.app import CAPTURED_SUBCOMMANDS, RTApp
from rt.tui.command_output import CommandOutputScreen
from rt.tui.data import LessonSummary


class TestCommandOutputScreen:
    @pytest.mark.anyio
    async def test_successful_command_auto_dismisses_with_zero(self, monkeypatch):
        # Sostituiamo l'eseguibile con un comando python che stampa 2 righe ed esce con 0
        cmd_script = "import sys; print('prima riga'); sys.stdout.flush(); print('seconda riga')"
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        class HostApp(App[int]):
            return_code = None

            @work
            async def on_mount(self):
                self.return_code = await self.push_screen_wait(
                    CommandOutputScreen(["-c", cmd_script])
                )
                self.exit(self.return_code)

        app = HostApp()
        async with app.run_test() as pilot:
            # Attendiamo che il sottoprocesso e l'auto-dismiss (sleep 0.6s) completino
            await pilot.pause(1.0)
            assert app.return_code == 0

    @pytest.mark.anyio
    async def test_failing_command_stays_open_until_escape(self, monkeypatch):
        cmd_script = "import sys; print('errore build fallita'); sys.exit(42)"
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        class HostApp(App[int]):
            return_code = None

            @work
            async def on_mount(self):
                self.return_code = await self.push_screen_wait(
                    CommandOutputScreen(["-c", cmd_script])
                )

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.5)

            # La schermata CommandOutputScreen deve essere ancora aperta!
            assert isinstance(app.screen, CommandOutputScreen)
            assert app.return_code is None

            status_widget = app.screen.query_one("#cmd-status", Static)
            assert "42" in str(status_widget.render())

            # Premendo Escape, la schermata si chiude e restituisce il returncode 42
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, CommandOutputScreen)
            assert app.return_code == 42

    @pytest.mark.anyio
    async def test_spawn_failure_displays_error_and_allows_escape(self, monkeypatch):
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: "/path/to/nonexistent/executable",
        )

        class HostApp(App[int]):
            return_code = None

            @work
            async def on_mount(self):
                self.return_code = await self.push_screen_wait(
                    CommandOutputScreen(["build", "/dummy"])
                )

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            assert isinstance(app.screen, CommandOutputScreen)
            status_widget = app.screen.query_one("#cmd-status", Static)
            assert "Errore di avvio" in str(status_widget.render())

            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, CommandOutputScreen)
            assert app.return_code == 1


class TestExecuteRouting:
    @pytest.mark.anyio
    async def test_captured_subcommand_routes_to_screen(self, monkeypatch):
        app = RTApp()
        mock_refresh = AsyncMock()
        monkeypatch.setattr(app, "refresh_lessons", mock_refresh)
        mock_run_cli = MagicMock()
        monkeypatch.setattr(app, "_run_cli", mock_run_cli)

        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return 0

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)

        await app._execute(["build", "/path/to/lesson"])

        assert len(pushed_screens) == 1
        assert isinstance(pushed_screens[0], CommandOutputScreen)
        assert pushed_screens[0].argv == ["build", "/path/to/lesson"]
        mock_run_cli.assert_not_called()
        mock_refresh.assert_awaited_once()

    @pytest.mark.anyio
    async def test_non_captured_subcommand_routes_to_run_cli(self, monkeypatch):
        app = RTApp()
        mock_refresh = AsyncMock()
        monkeypatch.setattr(app, "refresh_lessons", mock_refresh)
        mock_run_cli = MagicMock()
        monkeypatch.setattr(app, "_run_cli", mock_run_cli)
        mock_push = AsyncMock()
        monkeypatch.setattr(app, "push_screen_wait", mock_push)

        await app._execute(["run", "/path/to/lesson"])

        mock_push.assert_not_called()
        mock_run_cli.assert_called_once_with(["run", "/path/to/lesson"])
        mock_refresh.assert_awaited_once()

    def test_captured_subcommands_set(self):
        expected = {
            "prepare", "rewrite", "build", "cost", "status", "add-images",
            "validate-outline", "validate-draft", "setup"
        }
        assert CAPTURED_SUBCOMMANDS == expected

    def test_report_subcommands_set(self):
        from rt.tui.app import REPORT_SUBCOMMANDS
        assert REPORT_SUBCOMMANDS == {"cost", "status", "validate-outline", "validate-draft"}
        assert REPORT_SUBCOMMANDS <= CAPTURED_SUBCOMMANDS

    @pytest.mark.anyio
    async def test_report_subcommand_disables_auto_dismiss(self, monkeypatch):
        # Regressione: 'cost'/'status' ecc. sono report da leggere, non semplici conferme —
        # non devono chiudersi da soli nemmeno su successo (visto dal vivo: la schermata dei
        # costi si chiudeva un istante dopo essersi aperta, senza dare il tempo di leggerla).
        app = RTApp()
        monkeypatch.setattr(app, "refresh_lessons", AsyncMock())
        monkeypatch.setattr(app, "_run_cli", MagicMock())
        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return 0
        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)

        await app._execute(["cost", "/path/to/lesson", "--split"])
        await app._execute(["build", "/path/to/lesson"])

        assert pushed_screens[0].argv[0] == "cost"
        assert pushed_screens[0].auto_dismiss_on_success is False
        assert pushed_screens[1].argv[0] == "build"
        assert pushed_screens[1].auto_dismiss_on_success is True


class TestCommandOutputScreenAutoDismissFlag:
    @pytest.mark.anyio
    async def test_auto_dismiss_false_keeps_screen_open_on_success(self, monkeypatch):
        cmd_script = "print('report riga 1')"
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        class HostApp(App[int]):
            return_code = None

            @work
            async def on_mount(self):
                self.return_code = await self.push_screen_wait(
                    CommandOutputScreen(["-c", cmd_script], auto_dismiss_on_success=False)
                )

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            # Successo, ma auto_dismiss_on_success=False: deve restare aperta
            assert isinstance(app.screen, CommandOutputScreen)
            assert app.return_code is None
            status_widget = app.screen.query_one("#cmd-status", Static)
            assert "successo" in str(status_widget.render()).lower()

            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, CommandOutputScreen)
            assert app.return_code == 0

    @pytest.mark.anyio
    async def test_stdin_devnull_prevents_hang_on_interactive_prompt(self, monkeypatch):
        # Regressione reale: 'rt build' può chiedere via input()/questionary se avviare il
        # demone Telegram quando la notifica fallisce. Senza stdin=DEVNULL il sottoprocesso
        # erediterebbe il terminale reale della dashboard (isatty()=True) e resterebbe
        # bloccato per sempre in attesa di un input che non può mai arrivargli in modo
        # affidabile (in conflitto con la lettura raw-mode di Textual).
        cmd_script = (
            "import sys\n"
            "print('prima della domanda')\n"
            "try:\n"
            "    line = input('Vuoi procedere? (Y/n) ')\n"
            "except EOFError:\n"
            "    line = None\n"
            "print(f'risposta={line!r}')\n"
        )
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        class HostApp(App[int]):
            return_code = None

            @work
            async def on_mount(self):
                self.return_code = await self.push_screen_wait(
                    CommandOutputScreen(["-c", cmd_script])
                )
                self.exit(self.return_code)

        app = HostApp()
        async with app.run_test() as pilot:
            # Se stdin non fosse DEVNULL questo test andrebbe in timeout (il sottoprocesso
            # resterebbe bloccato su input() per sempre): il fatto che completi in tempi
            # brevi è la prova che EOFError viene sollevato subito, come atteso.
            await pilot.pause(1.0)
            assert app.return_code == 0


class TestDashboardKeypressRegression:
    @pytest.mark.anyio
    async def test_clicking_build_button_launches_build_without_no_active_worker_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path=str(tmp_path / "selected"),
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
        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return 0

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)

        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            # Simula il click reale sulla scritta cliccabile della fase build dalla dashboard
            await pilot.click("#phase-link-build")
            await pilot.pause(0.5)
            await app.workers.wait_for_complete()

            assert len(pushed_screens) == 1
            assert isinstance(pushed_screens[0], CommandOutputScreen)
            assert pushed_screens[0].argv == ["build", str(tmp_path / "selected")]

