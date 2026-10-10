"""Scritture di una lezione: lock fra processi, rientrante nello stesso thread."""
import os
import threading
from contextlib import contextmanager
from functools import wraps
from inspect import signature
from rt.core.filelock import file_lock
from rt.storage import fs

_local = threading.local()


@contextmanager
def lesson_lock(lesson_dir):
    path = fs.lock_path(os.path.join(os.path.realpath(lesson_dir), ".rt.lock"))
    held = getattr(_local, "held", set())
    if path in held:
        yield
        return
    _local.held = held
    with file_lock(path, retries=100, backoff=0.05):
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)


def lesson_locked(function):
    """Protegge anche la lettura che precede la scrittura, per evitare aggiornamenti persi."""
    parameters = signature(function)
    @wraps(function)
    def locked(*args, **kwargs):
        lesson_dir = parameters.bind(*args, **kwargs).arguments["lesson_dir"]
        with lesson_lock(lesson_dir):
            return function(*args, **kwargs)
    return locked
