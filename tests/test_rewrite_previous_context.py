import json
from unittest.mock import MagicMock

import pytest

from rt.core.models import Draft, DraftUnit
from rt.llm.client import LLMClient, _cache_lesson_prefix
from rt.llm.prompts import build_rewrite_user_prompt, build_rewrite_prefix, build_rewrite_prefix_parts, ReviewFindingList
from rt.pipeline.rewrite import _run_rewrite, save_draft, previous_context_for_usage
from tests.test_checkpointing import multi_unit_lesson  # noqa: F401


def test_prompt_order_reserves_materials_before_previous_units_and_current_id():
    prompt = build_rewrite_user_prompt("2.1", "Current", "[seg_000009] main", ["seg_000009"],
        "before 90 seconds", "after 90 seconds", "outline content", previous_units_text="previous rewritten",
        materials_text="materials content")
    parts = ["outline content", "materials content", "previous rewritten", "ID: 2.1", "before 90 seconds",
             "[seg_000009] main", "after 90 seconds"]
    assert [prompt.index(part) for part in parts] == sorted(prompt.index(part) for part in parts)


def test_single_unit_receives_previous_draft_and_only_90_seconds_after(multi_unit_lesson, monkeypatch):
    from rt.pipeline.outline import load_outline
    from rt.core.segments import load_segments_json, save_segments_json
    from rt.core.lesson_paths import lesson_path
    from rt.core.timestamp import format_timestamp
    units = [u for m in load_outline(multi_unit_lesson).macro_sections for u in m.units]
    # L'ultimo segmento dell'unità successiva va oltre i 90 s dopo l'unità attuale.
    path = lesson_path(multi_unit_lesson, "segments.json")
    segments = load_segments_json(path).segments
    late = segments[-1]
    segments[-1] = late.model_copy(update={"start_seconds": 300.0, "end_seconds": 310.0,
        "start_formatted": format_timestamp(300.0), "end_formatted": format_timestamp(310.0)})
    save_segments_json(segments, path)
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
    by_id = {s.id: s for s in segments}
    within, beyond = by_id[units[2].start_segment_id], by_id[units[2].end_segment_id]
    after = request["prompt"].split("CONTESTO SUCCESSIVO")[1]
    assert within.text_raw in after
    assert beyond.text_raw not in request["prompt"]


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


def test_observed_usage_plus_reserved_output_drops_oldest_unit_only(multi_unit_lesson, monkeypatch):
    captured = []
    original = LLMClient.call_structured
    # Contesto 8000, output riservato 2000: dopo la prima chiamata 3000+1500+2000 entra,
    # dopo la seconda 5000+1500+2000 no (la risposta entra nel prossimo prefisso).
    observed = [{"prompt_tokens": 3000, "completion_tokens": 1500}, {"prompt_tokens": 5000, "completion_tokens": 1500},
                {"prompt_tokens": 5000, "completion_tokens": 1500}]
    def call(self, **kwargs):
        captured.append(kwargs)
        unit = original(self, **kwargs)
        unit.content = f"REWRITTEN {unit.unit_id}"
        self.last_context_model = {"provider": "openrouter", "model": "test/context"}
        self.last_usage = observed[len(captured) - 1]
        self.last_max_tokens = 2000
        return unit
    monkeypatch.setattr(LLMClient, "call_structured", call)
    monkeypatch.setattr("rt.llm.pricing.get_model_context_length", lambda *a: 8000)
    _run_rewrite(multi_unit_lesson, force=True, force_mock=True)
    assert "REWRITTEN 1.1" in captured[1]["prompt_prefix"]
    assert "REWRITTEN 1.1" not in captured[2]["prompt_prefix"]
    assert "REWRITTEN 1.2" in captured[2]["prompt_prefix"]


def test_dropped_units_are_not_reinserted_and_window_advances_one_per_call(multi_unit_lesson, monkeypatch):
    from rt.core.models import OutlineUnit
    from rt.pipeline.outline import load_outline, save_outline
    outline = load_outline(multi_unit_lesson)
    macro = outline.macro_sections[0]
    # Quattro unità: la terza chiamata toglie 1.1, la quarta toglie 1.2 e non rimette 1.1.
    macro.units = [OutlineUnit(id=f"1.{i}", title=f"Unit {i}", start_segment_id=f"seg_00000{i}",
                               end_segment_id=f"seg_00000{i}") for i in range(1, 5)] + [
        OutlineUnit(id="1.5", title="Unit 5", start_segment_id="seg_000005", end_segment_id="seg_000006")]
    save_outline(outline, multi_unit_lesson)
    captured = []
    original = LLMClient.call_structured
    def call(self, **kwargs):
        captured.append(kwargs)
        unit = original(self, **kwargs)
        unit.content = f"REWRITTEN {unit.unit_id}"
        self.last_context_model = {"provider": "openrouter", "model": "test/context"}
        self.last_usage = {"prompt_tokens": 3000 if len(captured) == 1 else 6000, "completion_tokens": 1500}
        self.last_max_tokens = 2000
        return unit
    monkeypatch.setattr(LLMClient, "call_structured", call)
    monkeypatch.setattr("rt.llm.pricing.get_model_context_length", lambda *a: 8000)
    _run_rewrite(multi_unit_lesson, force=True, force_mock=True)
    windows = [[uid for uid in ("1.1", "1.2", "1.3", "1.4") if f"REWRITTEN {uid}" in c["prompt_prefix"]] for c in captured]
    assert windows == [[], ["1.1"], ["1.2"], ["1.3"], ["1.4"]]


@pytest.mark.parametrize("limit,usage,max_output,cut", [
    (100, {"prompt_tokens": 80, "completion_tokens": 21}, None, True),
    (100, {"prompt_tokens": 80, "completion_tokens": 20}, None, False),
    (100, {"prompt_tokens": 60, "completion_tokens": 20}, 21, True),
    (100, {"prompt_tokens": 60, "completion_tokens": 20}, 20, False),
    (None, {"prompt_tokens": 999, "completion_tokens": 999}, 10, False),
    (100, None, 10, False), (100, {"prompt_tokens": 999}, 10, False),
    (100, {"completion_tokens": 999}, 10, False), (100, {"prompt_tokens": True, "completion_tokens": 999}, 10, False),
])
def test_context_pruning_only_with_metadata_and_complete_real_usage(limit, usage, max_output, cut):
    previous = ["oldest", "middle", "newest"]
    assert previous_context_for_usage(previous, limit, usage, max_output) == (previous[1:] if cut else previous)


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
def test_cache_marker_is_on_fixed_block_and_last_previous_unit_without_mutating_fallback(model):
    blocks = [{"type": "text", "text": "outline"}, {"type": "text", "text": "previous one"},
              {"type": "text", "text": "previous two"}]
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": blocks},
                {"role": "user", "content": "current unit"}]
    cached = _cache_lesson_prefix(messages, "openrouter", model, True)
    assert cached[1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert cached[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in b for b in blocks)
    assert all("cache_control" not in b for b in cached[1]["content"][1:-1])


@pytest.mark.parametrize("model", ["anthropic/claude", "google/gemini-2.5-flash"])
def test_growing_prefix_is_split_in_blocks_at_unit_boundaries(model):
    prefix = build_rewrite_prefix_parts("outline", ["Unità 1.1\nuno", "Unità 1.2\ndue", "Unità 1.3\ntre"])
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": str(prefix)},
                {"role": "user", "content": "current unit"}]
    cached = _cache_lesson_prefix(messages, "openrouter", model, True, prefix.parts)
    blocks = cached[1]["content"]
    # Blocco fisso, intestazione, una unità per blocco: stesso testo dei fallback.
    assert "".join(b["text"] for b in blocks) == messages[1]["content"]
    assert len(blocks) == 5
    assert blocks[0]["text"].startswith("CONTESTO GLOBALE") and "Unità" not in blocks[0]["text"]
    assert [b["text"] for b in blocks[2:]] == ["Unità 1.1\nuno\n\n", "Unità 1.2\ndue\n\n", "Unità 1.3\ntre\n\n"]
    marked = [i for i, b in enumerate(blocks) if "cache_control" in b]
    assert marked == [0, 4]
    total = sum(1 for m in cached if isinstance(m["content"], list) for b in m["content"] if "cache_control" in b)
    assert total <= 4
    # Senza unità precedenti resta un solo blocco marcato; testo diverso dalle parti: un blocco.
    only = build_rewrite_prefix_parts("outline")
    single = _cache_lesson_prefix([messages[0], {"role": "user", "content": str(only)}], "openrouter", model, True, only.parts)
    assert single[1]["content"] == [{"type": "text", "text": str(only), "cache_control": {"type": "ephemeral"}}]
    mismatch = _cache_lesson_prefix(messages, "openrouter", model, True, ("other",))
    assert len(mismatch[1]["content"]) == 1


def test_breakpoints_never_exceed_four():
    existing = [{"type": "text", "text": f"m{i}", "cache_control": {"type": "ephemeral"}} for i in range(3)]
    prefix = build_rewrite_prefix_parts("outline", ["a", "b"])
    messages = [{"role": "system", "content": existing}, {"role": "user", "content": str(prefix)}]
    cached = _cache_lesson_prefix(messages, "openrouter", "anthropic/claude", True, prefix.parts)
    assert [i for i, b in enumerate(cached[1]["content"]) if "cache_control" in b] == [len(cached[1]["content"]) - 1]


def test_client_sends_prefix_blocks_only_to_cache_providers(monkeypatch, tmp_path):
    prefix = build_rewrite_prefix_parts("outline", ["Unità 1.1\nuno", "Unità 1.2\ndue"])
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"issues": []}'}, "finish_reason": "stop"}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
        return response
    monkeypatch.setattr("requests.post", post)
    for provider, model, key in (("openrouter", "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY"),
                                 ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY")):
        monkeypatch.setenv(key, "test-key")
        client = LLMClient()
        client.config.pricing = {provider: {model: {"input_per_million": 0, "output_per_million": 0}}}
        client.call_structured(prompt="unit", system_prompt="system", prompt_prefix=prefix, response_model=ReviewFindingList,
                               job_name="review", override_provider=provider, override_model=model, stream=False,
                               constrained_schema=True, show_monitor=False, lesson_dir=str(tmp_path))
    cached, plain = (r["messages"][1]["content"] for r in requests)
    assert [b["text"] for b in cached] == list(prefix.parts)
    assert plain == str(prefix) and type(plain) is str


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
