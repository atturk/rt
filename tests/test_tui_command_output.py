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


class TestDashboardKeypressRegression:
    @pytest.mark.anyio
    async def test_pressing_b_key_launches_build_without_no_active_worker_crash(self, monkeypatch):
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path="/path/to/selected",
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

        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return 0

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)
        monkeypatch.setattr(app, "refresh_lessons", AsyncMock())

        async with app.run_test() as pilot:
            app.selected_lesson = dummy_lesson
            # Simula la pressione reale del tasto 'b' dalla dashboard
            await pilot.press("b")
            await pilot.pause(0.2)

            assert len(pushed_screens) == 1
            assert isinstance(pushed_screens[0], CommandOutputScreen)
            assert pushed_screens[0].argv == ["build", "/path/to/selected"]

    @pytest.mark.anyio
    async def test_pressing_c_key_launches_cost_without_no_active_worker_crash(self, monkeypatch):
        monkeypatch.setattr(
            "rt.tui.command_output.get_rt_executable_path",
            lambda: sys.executable,
        )

        app = RTApp()
        dummy_lesson = LessonSummary(
            dir_path="/path/to/selected",
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

        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return 0

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)
        monkeypatch.setattr(app, "refresh_lessons", AsyncMock())

        async with app.run_test() as pilot:
            app.selected_lesson = dummy_lesson
            # Simula la pressione reale del tasto 'c' dalla dashboard
            await pilot.press("c")
            await pilot.pause(0.2)

            assert len(pushed_screens) == 1
            assert isinstance(pushed_screens[0], CommandOutputScreen)
            assert pushed_screens[0].argv == ["cost", "/path/to/selected", "--split"]
