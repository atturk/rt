"""Una trascrizione locale alla volta per processo: il motore usa già tutti i core e tiene
l'audio decodificato in memoria (circa 700 MB per due ore di lezione)."""
import threading
from contextlib import contextmanager

_slot = threading.Semaphore(1)


@contextmanager
def local_transcription_slot(on_wait=None, cancel_token=None):
    if not _slot.acquire(blocking=False):
        if on_wait:
            on_wait("In attesa che finisca un'altra trascrizione")
        while not _slot.acquire(timeout=1.0):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()   # RunCancelled, rt/services/context.py
    try:
        yield
    finally:
        _slot.release()
