"""Windows: un lock in cancellazione dà accesso negato, e si riprova come se esistesse ancora."""
import os

from rt.core import filelock


def test_access_denied_while_deleting_is_retried_on_windows(tmp_path, monkeypatch):
    real_open, calls = os.open, []

    def flaky_open(path, flags, *args):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "Permission denied", path)
        return real_open(path, flags, *args)

    monkeypatch.setattr(filelock.sys, "platform", "win32")
    monkeypatch.setattr(filelock.os, "open", flaky_open)
    lock = str(tmp_path / "x.lock")
    filelock.acquire_file_lock(lock, backoff=0.001)
    assert len(calls) == 2 and os.path.exists(lock)
