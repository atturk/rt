"""
Test per Task 92 — rt -v (versione) e rt -u (aggiornamento) basati su file VERSION e GitHub Releases.
"""
import io
import os
import sys
import json
import tarfile
import tempfile
import urllib.error
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


def test_get_current_version_from_file(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("3.3.8\n", encoding="utf-8")
    assert get_current_version(str(tmp_path)) == "3.3.8"

    version_file.write_text("v3.4.0", encoding="utf-8")
    assert get_current_version(str(tmp_path)) == "3.4.0"


def test_get_current_version_missing_or_empty(tmp_path):
    assert get_current_version(str(tmp_path)) == "sconosciuta"

    version_file = tmp_path / "VERSION"
    version_file.write_text("   \n", encoding="utf-8")
    assert get_current_version(str(tmp_path)) == "sconosciuta"


def test_get_latest_remote_version_success():
    mock_payload = json.dumps({"tag_name": "v3.3.8"}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        latest = get_latest_remote_version("/fake/root", timeout=3.0)
        assert latest == "3.3.8"


def test_get_latest_remote_version_404_no_releases():
    http_err = urllib.error.HTTPError(
        url="https://api.github.com/repos/atturk/rt/releases/latest",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=io.BytesIO(b"{}"),
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        latest = get_latest_remote_version("/fake/root")
        assert latest == ""


def test_get_latest_remote_version_failure_or_timeout():
    url_err = urllib.error.URLError("Network is unreachable")
    with patch("urllib.request.urlopen", side_effect=url_err):
        assert get_latest_remote_version("/fake/root") is None

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Timed out")):
        assert get_latest_remote_version("/fake/root") is None


def test_run_version_up_to_date(capsys):
    with patch("rt.core.version.get_current_version", return_value="3.3.8"), \
         patch("rt.core.version.get_latest_remote_version", return_value="3.3.8"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 3.3.8 — sei aggiornato ✅" in captured


def test_run_version_update_available(capsys):
    with patch("rt.core.version.get_current_version", return_value="3.3.7"), \
         patch("rt.core.version.get_latest_remote_version", return_value="3.3.8"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 3.3.7 — è disponibile la versione 3.3.8" in captured
        assert "Esegui 'rt -u' per aggiornare" in captured


def test_run_version_offline(capsys):
    with patch("rt.core.version.get_current_version", return_value="3.3.8"), \
         patch("rt.core.version.get_latest_remote_version", return_value=None):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 3.3.8 (impossibile verificare aggiornamenti — controlla la connessione)" in captured


def test_run_version_no_releases_yet(capsys):
    with patch("rt.core.version.get_current_version", return_value="3.3.8"), \
         patch("rt.core.version.get_latest_remote_version", return_value=""):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione 3.3.8 (nessuna versione pubblicata ancora sul repository)" in captured


def test_run_version_unknown_current_version(capsys):
    with patch("rt.core.version.get_current_version", return_value="sconosciuta"), \
         patch("rt.core.version.get_latest_remote_version", return_value="3.3.8"):
        run_version("/fake/root")
        captured = capsys.readouterr().out
        assert "RT versione sconosciuta — è disponibile la versione 3.3.8" in captured
        assert "Esegui 'rt -u' per aggiornare" in captured


def _create_mock_tarball_bytes(version: str, new_file_name: str = "nuovo_modulo.py") -> bytes:
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w:gz") as tar:
        # VERSION
        v_data = f"{version}\n".encode("utf-8")
        ti_v = tarfile.TarInfo(name=f"rt-{version}/VERSION")
        ti_v.size = len(v_data)
        tar.addfile(ti_v, io.BytesIO(v_data))

        # new file
        f_data = b"# new file content\n"
        ti_f = tarfile.TarInfo(name=f"rt-{version}/{new_file_name}")
        ti_f.size = len(f_data)
        tar.addfile(ti_f, io.BytesIO(f_data))

        # requirements.txt
        req_data = b"pytest\n"
        ti_req = tarfile.TarInfo(name=f"rt-{version}/requirements.txt")
        ti_req.size = len(req_data)
        tar.addfile(ti_req, io.BytesIO(req_data))

    return tar_stream.getvalue()


def test_run_update_end_to_end_success(tmp_path, capsys):
    # 1. Existing installation in tmp_path
    (tmp_path / "VERSION").write_text("3.3.7\n", encoding="utf-8")
    (tmp_path / "rt").mkdir()
    (tmp_path / "rt" / "vecchio_modulo.py").write_text("print('old')", encoding="utf-8")
    private_files = [".agents/notes.md", ".agent/plan.md", ".claude/settings.json",
                     ".rt_telegram/registry.json", "lezioni/audio.wav", "appunti.md"]
    for name in private_files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("contenuto locale", encoding="utf-8")
    
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "general.yaml").write_text("user_setting: true\n", encoding="utf-8")

    (tmp_path / ".env").write_text("SECRET=my_key\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("LOCAL=1\n", encoding="utf-8")
    (tmp_path / "install.log").write_text("previous install log\n", encoding="utf-8")

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_py = venv_bin / "python3"
    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")

    tar_bytes = _create_mock_tarball_bytes("3.3.8", "nuovo_modulo.py")

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        if "releases/latest" in url:
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({"tag_name": "v3.3.8"}).encode("utf-8")
        elif "archive/refs/tags" in url or ".tar.gz" in url:
            mock_resp.status = 200
            mock_resp.read.side_effect = [tar_bytes, b""]
            mock_resp.raw = io.BytesIO(tar_bytes)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
         patch("subprocess.run") as mock_subproc:

        with pytest.raises(SystemExit) as exc_info:
            run_update(str(tmp_path))
        assert exc_info.value.code == 0

    captured = capsys.readouterr().out
    assert "✅ RT aggiornato: 3.3.7 → 3.3.8" in captured

    # Verify user config, env, venv, install.log were NOT modified
    assert (tmp_path / "config" / "general.yaml").read_text(encoding="utf-8") == "user_setting: true\n"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "SECRET=my_key\n"
    assert (tmp_path / ".env.local").read_text(encoding="utf-8") == "LOCAL=1\n"
    assert (tmp_path / "install.log").read_text(encoding="utf-8") == "previous install log\n"
    assert (tmp_path / ".venv" / "bin" / "python3").exists()

    # Elimina solo codice obsoleto, conserva stato e dati locali.
    assert not (tmp_path / "rt" / "vecchio_modulo.py").exists()
    for name in private_files:
        assert (tmp_path / name).read_text(encoding="utf-8") == "contenuto locale"
    assert (tmp_path / "nuovo_modulo.py").exists()
    assert (tmp_path / "VERSION").read_text(encoding="utf-8").strip() == "3.3.8"


def test_run_update_download_failure_preserves_installation(tmp_path, capsys):
    (tmp_path / "VERSION").write_text("3.3.7\n", encoding="utf-8")
    (tmp_path / "vecchio_modulo.py").write_text("print('old')", encoding="utf-8")

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "general.yaml").write_text("user_setting: true\n", encoding="utf-8")

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "releases/latest" in url:
            mock_resp = MagicMock()
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({"tag_name": "v3.3.8"}).encode("utf-8")
            return mock_resp
        else:
            raise urllib.error.URLError("Download stream interrupted")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with pytest.raises(SystemExit) as exc_info:
            run_update(str(tmp_path))
        assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "❌ Impossibile scaricare l'aggiornamento" in err

    # Verify files untouched
    assert (tmp_path / "VERSION").read_text(encoding="utf-8").strip() == "3.3.7"
    assert (tmp_path / "vecchio_modulo.py").exists()
    assert (tmp_path / "config" / "general.yaml").exists()


def test_run_update_already_up_to_date(tmp_path, capsys):
    (tmp_path / "VERSION").write_text("3.3.8\n", encoding="utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"tag_name": "v3.3.8"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(SystemExit) as exc_info:
            run_update(str(tmp_path))
        assert exc_info.value.code == 0

    captured = capsys.readouterr().out
    assert "Sei già aggiornato all'ultima versione (3.3.8)." in captured


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


def test_cli_main_no_subcommand_launches_tui_app():
    with patch("rt.tui.app.run_app") as mock_run:
        main([])
    mock_run.assert_called_once()


def test_cli_help_includes_version_and_update(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr().out
    assert "-v, --version" in captured
    assert "-u, --update" in captured


@pytest.mark.parametrize('git_is_file', [False, True])
def test_update_refuses_development_checkout_before_network(tmp_path, git_is_file):
    """Protegge sia repository normali sia worktree, anche se hanno modifiche locali."""
    if git_is_file:
        (tmp_path / '.git').write_text('gitdir: /some/worktree')
    else:
        (tmp_path / '.git').mkdir()
    with patch('urllib.request.urlopen') as network:
        with pytest.raises(SystemExit) as exc:
            run_update(str(tmp_path))
    assert exc.value.code == 1
    network.assert_not_called()
