"""
tests/api_support.py
Lezioni di prova per i test dell'API (fase E): una cartella lezione in una lessons_root
temporanea, con configurazione isolata nella cwd (come tests/golden_support.py).
"""
import os
import shutil

from tests.golden_support import AUDIO_FIXTURE, INFO_YAML, LESSON_NAME, TRANSCRIPT_MD


def isolated_workspace(tmp_path, monkeypatch, lessons_root=True):
    """cwd con config/ ed .env propri; lessons_root dentro tmp_path. Restituisce la root."""
    work = tmp_path / "work"
    (work / "config").mkdir(parents=True)
    (work / ".env").write_text("", encoding="utf-8")
    root = tmp_path / "lessons"
    root.mkdir()
    if lessons_root:
        (work / "config" / "general.yaml").write_text(
            f"telegram:\n  lessons_root: {str(root)!r}\n  default_channel: terminal\n", encoding="utf-8")
    monkeypatch.chdir(work)
    return str(root)


def make_lesson(root: str, name: str = LESSON_NAME) -> str:
    """Cartella già inizializzata con trascritto Markdown (come lo scenario golden)."""
    lesson_dir = os.path.join(root, name)
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML)
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD)
    return lesson_dir


def add_audio(lesson_dir: str, name: str = "lezione.m4a") -> str:
    target = os.path.join(lesson_dir, name)
    shutil.copy(AUDIO_FIXTURE, target)
    return target


def run_mock_pipeline(lesson_dir: str, with_review: bool = True, auto_accept: bool = True):
    """Pipeline in processo, in mock, senza DecisionProvider (come la eseguirebbe il worker)."""
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    options = PipelineOptions(mock=True, with_review=with_review, auto_accept=auto_accept,
                              rename=False, channel="terminal")
    return run_pipeline([lesson_dir], options, RunContext())
