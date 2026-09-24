"""Flusso locale della dashboard web e importazione audio."""
from pathlib import Path

import pytest

from rt.web.data import lesson_audio_path, lesson_card, lesson_preview_html, lesson_title, list_lessons, sidebar_lessons
from rt.web.ingest import ingest_audio


def test_web_import_creates_lesson_without_overwriting(tmp_path):
    root = tmp_path / "lessons"
    root.mkdir()
    source = tmp_path / "recording.mp3"
    source.write_bytes(b"test audio")

    lesson_dir = Path(ingest_audio(str(source), str(root), "2026-09-24", "BIOCHIMICA", "Lipidi", False))
    assert (lesson_dir / "recording.mp3").read_bytes() == b"test audio"
    assert (lesson_dir / "info.yaml").is_file()
    assert len(list_lessons(str(root))) == 1

    lesson = list_lessons(str(root))[0]
    assert lesson_title(lesson) == "Lipidi"
    assert "BIOCHIMICA" in sidebar_lessons([lesson], lesson.dir_path)
    assert 'aria-current="page"' in sidebar_lessons([lesson], lesson.dir_path)
    assert "<h2>Lipidi</h2>" in lesson_card(lesson)
    exposed_audio = Path(lesson_audio_path(lesson))
    assert exposed_audio.read_bytes() == b"test audio"
    assert not exposed_audio.is_relative_to(root)

    with pytest.raises(ValueError, match="già inizializzata"):
        ingest_audio(str(source), str(root), "2026-09-24", "BIOCHIMICA", "Lipidi", False)
    assert len(list_lessons(str(root))) == 1


def test_dashboard_renders_full_markdown_without_duplicate_title(monkeypatch, tmp_path):
    lesson = type("Lesson", (), {"dir_path": str(tmp_path)})()
    content = "# Titolo duplicato\n\n## Sezione\n\n00:10 <script>unsafe</script>\n\n" + "testo " * 4000
    monkeypatch.setattr("rt.web.data.load_markdown_preview", lambda _: content)

    rendered = lesson_preview_html(lesson)
    assert "Titolo duplicato" not in rendered
    assert "<h2>Sezione</h2>" in rendered
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in rendered
    assert rendered.count("testo") == 4000
