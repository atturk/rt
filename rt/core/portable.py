"""
rt.core.portable
Piccole primitive di sistema che su macOS/Linux e su Windows funzionano in modo diverso:
lock esclusivo su un file aperto e controllo che un processo sia ancora vivo.
"""
import errno
import os
from typing import IO

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_BUSY = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


def lock_file(handle: IO, blocking: bool = True) -> bool:
    """Lock esclusivo sul file aperto. Con blocking=False restituisce False se è già preso.
    Il sistema operativo lo rilascia da solo alla chiusura del file o alla morte del processo."""
    try:
        if os.name == "nt":
            handle.seek(0)
            # LK_LOCK riprova per circa 10 secondi e poi fallisce: si ripete finché non lo prende
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                    return True
                except OSError as exc:
                    if not blocking or exc.errno not in _BUSY:
                        raise
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return True
    except OSError as exc:
        if not blocking and exc.errno in _BUSY:
            return False
        raise


def unlock_file(handle: IO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pid_alive(pid: int) -> bool:
    """Il processo esiste ancora? Su Windows os.kill(pid, 0) non controlla: manda CTRL+C."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # accesso negato: il processo esiste
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
