import os
import time
from unittest.mock import MagicMock
import pytest

from rt.core.models import Outline, OutlineMacro, OutlineUnit, Draft, DraftUnit
from rt.core.config import RTConfig, RewriteConfig
from rt.llm.client import LLMClient
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import save_outline
from rt.pipeline.rewrite import _run_rewrite, load_draft


@pytest.fixture
def two_macro_lesson(tmp_path):
    lesson_dir = str(tmp_path / "[2026-09-06] TEST - Two Macro Lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-06'
materia: BIOCHIMICA
argomenti: Lipidi e metabolismo energetico
cartella: '[2026-09-06] TEST - Two Macro Lesson'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    transcript_content = """---
data: '2026-09-06'
materia: BIOCHIMICA
---

*00:02*
Segmento uno per prima unità.

*00:14*
Segmento due per prima unità.

*00:22*
Segmento tre per seconda unità.

*00:30*
Segmento quattro per terza unità macro due.

*00:45-00:55*
Segmento cinque per terza unità macro due.

*01:00-01:10*
Segmento sei per quarta unità macro due.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)

    run_prepare(lesson_dir)

    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Due Macro",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Capitolo 1",
                units=[
                    OutlineUnit(id="1.1", title="U1.1", start_segment_id="seg_000001", end_segment_id="seg_000002"),
                    OutlineUnit(id="1.2", title="U1.2", start_segment_id="seg_000003", end_segment_id="seg_000003"),
                ],
            ),
            OutlineMacro(
                id="2",
                title="Capitolo 2",
                units=[
                    OutlineUnit(id="2.1", title="U2.1", start_segment_id="seg_000004", end_segment_id="seg_000005"),
                    OutlineUnit(id="2.2", title="U2.2", start_segment_id="seg_000006", end_segment_id="seg_000006"),
                ],
            ),
        ],
    )
    save_outline(outline, lesson_dir)
    return lesson_dir


def test_macro_context_mode_limits_context_to_same_macro(two_macro_lesson, monkeypatch):
    test_cfg = RTConfig(rewrite=RewriteConfig(context_mode="macro", parallel_macros=2))
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: test_cfg)

    captured = {}
    original = LLMClient.call_structured

    def fake_call(self, **kwargs):
        unit_id = kwargs.get("unit_id", "")
        # Extract the bare unit id (e.g. "1.1" from "unit 1/4 (1.1: U1.1)")
        for uid in ("1.1", "1.2", "2.1", "2.2"):
            if uid in unit_id:
                captured[uid] = kwargs.get("prompt_prefix", "")
                break
        res = original(self, **kwargs)
        res.content = f"Rielaborato {res.unit_id}"
        return res

    monkeypatch.setattr(LLMClient, "call_structured", fake_call)

    _run_rewrite(two_macro_lesson, force=True, force_mock=True)

    assert "1.1" in captured
    assert "1.2" in captured
    assert "2.1" in captured
    assert "2.2" in captured

    # In Macro 1:
    assert "Rielaborato 1.1" not in captured["1.1"]
    assert "Rielaborato 1.1" in captured["1.2"]
    assert "Rielaborato 2" not in captured["1.2"]

    # In Macro 2: context must ONLY contain units of Macro 2
    assert "Rielaborato 1.1" not in captured["2.1"]
    assert "Rielaborato 1.2" not in captured["2.1"]
    assert "Rielaborato 2.1" not in captured["2.1"]

    assert "Rielaborato 1.1" not in captured["2.2"]
    assert "Rielaborato 1.2" not in captured["2.2"]
    assert "Rielaborato 2.1" in captured["2.2"]


def test_macro_context_mode_runs_in_parallel(two_macro_lesson, monkeypatch):
    test_cfg = RTConfig(rewrite=RewriteConfig(context_mode="macro", parallel_macros=2))
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: test_cfg)

    original = LLMClient.call_structured

    def slow_call(self, **kwargs):
        time.sleep(0.2)
        return original(self, **kwargs)

    monkeypatch.setattr(LLMClient, "call_structured", slow_call)

    start = time.monotonic()
    _run_rewrite(two_macro_lesson, force=True, force_mock=True)
    elapsed = time.monotonic() - start

    # 4 units in 2 macros of 2 units each:
    # Macro 1: 2 * 0.2 = 0.4s
    # Macro 2: 2 * 0.2 = 0.4s
    # In parallel: ~0.4s - 0.55s. Sequential would be >= 0.8s.
    assert elapsed < 0.7


def test_checkpoint_and_resume_halfway(two_macro_lesson, monkeypatch):
    test_cfg = RTConfig(rewrite=RewriteConfig(context_mode="macro", parallel_macros=1))
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: test_cfg)

    original = LLMClient.call_structured
    first_run = True

    def fail_on_last(self, **kwargs):
        nonlocal first_run
        unit_id = kwargs.get("unit_id", "")
        if first_run and "2.2" in unit_id:
            raise RuntimeError("Interruzione simulata su 2.2")
        res = original(self, **kwargs)
        res.content = f"Rielaborato {res.unit_id}"
        return res

    monkeypatch.setattr(LLMClient, "call_structured", fail_on_last)

    with pytest.raises(RuntimeError):
        _run_rewrite(two_macro_lesson, force=True, force_mock=True)

    draft_mid = load_draft(two_macro_lesson)
    mid_ids = [u.unit_id for u in draft_mid.units]
    assert mid_ids == ["1.1", "1.2", "2.1"]

    # Resume without failing
    first_run = False
    captured = {}

    def resume_call(self, **kwargs):
        unit_id = kwargs.get("unit_id", "")
        for uid in ("1.1", "1.2", "2.1", "2.2"):
            if uid in unit_id:
                captured[uid] = kwargs.get("prompt_prefix", "")
                break
        res = original(self, **kwargs)
        res.content = f"Rielaborato {res.unit_id}"
        return res

    monkeypatch.setattr(LLMClient, "call_structured", resume_call)
    _run_rewrite(two_macro_lesson, force=False, force_mock=True)

    # Only 2.2 should have been called
    assert list(captured.keys()) == ["2.2"]
    # And 2.2's context contains 2.1 from the checkpoint, and not 1.1/1.2
    assert "Rielaborato 2.1" in captured["2.2"]
    assert "Rielaborato 1.1" not in captured["2.2"]
    assert "Rielaborato 1.2" not in captured["2.2"]

    final_draft = load_draft(two_macro_lesson)
    assert [u.unit_id for u in final_draft.units] == ["1.1", "1.2", "2.1", "2.2"]


def test_all_context_mode_includes_all_previous_units(two_macro_lesson, monkeypatch):
    test_cfg = RTConfig(rewrite=RewriteConfig(context_mode="all", parallel_macros=2))
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: test_cfg)

    captured = {}
    original = LLMClient.call_structured

    def fake_call(self, **kwargs):
        unit_id = kwargs.get("unit_id", "")
        for uid in ("1.1", "1.2", "2.1", "2.2"):
            if uid in unit_id:
                captured[uid] = kwargs.get("prompt_prefix", "")
                break
        res = original(self, **kwargs)
        res.content = f"Rielaborato {res.unit_id}"
        return res

    monkeypatch.setattr(LLMClient, "call_structured", fake_call)

    _run_rewrite(two_macro_lesson, force=True, force_mock=True)

    # In "all" mode, 2.1 receives 1.1 and 1.2
    assert "Rielaborato 1.1" in captured["2.1"]
    assert "Rielaborato 1.2" in captured["2.1"]

    # 2.2 receives 1.1, 1.2 and 2.1
    assert "Rielaborato 1.1" in captured["2.2"]
    assert "Rielaborato 1.2" in captured["2.2"]
    assert "Rielaborato 2.1" in captured["2.2"]
