"""
rt.telegram.daemon_status
Gestione dello stato e PID del demone Telegram.
"""
import os
import sys
import atexit
import subprocess
import errno
from typing import Optional

if os.name == "nt":
    import msvcrt
else:
    import fcntl

DEFAULT_PID_PATH = os.path.expanduser("~/.rt/telegram_daemon.pid")
_pid_handle = None


def get_default_pid_path() -> str:
    return DEFAULT_PID_PATH


def write_daemon_pid(pid_path: Optional[str] = None) -> str:
    global _pid_handle
    path = pid_path or DEFAULT_PID_PATH
    if _pid_handle is not None:
        raise RuntimeError("Il bot Telegram è già in esecuzione.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise RuntimeError("Il bot Telegram è già in esecuzione.") from None
        raise
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    os.fsync(handle.fileno())
    _pid_handle = handle
    atexit.register(remove_daemon_pid, path)
    return path


def remove_daemon_pid(pid_path: Optional[str] = None) -> None:
    global _pid_handle
    path = pid_path or DEFAULT_PID_PATH
    try:
        if _pid_handle is not None and get_daemon_pid(path) == os.getpid():
            # Mantieni l'inode su cui è preso il lock: rimuoverlo aprirebbe
            # una finestra in cui due processi bloccano file diversi.
            _pid_handle.seek(0)
            _pid_handle.truncate()
            _pid_handle.flush()
    except OSError:
        pass
    finally:
        if _pid_handle is not None:
            _pid_handle.close()
            _pid_handle = None


def get_daemon_pid(pid_path: Optional[str] = None) -> Optional[int]:
    path = pid_path or DEFAULT_PID_PATH
    pid = None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        os.kill(pid, 0)
        return pid
    except PermissionError:
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, OSError):
        return None


def is_daemon_running(pid_path: Optional[str] = None) -> bool:
    return get_daemon_pid(pid_path) is not None


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


def start_daemon_detached(cwd: str, logfile: str, wait_seconds: float = 5.0) -> int:
    """Avvia 'rt telegram-daemon' in una sessione propria, scollegata da chi lo avvia (API,
    web): il bot sopravvive alla chiusura del processo che l'ha lanciato. Il lock del PID
    file impedisce i duplicati. Restituisce il PID o solleva RuntimeError."""
    import time
    running = get_daemon_pid()
    if running is not None:
        return running
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    with open(logfile, "a", encoding="utf-8") as output:
        os.chmod(logfile, 0o600)
        process = subprocess.Popen(
            [sys.executable, "-m", "rt.cli", "telegram-daemon"], cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        pid = get_daemon_pid()
        if pid is not None:
            return pid
        if process.poll() is not None:
            raise RuntimeError(f"Il bot non si è avviato. Controlla {logfile}.")
        time.sleep(0.1)
    raise RuntimeError(f"Il bot non ha confermato l'avvio. Controlla {logfile}.")


def stop_daemon(wait_seconds: float = 10.0) -> bool:
    """Chiede al bot di terminare (SIGTERM) e attende. False se non era in esecuzione."""
    import signal
    import time
    pid = get_daemon_pid()
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline and get_daemon_pid() is not None:
        time.sleep(0.1)
    return True
