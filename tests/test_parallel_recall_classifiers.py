import os
import threading
import time
from unittest.mock import patch, MagicMock
import pytest

from rt.core.models import Draft, DraftUnit, RecallQuestionType
from rt.core.config import RTConfig, RecallConfig, JevConfig, ClassifierConfig
from rt.llm.client import LLMClient
from rt.llm.cancel import use_cancel_token, RunCancelled
from rt.pipeline.recall import generate_recall_batch, load_recall_bank
from rt.services import unit_relevance, section_labels
from tests.test_checkpointing import multi_unit_lesson  # noqa: F401


def _setup_multi_group_lesson(tmp_path, num_units=4):
    lesson_dir = str(tmp_path / f"lesson_{num_units}")
    os.makedirs(lesson_dir, exist_ok=True)
    info_content = f"""data: '2026-09-06'
materia: STORIA
argomenti: Storia moderna
cartella: 'lesson_{num_units}'
file_audio: test_audio.m4a
fase_corrente: rewrite
stato: rewrite
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    units = [
        DraftUnit(
            unit_id=f"1.{i}",
            title=f"Unità {i}",
            start_segment_id=f"seg_{i:06d}",
            end_segment_id=f"seg_{i:06d}",
            source_segment_ids=[f"seg_{i:06d}"],
            content=f"Contenuto dettagliato per unità {i} con concetti importanti.",
        )
        for i in range(1, num_units + 1)
    ]
    draft = Draft(units=units)
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        f.write(draft.model_dump_json())

    from rt.pipeline.outline import save_outline
    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    ot_units = [OutlineUnit(id=u.unit_id, title=u.title, start_segment_id=u.start_segment_id, end_segment_id=u.end_segment_id) for u in units]
    outline = Outline(schema_version="1.0", lesson_title="Storia", macro_sections=[OutlineMacro(id="1", title="M1", units=ot_units)])
    save_outline(outline, lesson_dir)
    return lesson_dir


def test_recall_parallel_generation_speedup(tmp_path, monkeypatch):
    lesson_dir = _setup_multi_group_lesson(tmp_path, num_units=4)
    cfg = RTConfig(recall=RecallConfig(parallel_units=4, votes_enabled=False))
    monkeypatch.setattr("rt.pipeline.recall.load_config", lambda: cfg)

    call_count = 0
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_call_structured(self, prompt, system_prompt, response_model, **kwargs):
        nonlocal call_count, active, max_active
        with lock:
            call_count += 1
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        uid = kwargs.get("unit_id", "1.1")
        return response_model.model_validate({
            "questions": [{
                "type": "mirata",
                "question_text": f"Qual è il concetto importante di questa unità {uid} e contenuto?",
            }]
        })

    with patch.object(LLMClient, "call_structured", slow_call_structured):
        results = generate_recall_batch(
            lesson_dir, RecallQuestionType.MIRATA, count=None, few_shot_examples=[], force_mock=False
        )

    assert len(results) == 4
    assert call_count == 4
    # Le chiamate si sovrappongono: si misura la concorrenza, non il tempo, che sui runner
    # macOS carichi supera qualsiasi soglia (0.49 s contro 0.45 il 2 novembre).
    assert max_active >= 2


def test_recall_parallel_unique_question_ids(tmp_path, monkeypatch):
    lesson_dir = _setup_multi_group_lesson(tmp_path, num_units=6)
    cfg = RTConfig(recall=RecallConfig(parallel_units=4, votes_enabled=False))
    monkeypatch.setattr("rt.pipeline.recall.load_config", lambda: cfg)

    def multi_question_call(self, prompt, system_prompt, response_model, **kwargs):
        uid = kwargs.get("unit_id", "1.1")
        return response_model.model_validate({
            "questions": [
                {"type": "mirata", "question_text": f"Qual è il concetto importante di questa unità {uid} e contenuto?"},
                {"type": "mirata", "question_text": f"Descrivi il concetto importante dell'unità {uid} e contenuto?"},
            ]
        })

    with patch.object(LLMClient, "call_structured", multi_question_call):
        results = generate_recall_batch(
            lesson_dir, RecallQuestionType.MIRATA, count=None, few_shot_examples=[], force_mock=False
        )

    ids = [q.id for q in results]
    assert len(ids) == len(set(ids))
    assert len(ids) == 12


def test_recall_cancellation_stops_new_calls(tmp_path, monkeypatch):
    lesson_dir = _setup_multi_group_lesson(tmp_path, num_units=8)
    cfg = RTConfig(recall=RecallConfig(parallel_units=2, votes_enabled=False))
    monkeypatch.setattr("rt.pipeline.recall.load_config", lambda: cfg)

    class MockToken:
        def __init__(self):
            self.cancelled = False
        def on_cancel(self, cb):
            return lambda: None

    token = MockToken()
    calls = []

    def cancelling_call(self, prompt, system_prompt, response_model, **kwargs):
        calls.append(kwargs.get("unit_id"))
        time.sleep(0.05)
        # Cancel when first call finishes
        token.cancelled = True
        return response_model.model_validate({
            "questions": [{"type": "mirata", "question_text": f"Q for {kwargs.get('unit_id')}?"}]
        })

    with use_cancel_token(token):
        with patch.object(LLMClient, "call_structured", cancelling_call):
            with pytest.raises(RunCancelled):
                generate_recall_batch(
                    lesson_dir, RecallQuestionType.MIRATA, count=None, few_shot_examples=[], force_mock=False
                )

    # 8 total units, parallel=2. After cancelling, no new calls should start.
    assert len(calls) <= 3


def test_unit_relevance_parallel_speedup(tmp_path, monkeypatch):
    lesson_dir = _setup_multi_group_lesson(tmp_path, num_units=4)
    cfg = RTConfig(
        classifier=ClassifierConfig(
            relevance=JevConfig(relevance_model="openai/test", relevance_mode="active", credential="test_cred")
        )
    )
    monkeypatch.setattr("rt.services.unit_relevance.load_config", lambda: cfg)

    from rt.llm.jev_client import JevResponse, JevAnswer

    call_count = 0
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_call_jev(*args, **kwargs):
        nonlocal call_count, active, max_active
        with lock:
            call_count += 1
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return JevResponse(answers={"relevance": JevAnswer(type="score", score=2, confidence=0.9)})

    with patch("rt.llm.jev_client.call_jev", slow_call_jev):
        result = unit_relevance.refresh(lesson_dir, force=True, force_mock=False)

    assert len(result) == 4
    assert call_count == 4
    # Le chiamate si sovrappongono (concorrenza, non tempo: i runner carichi sforano le soglie).
    assert max_active >= 2
    # Order must match original units
    assert list(result.keys()) == ["1.1", "1.2", "1.3", "1.4"]


def test_section_labels_parallel_speedup(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path / "lesson_sections")
    os.makedirs(lesson_dir, exist_ok=True)
    info_content = """data: '2026-09-06'
materia: STORIA
argomenti: Storia moderna
cartella: 'lesson_sections'
file_audio: test_audio.m4a
fase_corrente: rewrite
stato: rewrite
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    from rt.pipeline.outline import save_outline
    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    from rt.core.config import CustomQuestionType
    units = [
        DraftUnit(unit_id=f"{i}.1", title=f"U{i}", start_segment_id=f"seg_{i}", end_segment_id=f"seg_{i}",
                  source_segment_ids=[f"seg_{i}"], content=f"Contenuto sezione {i}")
        for i in range(1, 5)
    ]
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        f.write(Draft(units=units).model_dump_json())

    macros = [OutlineMacro(id=str(i), title=f"Macro {i}", units=[OutlineUnit(id=f"{i}.1", title=f"U{i}", start_segment_id=f"seg_{i}", end_segment_id=f"seg_{i}")]) for i in range(1, 5)]
    save_outline(Outline(schema_version="1.0", lesson_title="Storia", macro_sections=macros), lesson_dir)

    custom_type = CustomQuestionType(id="tipo-test", nome="Tipo Test", materie=["storia"], cerca="Cerca qualcosa", chiedi="Domanda test?")
    cfg = RTConfig(
        recall=RecallConfig(custom_types=[custom_type]),
        classifier=ClassifierConfig(
            section_labels=JevConfig(relevance_model="openai/test", relevance_mode="active", credential="test_cred")
        ),
    )
    monkeypatch.setattr("rt.services.section_labels.load_config", lambda: cfg)
    monkeypatch.setattr("rt.services.custom_question_types.load_config", lambda: cfg)

    from rt.llm.jev_client import JevResponse, JevAnswer

    call_count = 0
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_call_jev(*args, **kwargs):
        nonlocal call_count, active, max_active
        with lock:
            call_count += 1
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return JevResponse(answers={"tipo": JevAnswer(type="choice", choice="tipo-test", confidence=0.8, probabilities={"tipo-test": 0.8, "nessuno": 0.2})})

    with patch("rt.llm.jev_client.call_jev", slow_call_jev):
        result = section_labels.refresh(lesson_dir, force=True, force_mock=False, explicit=True)

    assert len(result) == 4
    assert call_count == 4
    # Le chiamate si sovrappongono (concorrenza, non tempo: i runner carichi sforano le soglie).
    assert max_active >= 2
    assert list(result.keys()) == ["1", "2", "3", "4"]
