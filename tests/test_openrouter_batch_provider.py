"""Test unitari Fase 5: provider OpenRouter batch (serializzazione, parser fuori ordine, errori, DELETE)."""
import json
from unittest.mock import MagicMock

import pytest

from rt.llm.errors import LLMFailure, RateLimitFailure
from rt.llm.providers import get_provider
from rt.llm.providers.openrouter import OpenRouterProvider


def test_provider_supports_batch_flags():
    assert get_provider("openrouter").supports_batch is True
    assert get_provider("google").supports_batch is False
    assert get_provider("deepseek").supports_batch is False
    assert get_provider("openai_compatible").supports_batch is False


def test_openrouter_batch_payload_puts_metadata_before_requests():
    provider = OpenRouterProvider()
    serialized = provider.build_batch_payload(
        [
            {
                "custom_id": "k1",
                "body": {
                    "model": "openai/gpt-4o:batch",
                    "messages": [{"role": "user", "content": "Ciao"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            }
        ],
        model="openai/gpt-4o",
    )

    # Verifica l'ordine testuale delle chiavi nel JSON serializzato (obbligatorio per evitare 400 su OpenRouter)
    idx_endpoint = serialized.index('"endpoint"')
    idx_model = serialized.index('"model"')
    idx_window = serialized.index('"completion_window"')
    idx_requests = serialized.index('"requests"')
    assert idx_endpoint < idx_requests
    assert idx_model < idx_requests
    assert idx_window < idx_requests

    parsed = json.loads(serialized)
    assert parsed["endpoint"] == "/v1/chat/completions"
    assert parsed["model"] == "openai/gpt-4o:batch"
    assert parsed["completion_window"] == "24h"
    assert "stream" not in parsed["requests"][0]["body"]
    assert "stream_options" not in parsed["requests"][0]["body"]


def test_openrouter_submit_batch_and_http_errors(monkeypatch):
    provider = OpenRouterProvider()

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"id": "batch_abc123"}
    post_mock = MagicMock(return_value=ok_resp)
    monkeypatch.setattr("rt.llm.providers.openrouter.requests.post", post_mock)

    bid = provider.submit_batch(
        [{"custom_id": "k1", "body": {"model": "m:batch", "messages": []}}],
        model="m",
        api_key="sk-test",
    )
    assert bid == "batch_abc123"
    assert post_mock.call_args.args[0] == "https://openrouter.ai/api/v1/batches"

    # 402, 413, 429
    for status, exc_cls, expected_class in [
        (402, LLMFailure, "payment_required"),
        (413, LLMFailure, "payload_too_large"),
        (429, RateLimitFailure, "rate_limit"),
    ]:
        err_resp = MagicMock()
        err_resp.status_code = status
        err_resp.content = b'{"error": "limit"}'
        err_resp.text = '{"error": "limit"}'
        err_resp.headers = {"Retry-After": "12"} if status == 429 else {}
        monkeypatch.setattr("rt.llm.providers.openrouter.requests.post", MagicMock(return_value=err_resp))
        with pytest.raises(exc_cls) as exc_info:
            provider.submit_batch([{"custom_id": "k1", "body": {}}], model="m", api_key="sk-test")
        assert exc_info.value.failure_class == expected_class
        if status == 429:
            assert exc_info.value.retry_after == pytest.approx(12.0)


def test_openrouter_poll_batch_out_of_order_and_item_errors_and_cleanup(monkeypatch):
    provider = OpenRouterProvider()

    # Stato intermedio: in_progress -> None
    in_prog = MagicMock()
    in_prog.status_code = 200
    in_prog.json.return_value = {"id": "b1", "status": "in_progress"}
    monkeypatch.setattr("rt.llm.providers.openrouter.requests.get", MagicMock(return_value=in_prog))
    status, results = provider.poll_batch("b1", api_key="sk-test")
    assert status == "in_progress" and results is None

    # Stato completed con risultati fuori ordine (k2 prima di k1), forma OpenAI body, e k3 con errore
    done = MagicMock()
    done.status_code = 200
    done.json.return_value = {
        "id": "b1",
        "status": "completed",
        "model": "openai/gpt-4o:batch",
        "results": [
            {
                "custom_id": "k2",
                "response": {
                    "status_code": 200,
                    "body": {
                        "id": "cmpl-2",
                        "model": "openai/gpt-4o",
                        "choices": [{"message": {"content": '{"n": 2}', "reasoning": "ragionamento"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
                    },
                },
            },
            {
                "custom_id": "k3",
                "error": {"message": "Context length exceeded", "code": 400},
            },
            {
                "custom_id": "k1",
                "response": {
                    "id": "cmpl-1",
                    "choices": [{"message": {"content": '{"n": 1}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                },
            },
        ],
    }
    monkeypatch.setattr("rt.llm.providers.openrouter.requests.get", MagicMock(return_value=done))

    status, results = provider.poll_batch("b1", api_key="sk-test")
    assert status == "completed"
    assert results is not None
    assert set(results) == {"k1", "k2", "k3"}
    assert results["k1"].response is not None and results["k1"].response.content == '{"n": 1}'
    assert results["k2"].response is not None and results["k2"].response.content == '{"n": 2}'
    assert results["k2"].response.reasoning == "ragionamento"
    assert results["k2"].response.resolved_model == "openai/gpt-4o"
    assert results["k3"].response is None and "Context length" in (results["k3"].error or "")

    del_mock = MagicMock()
    monkeypatch.setattr("rt.llm.providers.openrouter.requests.delete", del_mock)
    provider.cleanup_batch("b1", api_key="sk-test")
    assert del_mock.call_args.args[0] == "https://openrouter.ai/api/v1/batches/b1"
