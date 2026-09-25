"""Flusso locale della dashboard web e importazione audio."""
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml
from unittest.mock import patch

from rt.web.app import build_app, main as web_main
from rt.web.data import lesson_audio_html, lesson_audio_path, lesson_card, lesson_preview_html, lesson_title, list_lessons, sidebar_lessons
from rt.web.ingest import ingest_audio
from rt.web.settings import save_lessons_root


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
    assert '<details class="rt-sidebar-group" open><summary>' in sidebar_lessons([lesson], lesson.dir_path)
    assert 'class="rt-sidebar-chevron"' in sidebar_lessons([lesson], lesson.dir_path)
    assert "<h2>Lipidi</h2>" in lesson_card(lesson)
    review_card = lesson_card(replace(lesson, pending_issues=3, cost_total=1.25))
    assert review_card.index('$1.25') < review_card.index('3 issue da valutare')
    assert 'questioni' not in review_card
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


def test_web_audio_remuxes_mislabeled_aac_without_touching_original(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg non disponibile")
    root = tmp_path / "lessons"
    root.mkdir()
    source = tmp_path / "recording.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-f", "adts", str(source)],
        check=True,
    )
    original = source.read_bytes()
    lesson_dir = Path(ingest_audio(str(source), str(root), "2026-09-24", "BIOCHIMICA", "Prova", False))
    lesson = list_lessons(str(root))[0]
    playable = Path(lesson_audio_path(lesson))

    assert original[4:8] != b"ftyp"
    assert playable.read_bytes()[4:8] == b"ftyp"
    assert (lesson_dir / source.name).read_bytes() == original
    assert 'data-chapter="next"' in lesson_audio_html(lesson)
    assert 'preload="metadata"' in lesson_audio_html(lesson)


def test_web_can_configure_lessons_folder_without_rewriting_other_settings(tmp_path, monkeypatch):
    project = tmp_path / "rt"
    config = project / "config"
    config.mkdir(parents=True)
    original = (
        'version: "2.0.0"\n\n'
        'telegram:\n'
        '  # Mantieni questo commento e i topic esistenti.\n'
        '  default_channel: "terminal"\n'
        '  lessons_root: null\n'
        '  topics: {BIOCHIMICA: 42}\n'
        'ui:\n  theme: dark\n'
    )
    general = config / "general.yaml"
    general.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    lessons = tmp_path / "Lezioni di prova"

    saved = save_lessons_root(str(lessons), project)

    assert saved == str(lessons)
    assert lessons.is_dir()
    updated = general.read_text(encoding="utf-8")
    assert "# Mantieni questo commento" in updated
    assert 'topics: {BIOCHIMICA: 42}' in updated
    assert yaml.safe_load(updated)["telegram"]["lessons_root"] == str(lessons)
    assert yaml.safe_load(updated)["ui"]["theme"] == "dark"


def test_web_rejects_lessons_folder_inside_installation(tmp_path, monkeypatch):
    project = tmp_path / "rt"
    (project / "config").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="fuori dall'installazione"):
        save_lessons_root(str(project / "lezioni"), project)
    assert not (project / "lezioni").exists()


def test_web_starts_without_configured_lessons_folder(tmp_path):
    with patch("rt.web.app.lessons_root", return_value=None), \
         patch("rt.web.app.build_app") as build, \
         patch("rt.web.app.configure_logging", return_value=str(tmp_path / "web.log")):
        web_main(["--no-browser"])

    assert build.call_args.args == ("",)
    launch_options = build.return_value.launch.call_args.kwargs
    assert launch_options["server_name"] == "127.0.0.1"
    assert "" not in launch_options["blocked_paths"]


def test_web_first_run_renders_configuration_screen():
    demo = build_app("")
    tabs = next(component for component in demo.config["components"]
                if component["props"].get("elem_id") == "rt-pages")
    assert tabs["props"]["selected"] == "config"


def test_page_reload_shows_phase_models_saved_after_startup(tmp_path, monkeypatch):
    """Gradio riusa i valori iniziali dei componenti: al caricamento della pagina i modelli
    per fase vanno riletti dal disco, altrimenti un refresh sembra annullare le modifiche."""
    from rt.web.connections import add_model, assign_phase, save_connection

    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "general.yaml").write_text("credentials: []\n", encoding="utf-8")
    (config / "outline.yaml").write_text("primary: {}\n", encoding="utf-8")
    save_connection(tmp_path, "Studio", "google", "", ["key-one"])
    demo = build_app("")

    add_model(tmp_path, "Studio", "gemini-test")
    with patch("rt.web.app.PROJECT_ROOT", tmp_path):
        assign_phase(tmp_path, "outline", "Studio", "gemini-test")
        handler = next(block.fn for block in demo.fns.values()
                       if getattr(block, "name", "") == "phase_dropdown_updates")
        updates = handler()

    outline_connection, outline_model = updates[0], updates[len(updates) // 2]
    assert outline_connection["value"] == "Studio"
    assert outline_model["value"] == "gemini-test"
    assert "gemini-test" in outline_model["choices"]
