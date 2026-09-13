"""
rt.core.filelock
Lock a file semplice e portabile per scritture concorrenti multi-processo e multi-thread.
Basato su os.O_CREAT | os.O_EXCL | os.O_WRONLY con rilevamento e rimozione di lock stale.
Nessuna dipendenza esterna.
"""
import os
import time
from contextlib import contextmanager
from typing import Generator, Optional


def acquire_file_lock(lock_path: str, retries: int = 30, backoff: float = 0.1, stale_sec: float = 30.0) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    for attempt in range(retries):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > stale_sec:
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
    try:
        yield
    finally:
        release_file_lock(lock_path)
