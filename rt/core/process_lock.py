"""
rt.core.process_lock
Lock di lavorazione per lezione tra processi: chi esegue la pipeline su una lezione (worker
della coda o 'rt run' in processo) tiene un flock su <lezione>/.rt.job.lock per tutta la
durata del lavoro. A differenza del lock breve di rt.core.filelock, il sistema operativo lo
rilascia da solo se il processo muore, quindi non esistono lock stale.
"""
import os
from contextlib import contextmanager
from typing import Iterator

from rt.core.portable import lock_file, unlock_file

LOCK_NAME = ".rt.job.lock"


class LessonBusy(RuntimeError):
    """Un altro processo sta già lavorando sulla stessa lezione."""


def lesson_lock_path(lesson_dir: str) -> str:
    from rt.storage import fs
    return fs.lock_path(os.path.join(lesson_dir, LOCK_NAME))


@contextmanager
def lesson_work_lock(lesson_dir: str) -> Iterator[None]:
    """Lock esclusivo non bloccante sulla lezione; LessonBusy se è già preso."""
    handle = open(lesson_lock_path(lesson_dir), "a+")
    try:
        if not lock_file(handle, blocking=False):
            raise LessonBusy(f"La lezione è già in lavorazione: {os.path.basename(os.path.abspath(lesson_dir))}")
        try:
            yield
        finally:
            unlock_file(handle)
    finally:
        handle.close()
