"""
Test per Task 54 — rt -v (versione) e rt -u (aggiornamento).
"""
import os
import sys
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from rt.core.version import (
    parse_semver,
    format_version,
    get_current_version,
    get_latest_remote_version,
    run_version,
    run_update,
)
from rt.cli import main


def test_parse_semver_and_format_version():
    assert parse_semver("v2.4.0") == (2, 4, 0)
    assert parse_semver("2.4.0") == (2, 4, 0)
    assert parse_semver("v2.10.1") == (2, 10, 1)
    assert parse_semver("v3.0") == (3, 0, 0)
    assert parse_semver("v4") == (4, 0, 0)
    assert parse_semver("invalid") is None
    assert parse_semver("") is None

    assert format_version("v2.4.0") == "2.4.0"
    assert format_version("V2.10.0") == "2.10.0"
    assert format_version("2.4.0") == "2.4.0"
    assert format_version("sconosciuta") == "sconosciuta"


def test_semver_sorting_v2_10_greater_than_v2_9():
    tags = ["v2.9.0", "v2.10.0", "v2.8.5", "v1.0.0", "v2.10.1"]
    parsed = [(parse_semver(t), format_version(t)) for t in tags]
    parsed.sort(key=lambda x: x[0])
    sorted_tags = [item[1] for item in parsed]
    assert sorted_tags == ["1.0.0", "2.8.5", "2.9.0", "2.10.0", "2.10.1"]
    assert parse_semver("v2.10.0") > parse_semver("v2.9.0")


def test_get_current_version_with_tag():
    mock_res = MagicMock(returncode=0, stdout="v2.4.0\n")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        ver = get_current_version("/fake/root")
        assert ver == "2.4.0"
        mock_run.assert_called_once_with(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd="/fake/root",
            capture_output=True,
            text=True,
            check=False,
        )


def test_get_current_version_no_tags():
    mock_res = MagicMock(returncode=128, stdout="", stderr="fatal: No names found\n")
    with patch("subprocess.run", return_value=mock_res):
        ver = get_current_version("/fake/root")
        assert ver == "sconosciuta"


def test_get_current_version_exception():
    with patch("subprocess.run", side_effect=OSError("git not found")):
        ver = get_current_version("/fake/root")
        assert ver == "sconosciuta"


def test_get_latest_remote_version_success():
    remote_output = (
        "aaa111\trefs/tags/v2.3.0\n"
        "bbb222\trefs/tags/v2.10.0\n"
        "ccc333\trefs/tags/v2.10.0^{}\n"
        "ddd444\trefs/tags/v2.9.0\n"
        "eee555\trefs/tags/non-semver\n"
    )
    mock_res = MagicMock(returncode=0, stdout=remote_output)
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        latest = get_latest_remote_version("/fake/root", timeout=3.0)
        assert latest == "2.10.0"
        mock_run.assert_called_once_with(
            ["git", "ls-remote", "--tags", "origin"],
            cwd="/fake/root",
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )


def test_get_latest_remote_version_failure_or_timeout():
    mock_res = MagicMock(returncode=128, stdout="")
    with patch("subprocess.run", return_value=mock_res):
        assert get_latest_remote_version("/fake/root") is None

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5.0)):
        assert get_latest_remote_version("/fake/root") is None

    with patch("subprocess.run", side_effect=OSError("network down")):
        assert get_latest_remote_version("/fake/root") is None


def test_run_version_up_to_date(capsys):
    with patch("rt.core.version.get_current_version", return_value="2.4.0"), \
         patch("rt.core.version.get_latest_remote_version", return_value="2.4.0"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 2.4.0 — sei aggiornato ✅" in captured


def test_run_version_update_available(capsys):
    with patch("rt.core.version.get_current_version", return_value="2.3.0"), \
         patch("rt.core.version.get_latest_remote_version", return_value="2.4.0"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 2.3.0 — è disponibile la versione 2.4.0" in captured
        assert "Esegui 'rt -u' per aggiornare" in captured


def test_run_version_offline(capsys):
    with patch("rt.core.version.get_current_version", return_value="2.3.0"), \
         patch("rt.core.version.get_latest_remote_version", return_value=None):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 2.3.0 (impossibile verificare aggiornamenti — controlla la connessione)" in captured


def test_run_version_unknown_current_version(capsys):
    with patch("rt.core.version.get_current_version", return_value="sconosciuta"), \
         patch("rt.core.version.get_latest_remote_version", return_value="2.4.0"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione sconosciuta — è disponibile la versione 2.4.0" in captured
        assert "Esegui 'rt -u' per aggiornare" in captured


def test_run_update_uncommitted_changes(capsys):
    # git status --porcelain -uno returns non-empty
    mock_status = MagicMock(returncode=0, stdout=" M rt/cli.py\n")
    with patch("subprocess.run", return_value=mock_status) as mock_run:
        with pytest.raises(SystemExit) as exc_info:
            run_update("/fake/root")
        assert exc_info.value.code == 1
        captured = capsys.readouterr().out
        assert "⚠️ Ci sono modifiche locali non salvate nel codice, impossibile aggiornare in sicurezza." in captured
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0] == ["git", "status", "--porcelain", "-uno"]


def test_run_update_not_on_main_branch(capsys):
    def side_effect(cmd, **kwargs):
        if cmd == ["git", "status", "--porcelain", "-uno"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return MagicMock(returncode=0, stdout="feature-branch\n")
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=side_effect):
        with pytest.raises(SystemExit) as exc_info:
            run_update("/fake/root")
        assert exc_info.value.code == 1
        captured = capsys.readouterr().out
        assert "⚠️ Non sei sul branch 'main', impossibile aggiornare automaticamente." in captured


def test_run_update_already_up_to_date(capsys):
    def side_effect(cmd, **kwargs):
        if cmd == ["git", "status", "--porcelain", "-uno"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return MagicMock(returncode=0, stdout="main\n")
        if cmd == ["git", "fetch", "origin"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "HEAD"]:
            return MagicMock(returncode=0, stdout="sha123\n")
        if cmd == ["git", "rev-parse", "origin/main"]:
            return MagicMock(returncode=0, stdout="sha123\n")
        if cmd == ["git", "describe", "--tags", "--abbrev=0"]:
            return MagicMock(returncode=0, stdout="v2.4.0\n")
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=side_effect) as mock_run:
        with pytest.raises(SystemExit) as exc_info:
            run_update("/fake/root")
        assert exc_info.value.code == 0
        captured = capsys.readouterr().out
        assert "Sei già aggiornato all'ultima versione (2.4.0)." in captured
        # Ensure pip install was NOT called
        for call in mock_run.call_args_list:
            assert "pip" not in call[0][0]


def test_run_update_successful(capsys, tmp_path):
    # Setup a mock requirements.txt and mock venv python
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest\n")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_py = venv_bin / "python3"
    venv_py.write_text("")

    call_history = []

    def side_effect(cmd, **kwargs):
        call_history.append(cmd)
        if cmd == ["git", "status", "--porcelain", "-uno"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return MagicMock(returncode=0, stdout="main\n")
        if cmd == ["git", "fetch", "origin"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "HEAD"]:
            return MagicMock(returncode=0, stdout="old_sha\n")
        if cmd == ["git", "rev-parse", "origin/main"]:
            return MagicMock(returncode=0, stdout="new_sha\n")
        if cmd == ["git", "describe", "--tags", "--abbrev=0"]:
            # Returns 2.3.0 first, then 2.4.0 after merge
            if len([c for c in call_history if c == ["git", "merge", "--ff-only", "origin/main"]]) == 0:
                return MagicMock(returncode=0, stdout="v2.3.0\n")
            return MagicMock(returncode=0, stdout="v2.4.0\n")
        if cmd == ["git", "merge", "--ff-only", "origin/main"]:
            return MagicMock(returncode=0, stdout="Updating old_sha..new_sha\n")
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=side_effect):
        with pytest.raises(SystemExit) as exc_info:
            run_update(str(tmp_path))
        assert exc_info.value.code == 0
        captured = capsys.readouterr().out
        assert "Aggiornamento in corso..." in captured
        assert "✅ RT aggiornato: 2.3.0 → 2.4.0" in captured

        # Check that pip install was called with the venv python
        pip_calls = [c for c in call_history if len(c) > 2 and "pip" in c]
        assert len(pip_calls) == 1
        assert pip_calls[0][0] == str(venv_py)
        assert pip_calls[0][1:] == ["-m", "pip", "install", "-r", str(req_file), "--quiet"]


def test_run_update_divergent_history_merge_failure(capsys):
    def side_effect(cmd, **kwargs):
        if cmd == ["git", "status", "--porcelain", "-uno"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return MagicMock(returncode=0, stdout="main\n")
        if cmd == ["git", "fetch", "origin"]:
            return MagicMock(returncode=0, stdout="")
        if cmd == ["git", "rev-parse", "HEAD"]:
            return MagicMock(returncode=0, stdout="old_sha\n")
        if cmd == ["git", "rev-parse", "origin/main"]:
            return MagicMock(returncode=0, stdout="new_sha\n")
        if cmd == ["git", "describe", "--tags", "--abbrev=0"]:
            return MagicMock(returncode=0, stdout="v2.3.0\n")
        if cmd == ["git", "merge", "--ff-only", "origin/main"]:
            return MagicMock(returncode=1, stdout="", stderr="fatal: Not possible to fast-forward, aborting.")
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=side_effect):
        with pytest.raises(SystemExit) as exc_info:
            run_update("/fake/root")
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "❌ Impossibile completare l'aggiornamento automatico" in err
        assert "Contatta chi mantiene il progetto" in err


def test_cli_main_flag_interception():
    with patch("rt.core.version.run_version") as mock_version:
        with pytest.raises(SystemExit) as exc_info:
            main(["-v"])
        assert exc_info.value.code == 0
        mock_version.assert_called_once()

    with patch("rt.core.version.run_version") as mock_version:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        mock_version.assert_called_once()

    with patch("rt.core.version.run_update") as mock_update:
        with pytest.raises(SystemExit) as exc_info:
            main(["-u"])
        assert exc_info.value.code == 0
        mock_update.assert_called_once()

    with patch("rt.core.version.run_update") as mock_update:
        with pytest.raises(SystemExit) as exc_info:
            main(["--update"])
        assert exc_info.value.code == 0
        mock_update.assert_called_once()


def test_cli_main_missing_subcommand_behavior():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    # argparse error on missing required subparser exits with code 2
    assert exc_info.value.code == 2


def test_cli_help_includes_version_and_update(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr().out
    assert "-v, --version" in captured
    assert "-u, --update" in captured
