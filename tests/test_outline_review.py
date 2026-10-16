import os
import pytest
from unittest.mock import patch, MagicMock

from rt.core.models import Outline, OutlineMacro, OutlineUnit
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.outline_review import outline_needs_approval


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


def test_outline_needs_approval_before_rewrite(synthetic_outline_lesson):
    assert outline_needs_approval(synthetic_outline_lesson) is True


def test_gating_rule_skips_when_rewrite_valid(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)
    assert outline_needs_approval(lesson_dir, force=False) is False


def test_gating_rule_bypassed_with_force(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)
    assert outline_needs_approval(lesson_dir, force=True) is True
