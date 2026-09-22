"""
tests/test_tui_command_form.py
Test per l'infrastruttura di form generica sopra argparse (Task 82):
- build_parser()
- CommandFormScreen e ConfirmModal
- Wiring in RTApp
"""
import argparse
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.widgets import Checkbox, Input, Select, Button

from rt.cli import build_parser
from rt.tui.command_form import CommandFormScreen, ConfirmModal, _get_primary_opt_string
from rt.tui.app import RTApp
from rt.tui.data import LessonSummary


class TestBuildParser:
    def test_returns_all_15_subcommands(self):
        parser, sub_dict = build_parser()
        expected_subcommands = {
            "config", "run", "review", "recall", "status", "telegram-daemon",
            "setup", "prepare", "outline", "rewrite", "build", "add-images",
            "validate-outline", "validate-draft", "cost",
        }
        assert set(sub_dict.keys()) == expected_subcommands
        assert len(sub_dict) == 15

    def test_parse_args_run_command(self):
        parser, _ = build_parser()
        args = parser.parse_args(["run", "lezione.m4a", "--mock", "--date", "2026-03-14"])
        assert args.command == "run"
        assert args.input == ["lezione.m4a"]
        assert args.mock is True
        assert args.date == "2026-03-14"
        assert args.rename is True

    def test_help_formatting(self, capsys):
        parser, _ = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["-h"])
        out, _ = capsys.readouterr()
        assert "rt <comando> [opzioni]" in out
        assert "Comandi principali" in out
        assert "Fasi della pipeline:" in out
        assert "Esegue l'intera pipeline end-to-end" in out

        with pytest.raises(SystemExit):
            parser.parse_args(["run", "-h"])
        out_run, _ = capsys.readouterr()
        assert "input" in out_run
        assert "--with-review" in out_run
        assert "--mock" in out_run


class TestConfirmModal:
    @pytest.mark.anyio
    async def test_confirm_modal_buttons_and_keys(self):
        from textual import work

        class ModalHostApp(App[bool]):
            @work
            async def on_mount(self):
                res = await self.push_screen_wait(ConfirmModal("Sei sicuro?", title="Test Modal"))
                self.exit(res)

        app = ModalHostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press 'y' to confirm
            await pilot.press("y")
            await pilot.pause()
            assert app.return_value is True

        app_cancel = ModalHostApp()
        async with app_cancel.run_test() as pilot:
            await pilot.pause()
            # Press 'n' to cancel
            await pilot.press("n")
            await pilot.pause()
            assert app_cancel.return_value is False


class TestCommandFormScreen:
    @pytest.mark.anyio
    async def test_widget_generation_and_prefill(self):
        _, sub_dict = build_parser()
        run_parser = sub_dict["run"]

        prefill = {
            "input": ["/path/to/my_lesson"],
            "date": "2026-05-10",
            "mock": True,
            "rename": False,
            "channel": "terminal",
            "with_review": "all",
        }

        form = CommandFormScreen("run", run_parser, prefill=prefill)

        class HostApp(App):
            def compose(self):
                yield form

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify widgets count against non-help actions
            non_help_actions = [
                a for a in run_parser._actions
                if a.dest != "help" and not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))
            ]

            input_widget = form.query_one("#inp_input", Input)
            assert input_widget.value == "/path/to/my_lesson"

            date_widget = form.query_one("#inp_date", Input)
            assert date_widget.value == "2026-05-10"

            mock_widget = form.query_one("#chk_mock", Checkbox)
            assert mock_widget.value is True

            rename_widget = form.query_one("#chk_rename", Checkbox)
            assert rename_widget.value is False

            channel_widget = form.query_one("#sel_channel", Select)
            assert channel_widget.value == "terminal"

            with_review_widget = form.query_one("#sel_with_review", Select)
            assert with_review_widget.value == "all"

            # Check built argv
            argv = form.build_argv()
            assert argv[0] == "run"
            assert "--mock" in argv
            assert "--no-rename" in argv
            assert "--channel" in argv
            assert "terminal" in argv
            assert "--with-review" in argv
            assert "all" in argv
            assert "--date" in argv
            assert "2026-05-10" in argv
            assert "/path/to/my_lesson" in argv

    @pytest.mark.anyio
    async def test_form_submission_with_force_triggers_confirm(self):
        from textual import work

        _, sub_dict = build_parser()
        run_parser = sub_dict["run"]

        prefill = {"input": ["audio.m4a"], "force": True}

        class HostApp(App[list]):
            @work
            async def on_mount(self):
                res = await self.push_screen_wait(
                    CommandFormScreen("run", run_parser, prefill=prefill)
                )
                self.exit(res)

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press Ctrl+S to submit
            await pilot.press("ctrl+s")
            await pilot.pause()

            # Confirm modal should be visible -> press 'y'
            await pilot.press("y")
            await pilot.pause()

            assert app.return_value is not None
            assert "--force" in app.return_value
            assert "audio.m4a" in app.return_value

    @pytest.mark.anyio
    async def test_form_cancel_returns_none(self):
        from textual import work

        _, sub_dict = build_parser()
        run_parser = sub_dict["run"]

        class HostApp(App[list]):
            @work
            async def on_mount(self):
                res = await self.push_screen_wait(
                    CommandFormScreen("run", run_parser)
                )
                self.exit(res)

        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press Escape to cancel
            await pilot.press("escape")
            await pilot.pause()
            assert app.return_value is None


class TestDashboardWiringNonRegression:
    def test_old_new_lesson_modal_and_action_removed(self):
        import rt.tui.app as tui_app_mod
        assert not hasattr(tui_app_mod, "NewLessonModal")
        assert not hasattr(tui_app_mod.RTApp, "action_new_lesson")

    @pytest.mark.anyio
    async def test_action_run_with_and_without_selected_lesson(self, monkeypatch):
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

        # 1. With selected lesson
        app.selected_lesson = dummy_lesson
        monkeypatch.setattr(app, "refresh_lessons", AsyncMock())
        mock_run_cli = MagicMock()
        monkeypatch.setattr(app, "_run_cli", mock_run_cli)

        pushed_screens = []
        async def fake_push_screen_wait(screen):
            pushed_screens.append(screen)
            return ["run", screen.prefill.get("input", [""])[0]]

        monkeypatch.setattr(app, "push_screen_wait", fake_push_screen_wait)

        await app.action_run()
        assert len(pushed_screens) == 1
        assert pushed_screens[0].prefill == {"input": ["/path/to/selected"]}
        mock_run_cli.assert_called_with(["run", "/path/to/selected"])

        # 2. Without selected lesson
        pushed_screens.clear()
        app.selected_lesson = None
        monkeypatch.setattr(app, "_lessons_root", lambda: "/my/lessons/root")

        await app.action_run()
        assert len(pushed_screens) == 1
        assert pushed_screens[0].prefill == {"dest_dir": "/my/lessons/root"}
