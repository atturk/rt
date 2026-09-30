"""install.sh: gli strumenti facoltativi (micro, mpv) non fermano l'installazione, Homebrew non
scrivibile si segnala prima del primo 'brew install' con il comando per sistemarlo, e un errore
di un'installazione obbligatoria mostra la coda di install.log.

Le funzioni si estraggono dallo script e girano in bash con 'set -euo pipefail' e un 'brew'
finto: lo script intero installerebbe davvero."""
import os
import re
import shutil
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SH = os.path.join(PROJECT_ROOT, "install.sh")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash non disponibile")


def _functions() -> str:
    with open(INSTALL_SH, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^show_log_tail\(\) \{.*?^brew_install_quiet\(\) \{.*?^\}\n", text, re.S | re.M)
    assert m, "funzioni di brew_install_quiet non trovate in install.sh"
    return m.group(0)


FAKE_BREW = r'''
brew() {
    case "$1" in
        --prefix) echo "$PREFIX" ;;
        install)
            echo "==> Installing $2"
            if [ "${BREW_FAILS:-}" = "$2" ]; then
                echo "Error: The following directories are not writable by your user:"
                echo "$PREFIX/share/man"
                return 1
            fi ;;
    esac
}
'''


def _run(tmp_path, body: str, extra_env=None):
    prefix = tmp_path / "homebrew"
    for d in ("bin", "Cellar", "share"):
        (prefix / d).mkdir(parents=True, exist_ok=True)
    log = tmp_path / "install.log"
    log.write_text("", encoding="utf-8")
    script = "\n".join([
        "set -euo pipefail",
        f"LOG_FILE='{log}'",
        "RED=''; GREEN=''; YELLOW=''; RESET=''",
        f"PREFIX='{prefix}'",
        FAKE_BREW,
        _functions(),
        body,
    ])
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30)


def test_optional_tool_failure_only_warns(tmp_path):
    result = _run(tmp_path, 'brew_install_quiet mpv "mpv" optional\necho "PROSEGUO"',
                  {"BREW_FAILS": "mpv"})
    assert result.returncode == 0
    assert "PROSEGUO" in result.stdout
    assert "mpv" in result.stderr and "facoltativo" in result.stderr


def test_required_tool_failure_stops_and_shows_log_tail(tmp_path):
    result = _run(tmp_path, 'brew_install_quiet ffmpeg "ffmpeg"\necho "PROSEGUO"',
                  {"BREW_FAILS": "ffmpeg"})
    assert result.returncode == 1
    assert "PROSEGUO" not in result.stdout
    assert "Installazione di ffmpeg fallita" in result.stderr
    assert "Ultime righe di install.log" in result.stderr
    assert "not writable by your user" in result.stderr


def test_successful_install(tmp_path):
    result = _run(tmp_path, 'brew_install_quiet ffmpeg "ffmpeg"\necho "PROSEGUO"')
    assert result.returncode == 0 and "ffmpeg installato" in result.stdout and "PROSEGUO" in result.stdout


def test_unwritable_homebrew_stops_before_brew_install_with_the_fix(tmp_path):
    # Da root ogni cartella è scrivibile: qui si simula il risultato del controllo.
    body = "\n".join([
        'brew_unwritable_dirs() { echo "$PREFIX/Cellar"; }',
        'brew() { if [ "$1" = install ]; then echo "BREW INSTALL"; fi; }',
        'brew_install_quiet micro "micro" optional',
        'echo "DOPO MICRO"',
        'brew_install_quiet ffmpeg "ffmpeg"',
        'echo "PROSEGUO"',
    ])
    result = _run(tmp_path, body)
    assert result.returncode == 1
    assert "BREW INSTALL" not in result.stdout
    assert "DOPO MICRO" in result.stdout and "PROSEGUO" not in result.stdout
    assert "Homebrew non è scrivibile" in result.stderr and "/Cellar" in result.stderr
    assert 'sudo chown -R "$(whoami)" "$(brew --prefix)"' in result.stderr
    assert result.stderr.count("appartengono a un altro utente") == 1  # controllo fatto una volta
    assert "ffmpeg è necessario" in result.stderr


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="da root ogni cartella è scrivibile")
def test_unwritable_dirs_are_detected(tmp_path):
    cellar = tmp_path / "homebrew" / "Cellar"
    cellar.mkdir(parents=True)
    cellar.chmod(0o555)
    try:
        result = _run(tmp_path, "brew_unwritable_dirs")
    finally:
        cellar.chmod(0o755)
    assert result.returncode == 0
    assert result.stdout.strip().splitlines() == [str(cellar)]


def test_writable_homebrew_passes_the_check(tmp_path):
    result = _run(tmp_path, 'brew_unwritable_dirs\ncheck_brew_writable && echo "OK"')
    assert result.returncode == 0 and result.stdout.strip() == "OK"


def test_install_sh_syntax():
    assert subprocess.run(["bash", "-n", INSTALL_SH]).returncode == 0
