"""V4b: contratto del revisore imposto dal gateway senza cambiare gli altri job."""
import json
from unittest.mock import MagicMock

import pytest

from rt.llm.client import LLMClient
from rt.llm.prompts import ReviewFindingList
from rt.llm.providers.deepseek import DeepSeekProvider
from rt.llm.providers.google import GoogleProvider
from rt.llm.providers.openrouter import OpenRouterProvider


@pytest.mark.parametrize("provider,model", [(OpenRouterProvider(), "anthropic/claude-3.5-sonnet"),
                                            (GoogleProvider(), "google/gemini-2.5-flash")])
@pytest.mark.parametrize("stream", [False, True])
def test_provider_imposes_review_schema(provider, model, stream):
    schema = ReviewFindingList.model_json_schema()
    payload = provider.build_payload(model=model, messages=[], response_format={"type": "json_object"},
                                     response_json_schema=schema, stream=stream)
    assert payload["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "structured_response", "strict": True, "schema": schema}}


def test_deepseek_keeps_json_object():
    payload = DeepSeekProvider().build_payload(model="deepseek-chat", messages=[],
        response_format={"type": "json_object"}, response_json_schema=ReviewFindingList.model_json_schema())
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("provider,model,key", [("openrouter", "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY"),
                                              ("google", "gemini-2.5-flash", "GOOGLE_API_KEY_1"),
                                              ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY")])
def test_gateway_schema_and_local_validation(monkeypatch, provider, model, key):
    monkeypatch.setenv(key, "test-key")
    requests = []
    invalid = {"issues": [{"tipo": "concettuale", "gravita": "alta", "citazione": "citazione", "motivazione": "motivo"}]}
    valid = {"issues": [{**invalid["issues"][0], "sostituzione": "testo corretto"}]}
    replies = iter([invalid, valid])
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": json.dumps(next(replies))}, "finish_reason": "stop"}]}
        return response
    monkeypatch.setattr("requests.post", post)
    client = LLMClient()
    result = client.call_structured(prompt="unità", system_prompt="sistema", response_model=ReviewFindingList,
        job_name="review", override_provider=provider, override_model=model,
        override_credential="google_1" if provider == "google" else provider,
        stream=False, show_monitor=False, constrained_schema=True)
    assert result.issues[0].sostituzione == "testo corretto"
    assert len(requests) == 2  # il JSON senza sostituzione non supera la validazione
    expected = "json_object" if provider == "deepseek" else "json_schema"
    assert all(request["response_format"]["type"] == expected for request in requests)
