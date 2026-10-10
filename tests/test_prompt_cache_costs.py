"""V4d: cache del prefisso, conteggi, costi e persistenza delle chiamate."""
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from rt.db.models import LlmCall
from rt.db.session import session_scope
from rt.llm.client import LLMClient, _cache_lesson_prefix
from rt.llm.pricing import calculate_cost
from rt.llm.prompts import ReviewFindingList
from rt.llm.telemetry import current_telemetry
from rt.llm.usage import cached_prompt_tokens


@pytest.mark.parametrize("usage,expected", [({"prompt_cache_hit_tokens": 800}, 800),
    ({"prompt_tokens_details": {"cached_tokens": 800}}, 800), ({}, None),
    ({"prompt_cache_hit_tokens": 0}, 0), ({"prompt_cache_hit_tokens": True}, None)])
def test_usage_cache_tokens(usage, expected):
    assert cached_prompt_tokens(usage) == expected


def test_cache_cost_known_unknown_and_clamped():
    pricing = {"test": {"model": {"input_per_million": 10, "cached_input_per_million": 1, "output_per_million": 20}}}
    assert calculate_cost("test", "model", 1000, 100, custom_pricing=pricing, cached_input_tokens=800) == 0.0048
    assert calculate_cost("test", "model", 1000, 100, custom_pricing=pricing, cached_input_tokens=2000) == 0.003
    del pricing["test"]["model"]["cached_input_per_million"]
    assert calculate_cost("test", "model", 1000, 100, custom_pricing=pricing, cached_input_tokens=800) == 0.012


def test_openrouter_dynamic_price_includes_cache_read_discount(monkeypatch):
    monkeypatch.setattr("rt.llm.pricing._OPENROUTER_DYNAMIC_CACHE", {})
    monkeypatch.setattr("rt.llm.pricing._OPENROUTER_DYNAMIC_FETCHED", False)
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": [{"id": "test/cache-model", "pricing": {
        "prompt": "0.00001", "completion": "0.00002", "input_cache_read": "0.000001"}}]}
    monkeypatch.setattr("requests.get", lambda *a, **kw: response)
    assert calculate_cost("openrouter", "test/cache-model", 1000, 100, cached_input_tokens=800) == 0.0048


@pytest.mark.parametrize("provider,model,marked", [("openrouter", "anthropic/claude-3.5-sonnet", True),
    ("openrouter", "google/gemini-2.5-flash", True), ("openrouter", "deepseek/deepseek-chat", False),
    ("deepseek", "deepseek-chat", False), ("google", "gemini-2.5-flash", False)])
def test_only_supported_lesson_prefix_is_cached(provider, model, marked):
    messages = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "lezione"},
                {"role": "user", "content": "unità\nextra"}]
    result = _cache_lesson_prefix(messages, provider, model, True)
    assert messages[1]["content"] == "lezione"
    assert result[0] == messages[0] and result[2] == messages[2]
    assert result[1]["content"] == ([{"type": "text", "text": "lezione", "cache_control": {"type": "ephemeral"}}] if marked else "lezione")


@pytest.mark.parametrize("provider,model,key,cache_usage", [("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY", {"prompt_cache_hit_tokens": 800}),
    ("openrouter", "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY", {"prompt_tokens_details": {"cached_tokens": 800}})])
@pytest.mark.parametrize("stream", [False, True])
def test_cache_tokens_and_discount_are_saved_in_call_and_database(tmp_path, monkeypatch, rt_db, provider, model, key, cache_usage, stream):
    monkeypatch.setenv(key, "test-key")
    lesson = tmp_path / "lezione"
    lesson.mkdir()
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100, **cache_usage}
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"issues": []}'}, "finish_reason": "stop"}], "usage": usage}
        response.iter_lines.return_value = [
            "data: " + json.dumps({"choices": [{"delta": {"content": '{"issues": []}'}, "finish_reason": "stop"}], "usage": usage}),
            "data: [DONE]",
        ]
        return response
    monkeypatch.setattr("requests.post", post)
    client = LLMClient()
    client.config.pricing = {provider: {model: {"input_per_million": 10, "cached_input_per_million": 1, "output_per_million": 20}}}
    client.call_structured(prompt="unità\nextra", prompt_prefix="lezione", system_prompt="sistema", response_model=ReviewFindingList,
        job_name="review", override_provider=provider, override_model=model, stream=stream, show_monitor=False,
        lesson_dir=str(lesson), constrained_schema=True)
    record = current_telemetry().get_last()
    assert record.cached_input_tokens == 800
    assert record.estimated_cost == 0.0048
    with session_scope(rt_db) as session:
        call = session.scalar(select(LlmCall))
        assert call.cached_input_tokens == call.payload["cached_input_tokens"] == 800
        assert call.estimated_cost == 0.0048
    from rt.pipeline.cost import compute_lesson_cost
    assert compute_lesson_cost(str(lesson))["total_estimated_cost_usd"] == 0.0048
    content = requests[0]["messages"][1]["content"]
    if provider == "openrouter":
        assert content[0]["cache_control"] == {"type": "ephemeral"}
    else:
        assert content == "lezione"


def test_import_historical_cache_usage_preserves_counts(tmp_path, rt_db):
    from rt.core.lesson_paths import lesson_path
    from rt.db.llm_calls import load_entries, record_llm_call
    lesson = tmp_path / "lezione"
    lesson.mkdir()
    entry = {"job": "review", "usage": {"prompt_cache_hit_tokens": 200}}
    with open(lesson_path(str(lesson), "llm_debug.log"), "w") as file:
        file.write(json.dumps(entry) + "\n")
    record_llm_call(str(lesson), entry)
    assert load_entries(str(lesson))[0]["cached_input_tokens"] == 200
    with session_scope(rt_db) as session:
        assert session.scalar(select(LlmCall)).cached_input_tokens == 200


def test_failed_validation_still_records_cache_tokens_and_cost(tmp_path, monkeypatch, rt_db):
    from rt.llm.errors import LLMFailure
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    lesson = tmp_path / "lezione"
    lesson.mkdir()
    response = MagicMock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": '{"issues": [{"tipo": "concettuale"}]}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 800}}
    monkeypatch.setattr("requests.post", lambda *a, **kw: response)
    client = LLMClient()
    client.config.pricing = {"deepseek": {"deepseek-chat": {
        "input_per_million": 10, "cached_input_per_million": 1, "output_per_million": 20}}}
    with pytest.raises(LLMFailure):
        client.call_structured(prompt="unità", system_prompt="sistema", response_model=ReviewFindingList,
            job_name="review", override_provider="deepseek", override_model="deepseek-chat", max_retries=0,
            stream=False, show_monitor=False, lesson_dir=str(lesson))
    with session_scope(rt_db) as session:
        call = session.scalar(select(LlmCall))
        assert call.status == "error"
        assert call.cached_input_tokens == 800 and call.estimated_cost == 0.0048
    assert current_telemetry().get_last().cached_input_tokens == 800
