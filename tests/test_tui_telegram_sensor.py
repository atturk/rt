"""
tests/test_tui_telegram_sensor.py
Test per il sensore di stato Telegram cliccabile nella dashboard (Task 88):
- Clic su sensore con demone già attivo: non spawna sottoprocesso
- Clic su sensore con demone non attivo: spawna Terminal.app via osascript
- Gestione corretta dei percorsi con spazi
"""
import pytest
from unittest.mock import MagicMock

from rt.tui.app import RTApp, TelegramStatusIndicator


class TestTelegramSensor:
    @pytest.mark.anyio
    async def test_clicking_sensor_when_already_running_does_not_spawn_process(self, monkeypatch):
        mock_proc = MagicMock()
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.communicate.return_value = ("v3.3.4", "")
        mock_proc.returncode = 0
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("subprocess.Popen", mock_popen)
        monkeypatch.setattr("rt.core.version.get_current_version", lambda root: "3.3.4")
        monkeypatch.setattr("rt.telegram.daemon_status.is_daemon_running", lambda: True)

        app = RTApp()
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            mock_popen.reset_mock()
            await pilot.click("#status")
            await pilot.pause(0.2)

            mock_popen.assert_not_called()

    @pytest.mark.anyio
    async def test_clicking_sensor_when_stopped_launches_terminal_via_osascript(self, monkeypatch):
        mock_proc = MagicMock()
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.communicate.return_value = ("v3.3.4", "")
        mock_proc.returncode = 0
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("subprocess.Popen", mock_popen)
        monkeypatch.setattr("rt.core.version.get_current_version", lambda root: "3.3.4")
        monkeypatch.setattr("rt.telegram.daemon_status.is_daemon_running", lambda: False)
        monkeypatch.setattr("rt.telegram.daemon_status.get_rt_executable_path", lambda: "/mock/bin/rt")

        app = RTApp()
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            mock_popen.reset_mock()
            await pilot.click("#status")
            await pilot.pause(0.2)

            mock_popen.assert_called_once()
            args, _ = mock_popen.call_args
            cmd_list = args[0]
            assert cmd_list[0] == "osascript"
            assert cmd_list[1] == "-e"
            assert 'tell application "Terminal" to do script' in cmd_list[2]
            assert "/mock/bin/rt" in cmd_list[2]
            assert "telegram-daemon" in cmd_list[2]

    @pytest.mark.anyio
    async def test_quoting_handles_spaces_in_rt_path(self, monkeypatch):
        mock_proc = MagicMock()
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.communicate.return_value = ("v3.3.4", "")
        mock_proc.returncode = 0
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("subprocess.Popen", mock_popen)
        monkeypatch.setattr("rt.core.version.get_current_version", lambda root: "3.3.4")
        monkeypatch.setattr("rt.telegram.daemon_status.is_daemon_running", lambda: False)
        monkeypatch.setattr(
            "rt.telegram.daemon_status.get_rt_executable_path",
            lambda: "/Applications/My RT App/bin/rt",
        )

        app = RTApp()
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            mock_popen.reset_mock()
            await pilot.click("#status")
            await pilot.pause(0.2)

            mock_popen.assert_called_once()
            args, _ = mock_popen.call_args
            script_str = args[0][2]
            # Assicura che il path con spazio sia quotato nella stringa per la shell
            assert "'/Applications/My RT App/bin/rt' telegram-daemon" in script_str


