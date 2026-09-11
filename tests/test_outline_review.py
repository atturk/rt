import os
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.outline_review import confirm_or_revise_outline


@pytest.fixture
def synthetic_outline_lesson(tmp_path):
    lesson_dir = str(tmp_path / "test_lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    
    info_content = """data: '2026-09-08'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: 'test_lesson'
file_audio: test.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)
        
    transcript_content = """---
data: '2026-09-08'
materia: BIOCHIMICA
---

*00:02*
Introduzione alla lezione di biochimica sui lipidi.

*00:20*
I lipidi sono depositati nel tessuto adiposo.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)
        
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    return lesson_dir


def test_terminal_approve_direct(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    with patch("builtins.input", side_effect=["A"]) as mock_input:
        confirm_or_revise_outline(lesson_dir, force_mock=True)
        assert mock_input.call_count == 1


def test_terminal_changes_requested_then_approve(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    # M -> feedback -> A
    with patch("builtins.input", side_effect=["M", "Aggiungi dettagli sulle lipasi", "A"]) as mock_input:
        with patch("rt.pipeline.outline_review.run_outline_revision", wraps=__import__("rt.pipeline.outline", fromlist=["run_outline_revision"]).run_outline_revision) as mock_rev:
            confirm_or_revise_outline(lesson_dir, force_mock=True)
            assert mock_input.call_count == 3
            assert mock_rev.call_count == 1


def test_gating_rule_skips_when_rewrite_valid(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)

    # Con rewrite VALID, input() non deve MAI essere chiamato
    with patch("builtins.input", side_effect=AssertionError("input() non doveva essere chiamato")):
        confirm_or_revise_outline(lesson_dir, force=False, force_mock=True)


def test_gating_rule_bypassed_with_force(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)

    # Con force=True, la conferma viene richiesta comunque
    with patch("builtins.input", side_effect=["A"]) as mock_input:
        confirm_or_revise_outline(lesson_dir, force=True, force_mock=True)
        assert mock_input.call_count == 1
