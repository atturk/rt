"""«Mostra file salvati»: raccolta dei file salvati a raffica e preferenza file.mostra-salvati."""
import threading

from rt import window_reveal


def _capture(monkeypatch, enabled=True):
    shown = []
    done = threading.Event()

    def reveal(files):
        shown.append(files)
        done.set()

    monkeypatch.setattr(window_reveal, "_GATHER_SECONDS", 0.05)
    monkeypatch.setattr(window_reveal, "reveal", reveal)
    monkeypatch.setattr(window_reveal, "enabled", lambda: enabled)
    return shown, done


def test_files_saved_together_are_shown_once_in_the_last_folder(tmp_path, monkeypatch):
    shown, done = _capture(monkeypatch)
    other, target = tmp_path / "altra", tmp_path / "scelta"
    other.mkdir(); target.mkdir()
    for p in (other / "a.pdf", target / "b.pdf", target / "c.md"):
        p.write_text("x")
    window_reveal.saved([str(other / "a.pdf")])
    window_reveal.saved([str(target / "b.pdf"), str(target / "c.md"), str(target / "b.pdf")])
    window_reveal.saved([str(target / "manca.pdf")])
    assert done.wait(2)
    assert shown == [[str((target / "b.pdf").resolve()), str((target / "c.md").resolve())]]


def test_preference_off_shows_nothing(tmp_path, monkeypatch):
    shown, done = _capture(monkeypatch, enabled=False)
    (tmp_path / "a.rt").write_text("x")
    window_reveal.saved([str(tmp_path / "a.rt")])
    assert not done.wait(0.3)
    assert shown == []


def test_enabled_reads_preference(monkeypatch):
    from rt.services import preferences_service
    monkeypatch.setattr(preferences_service, "list_preferences", lambda: {})
    assert window_reveal.enabled() is True
    monkeypatch.setattr(preferences_service, "list_preferences", lambda: {"file.mostra-salvati": False})
    assert window_reveal.enabled() is False
