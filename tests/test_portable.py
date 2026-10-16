"""Primitive di sistema portabili (macOS, Linux, Windows) e parti che prima erano solo Mac."""
import os
import subprocess
import sys

from rt.core import materials
from rt.core.portable import lock_file, pid_alive, unlock_file
from rt.pipeline.setup import sanitize_filename_part


def test_pid_alive():
    assert pid_alive(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not pid_alive(child.pid)
    assert not pid_alive(0)


def test_lock_file_non_blocking_from_another_process(tmp_path):
    path = tmp_path / "x.lock"
    with open(path, "a+") as handle:
        assert lock_file(handle, blocking=False)
        probe = ("import sys; from rt.core.portable import lock_file\n"
                 f"h = open({str(path)!r}, 'a+'); sys.exit(0 if lock_file(h, blocking=False) else 3)")
        assert subprocess.run([sys.executable, "-c", probe], cwd=os.getcwd()).returncode == 3
        unlock_file(handle)
        assert subprocess.run([sys.executable, "-c", probe], cwd=os.getcwd()).returncode == 0


def test_filename_part_is_valid_on_windows():
    assert sanitize_filename_part(' Chimica: acidi/basi "forti"? <1|2>. ') == "Chimica- acidi-basi forti 12"


def test_slides_use_libreoffice_without_quick_look(monkeypatch):
    monkeypatch.setattr(materials.sys, "platform", "win32")
    monkeypatch.setattr(materials.shutil, "which", lambda name: "/opt/lo/soffice" if name == "soffice" else None)
    assert materials._slide_command("a.pptx", "out") == ["/opt/lo/soffice", "--headless", "--convert-to", "pdf",
                                                         "--outdir", "out", "a.pptx"]
    monkeypatch.setattr(materials.shutil, "which", lambda name: None)
    monkeypatch.setattr(materials.os, "name", "posix")
    assert materials._slide_command("a.pptx", "out") is None
