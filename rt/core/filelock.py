"""
rt.core.filelock
Lock a file semplice e portabile per scritture concorrenti multi-processo e multi-thread.
Basato su os.O_CREAT | os.O_EXCL | os.O_WRONLY con rilevamento e rimozione di lock stale.
Nessuna dipendenza esterna.
"""
import os
import json
import socket
import threading
import time
from contextlib import contextmanager
from typing import Generator, Optional


def _expired(lock_path: str, stale_sec: float) -> bool:
    if time.time() - os.path.getmtime(lock_path) <= stale_sec:
        return False
    try:
        with open(lock_path, encoding="utf-8") as file:
            owner = json.load(file)
        if owner["host"] != socket.gethostname():
            return True
        os.kill(int(owner["pid"]), 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except (ValueError, KeyError, TypeError):
        # I vecchi lock non contenevano il proprietario.
        return True


def _renew(lock_path: str, stopped: threading.Event) -> None:
    while not stopped.wait(10):
        try:
            os.utime(lock_path, None)
        except FileNotFoundError:
            return


def acquire_file_lock(lock_path: str, retries: int = 30, backoff: float = 0.1, stale_sec: float = 30.0) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    for attempt in range(retries):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as file:
                json.dump({"pid": os.getpid(), "host": socket.gethostname()}, file)
            return
        except FileExistsError:
            try:
                if _expired(lock_path, stale_sec):
                    try:
                        os.remove(lock_path)  # lock stale, presumibile crash del processo che lo teneva
                    except FileNotFoundError:
                        pass
                    continue
            except FileNotFoundError:
                continue
            time.sleep(backoff * (attempt + 1 if attempt < 5 else 5))
    raise TimeoutError(f"Impossibile acquisire il lock su '{lock_path}' dopo {retries} tentativi.")


def release_file_lock(lock_path: str) -> None:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError:
        pass


@contextmanager
def file_lock(lock_path: str, retries: int = 30, backoff: float = 0.1, stale_sec: float = 30.0) -> Generator[None, None, None]:
    acquire_file_lock(lock_path, retries=retries, backoff=backoff, stale_sec=stale_sec)
    stopped = threading.Event()
    heartbeat = threading.Thread(target=_renew, args=(lock_path, stopped), daemon=True)
    heartbeat.start()
    try:
        yield
    finally:
        stopped.set()
        heartbeat.join()
        release_file_lock(lock_path)
