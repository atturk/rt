import json
from unittest.mock import MagicMock

import pytest

from rt.core.models import Draft, DraftUnit
from rt.llm.client import LLMClient, _cache_lesson_prefix
from rt.llm.prompts import build_rewrite_user_prompt, build_rewrite_prefix, ReviewFindingList
from rt.pipeline.rewrite import _run_rewrite, save_draft, previous_context_for_usage
from tests.test_checkpointing import multi_unit_lesson  # noqa: F401


def test_prompt_order_reserves_materials_before_previous_units_and_current_id():
    prompt = build_rewrite_user_prompt("2.1", "Current", "[seg_000009] main", ["seg_000009"],
        "before 90 seconds", "after 90 seconds", "outline content", previous_units_text="previous rewritten",
        materials_text="materials content")
    parts = ["outline content", "materials content", "previous rewritten", "ID: 2.1", "before 90 seconds",
             "[seg_000009] main", "after 90 seconds"]
    assert [prompt.index(part) for part in parts] == sorted(prompt.index(part) for part in parts)


def test_single_unit_receives_previous_draft_and_no_future_transcript(multi_unit_lesson, monkeypatch):
    from rt.pipeline.outline import load_outline
    units = [u for m in load_outline(multi_unit_lesson).macro_sections for u in m.units]
    draft = Draft(units=[DraftUnit(unit_id=u.id, title=u.title, start_segment_id=u.start_segment_id,
        end_segment_id=u.end_segment_id, source_segment_ids=[u.start_segment_id, u.end_segment_id],
        content=f"REWRITTEN {u.id}") for u in units])
    save_draft(draft, multi_unit_lesson)
    captured = []
    def call(self, **kwargs):
        captured.append(kwargs)
        return draft.units[1].model_copy(deep=True)
    monkeypatch.setattr(LLMClient, "call_structured", call)
    result = _run_rewrite(multi_unit_lesson, target_unit_id=units[1].id, force=True)
    assert result["processed_units"] == 1
    request = captured[0]
    assert "REWRITTEN " + units[0].id in request["prompt_prefix"]
    assert "REWRITTEN " + units[2].id not in request["prompt_prefix"]
    assert "ID: " + units[1].id not in request["prompt_prefix"]
    from rt.core.segments import load_segments_json
    from rt.core.lesson_paths import lesson_path
    segments = load_segments_json(lesson_path(multi_unit_lesson, "segments.json")).segments
    future = [s for s in segments if s.id in (units[2].start_segment_id, units[2].end_segment_id)]
    assert all(s.text_raw not in request["prompt"] for s in future)


def test_sequential_rewrite_prefix_grows_in_outline_order(multi_unit_lesson, monkeypatch):
    captured = []
    original = LLMClient.call_structured
    def call(self, **kwargs):
        captured.append(kwargs)
        unit = original(self, **kwargs)
        unit.content = f"REWRITTEN {unit.unit_id}"
        return unit
    monkeypatch.setattr(LLMClient, "call_structured", call)
    _run_rewrite(multi_unit_lesson, force=True, force_mock=True)
    assert len(captured) == 3
    assert "REWRITTEN" not in captured[0]["prompt_prefix"]
    assert "REWRITTEN 1.1" in captured[1]["prompt_prefix"]
    prefix = captured[2]["prompt_prefix"]
    assert prefix.index("REWRITTEN 1.1") < prefix.index("REWRITTEN 1.2")


def test_observed_overflow_drops_oldest_context_and_does_not_reinsert_it(multi_unit_lesson, monkeypatch):
    captured = []
    original = LLMClient.call_structured
    def call(self, **kwargs):
        captured.append(kwargs)
        unit = original(self, **kwargs)
        unit.content = f"REWRITTEN {unit.unit_id}"
        self.last_context_model = {"provider": "openrouter", "model": "test/context"}
        self.last_usage = {"prompt_tokens": 100 if len(captured) == 1 else 1, "completion_tokens": 1}
        return unit
    monkeypatch.setattr(LLMClient, "call_structured", call)
    monkeypatch.setattr("rt.llm.pricing.get_model_context_length", lambda *a: 50)
    _run_rewrite(multi_unit_lesson, force=True, force_mock=True)
    assert "REWRITTEN" not in captured[1]["prompt_prefix"]
    assert "REWRITTEN 1.1" not in captured[2]["prompt_prefix"]
    assert "REWRITTEN 1.2" in captured[2]["prompt_prefix"]


@pytest.mark.parametrize("limit,usage,cut", [
    (100, {"prompt_tokens": 80, "completion_tokens": 21}, True),
    (100, {"prompt_tokens": 80, "completion_tokens": 20}, False),
    (None, {"prompt_tokens": 999, "completion_tokens": 999}, False),
    (100, None, False), (100, {"prompt_tokens": 999}, False),
    (100, {"completion_tokens": 999}, False), (100, {"prompt_tokens": True, "completion_tokens": 999}, False),
])
def test_context_pruning_only_with_metadata_and_complete_real_usage(limit, usage, cut):
    previous = ["oldest", "newest"]
    assert previous_context_for_usage(previous, limit, usage) == ([] if cut else previous)


def test_metadata_context_length_uses_same_model_fetch_as_prices(monkeypatch):
    import rt.llm.pricing as pricing
    monkeypatch.setattr(pricing, "_OPENROUTER_DYNAMIC_CACHE", {})
    monkeypatch.setattr(pricing, "_OPENROUTER_CONTEXT_LENGTHS", {})
    monkeypatch.setattr(pricing, "_OPENROUTER_DYNAMIC_FETCHED", False)
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": [{"id": "test/metadata", "context_length": 12345,
        "pricing": {"prompt": "0.00001", "completion": "0.00002"}}, {"id": "test/no-price", "context_length": 5678}]}
    get = MagicMock(return_value=response)
    monkeypatch.setattr("requests.get", get)
    assert pricing.get_model_context_length("openrouter", "~test/metadata") == 12345
    assert pricing.get_model_context_length("openrouter", "test/no-price") == 5678
    assert pricing.get_model_context_length("openrouter", "missing") is None
    assert pricing.get_model_context_length("deepseek", "test/metadata") is None
    assert get.call_count == 1


@pytest.mark.parametrize("model", ["anthropic/claude", "google/gemini-2.5-flash"])
def test_cache_marker_is_on_last_previous_unit_without_mutating_fallback(model):
    blocks = [{"type": "text", "text": "outline"}, {"type": "text", "text": "previous one"},
              {"type": "text", "text": "previous two"}]
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": blocks},
                {"role": "user", "content": "current unit"}]
    cached = _cache_lesson_prefix(messages, "openrouter", model, True)
    assert cached[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in b for b in blocks)
    assert all("cache_control" not in b for b in cached[1]["content"][:-1])


@pytest.mark.parametrize("stream", [False, True])
def test_client_exposes_observed_usage_and_actual_model(monkeypatch, tmp_path, stream):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    response = MagicMock(status_code=200)
    response.json.return_value = {"model": "test/actual", "choices": [{"message": {"content": '{"issues": []}'},
                                "finish_reason": "stop"}], "usage": usage}
    response.iter_lines.return_value = ["data: " + json.dumps({"model": "test/actual", "choices": [
        {"delta": {"content": '{"issues": []}'}, "finish_reason": "stop"}], "usage": usage}), "data: [DONE]"]
    monkeypatch.setattr("requests.post", lambda *a, **kw: response)
    client = LLMClient()
    client.config.pricing = {"openrouter": {"test/actual": {"input_per_million": 0, "output_per_million": 0}}}
    client.call_structured(prompt="unit", system_prompt="system", prompt_prefix="lesson", response_model=ReviewFindingList,
                          job_name="review", override_provider="openrouter", override_model="test/requested", stream=stream,
                          constrained_schema=True, show_monitor=False, lesson_dir=str(tmp_path))
    assert client.last_usage == usage
    assert client.last_context_model == {"provider": "openrouter", "model": "test/actual"}
