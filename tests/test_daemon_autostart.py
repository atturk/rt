"""
Test per Task 72: rilevamento stato demone Telegram e prompt di avvio automatico dopo build.
"""
import os
import sys
from unittest.mock import patch, MagicMock
import pytest

from rt.telegram.daemon_status import (
    is_daemon_running,
    write_daemon_pid,
    remove_daemon_pid,
    launch_daemon_in_terminal,
    get_rt_executable_path,
)
from rt.cli import _prompt_and_launch_daemon_if_needed


def test_is_daemon_running_no_file(tmp_path):
    pid_file = str(tmp_path / "daemon.pid")
    assert not is_daemon_running(pid_file)


def test_is_daemon_running_dead_process(tmp_path):
    pid_file = str(tmp_path / "daemon.pid")
    with open(pid_file, "w") as f:
        f.write("99999\n")

    with patch("os.kill", side_effect=ProcessLookupError):
        assert not is_daemon_running(pid_file)


def test_is_daemon_running_alive_process(tmp_path):
    pid_file = str(tmp_path / "daemon.pid")
    with open(pid_file, "w") as f:
        f.write("12345\n")

    with patch("os.kill", return_value=None):
        assert is_daemon_running(pid_file)


def test_write_and_remove_pid(tmp_path):
    pid_file = str(tmp_path / "subdir" / "daemon.pid")
    written = write_daemon_pid(pid_file)
    assert written == pid_file
    assert os.path.exists(pid_file)
    with open(pid_file, "r") as f:
        assert f.read().strip() == str(os.getpid())

    remove_daemon_pid(pid_file)
    assert not os.path.exists(pid_file)


def test_prompt_daemon_non_tty():
    with patch("sys.stdin.isatty", return_value=False), \
         patch("rt.telegram.daemon_status.is_daemon_running") as mock_running, \
         patch("questionary.confirm") as mock_confirm:
        _prompt_and_launch_daemon_if_needed()
        mock_running.assert_not_called()
        mock_confirm.assert_not_called()


def test_prompt_daemon_already_running():
    with patch("sys.stdin.isatty", return_value=True), \
         patch("rt.telegram.daemon_status.is_daemon_running", return_value=True), \
         patch("questionary.confirm") as mock_confirm:
        _prompt_and_launch_daemon_if_needed()
        mock_confirm.assert_not_called()


def test_prompt_daemon_confirmed():
    with patch("sys.stdin.isatty", return_value=True), \
         patch("rt.telegram.daemon_status.is_daemon_running", return_value=False), \
         patch("questionary.confirm") as mock_confirm, \
         patch("rt.telegram.daemon_status.launch_daemon_in_terminal") as mock_launch:
        mock_ask = MagicMock(return_value=True)
        mock_confirm.return_value.ask = mock_ask

        _prompt_and_launch_daemon_if_needed()
        mock_confirm.assert_called_once_with("Vuoi avviare il demone Telegram ora?", default=True)
        mock_launch.assert_called_once()


def test_prompt_daemon_declined():
    with patch("sys.stdin.isatty", return_value=True), \
         patch("rt.telegram.daemon_status.is_daemon_running", return_value=False), \
         patch("questionary.confirm") as mock_confirm, \
         patch("rt.telegram.daemon_status.launch_daemon_in_terminal") as mock_launch:
        mock_ask = MagicMock(return_value=False)
        mock_confirm.return_value.ask = mock_ask

        _prompt_and_launch_daemon_if_needed()
        mock_launch.assert_not_called()


def test_launch_daemon_in_terminal():
    with patch("subprocess.run") as mock_run:
        launch_daemon_in_terminal()
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd_args = args[0]
        assert cmd_args[0] == "osascript"
        assert cmd_args[1] == "-e"
        assert 'tell application "Terminal" to do script' in cmd_args[2]
        assert "telegram-daemon" in cmd_args[2]
