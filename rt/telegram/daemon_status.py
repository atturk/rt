"""
rt.telegram.daemon_status
Gestione dello stato e PID del demone Telegram.
"""
import os
import sys
import atexit
import subprocess
from typing import Optional

DEFAULT_PID_PATH = os.path.expanduser("~/.rt/telegram_daemon.pid")


def get_default_pid_path() -> str:
    return DEFAULT_PID_PATH


def write_daemon_pid(pid_path: Optional[str] = None) -> str:
    path = pid_path or DEFAULT_PID_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
    atexit.register(remove_daemon_pid, path)
    return path


def remove_daemon_pid(pid_path: Optional[str] = None) -> None:
    path = pid_path or DEFAULT_PID_PATH
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def is_daemon_running(pid_path: Optional[str] = None) -> bool:
    path = pid_path or DEFAULT_PID_PATH
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return False
        pid = int(content)
    except (ValueError, OSError):
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # Il processo con questo PID non esiste più (PID file orfano)
        return False
    except PermissionError:
        # Il processo esiste ma non abbiamo i permessi per inviare segnali
        return True
    except OSError:
        return False


def get_rt_executable_path() -> str:
    if sys.argv and sys.argv[0]:
        candidate = os.path.abspath(sys.argv[0])
        if os.path.isfile(candidate) and os.path.basename(candidate) == "rt":
            return candidate
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bin_rt = os.path.join(project_root, "bin", "rt")
    if os.path.isfile(bin_rt):
        return bin_rt
    return "rt"


def launch_daemon_in_terminal() -> None:
    rt_path = get_rt_executable_path()
    cmd = f"{rt_path} telegram-daemon"
    script = f'tell application "Terminal" to do script "{cmd}"'
    subprocess.run(["osascript", "-e", script])
