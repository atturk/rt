"""
tests/test_openrouter_provider_routing.py
Suite di test per il routing dei backend OpenRouter (provider_routing) per-route.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RouteConfig, JobRoutingConfig, RTConfig, load_config
from rt.llm.client import LLMClient
from rt.llm.providers.openrouter import OpenRouterProvider
from rt.llm.providers.deepseek import DeepSeekProvider
from rt.llm.providers.google import GoogleProvider
from rt.llm.providers.openai_compatible import OpenAICompatibleProvider


class DummyResponseSchema(BaseModel):
    summary: str


def test_route_config_provider_routing_passthrough():
    """
    1. RouteConfig con provider_routing si costruisce senza errori;
    il dizionario è accessibile esattamente come passato (nessuna validazione del contenuto).
    """
    routing_dict = {
        "only": ["deepinfra", "together"],
        "quantizations": ["fp8", "bf16"],
        "sort": "throughput",
        "allow_fallbacks": True,
        "arbitrary_future_field": 123
    }
    route = RouteConfig(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        provider_routing=routing_dict
    )
    assert route.provider_routing == routing_dict
    assert route.provider_routing["only"] == ["deepinfra", "together"]
    assert route.provider_routing["arbitrary_future_field"] == 123


def test_independent_provider_routing_across_routes():
    """
    2. Due route diverse nello stesso JobRoutingConfig (es. primary con DeepSeek
    e fallback.generic con GLM) hanno ciascuna il proprio provider_routing indipendente,
    senza alcuna condivisione o contaminazione.
    """
    primary_routing = {
        "only": ["hoster-deepseek-1", "hoster-deepseek-2"],
        "sort": "throughput"
    }
    fallback_routing = {
        "only": ["hoster-glm-1"],
        "sort": "latency"
    }

    job_cfg = JobRoutingConfig(
        primary=RouteConfig(
            provider="openrouter",
            model="deepseek/deepseek-v4-flash",
            provider_routing=primary_routing
        ),
        fallback={
            "generic": RouteConfig(
                provider="openrouter",
                model="z-ai/glm-5.3",
                provider_routing=fallback_routing
            )
        }
    )

    assert job_cfg.primary.provider_routing == primary_routing
    assert job_cfg.fallback.generic.provider_routing == fallback_routing
    assert job_cfg.primary.provider_routing != job_cfg.fallback.generic.provider_routing

    # Modifiche su un dizionario non influenzano l'altro
    job_cfg.primary.provider_routing["only"].append("hoster-deepseek-3")
    assert "hoster-deepseek-3" not in job_cfg.fallback.generic.provider_routing["only"]


def test_llm_client_resolve_provider_routing():
    """
    3. LLMClient._resolve_provider_routing:
       - route con provider_routing impostato + provider 'openrouter' -> restituisce il dizionario.
       - route senza provider_routing -> None.
       - provider non-openrouter (es. deepseek) con provider_routing impostato -> restituisce None.
    """
    client = LLMClient()

    routing_data = {"only": ["provider-a"], "sort": "price"}

    # Case 1: openrouter + provider_routing
    route_or = RouteConfig(provider="openrouter", model="deepseek/deepseek-v4-flash", provider_routing=routing_data)
    assert client._resolve_provider_routing(route_or, "openrouter") == routing_data

    # Case 2: openrouter senza provider_routing
    route_or_none = RouteConfig(provider="openrouter", model="deepseek/deepseek-v4-flash", provider_routing=None)
    assert client._resolve_provider_routing(route_or_none, "openrouter") is None

    # Case 3: provider != openrouter (es. deepseek, google, openai_compatible)
    route_ds = RouteConfig(provider="deepseek", model="deepseek-v4-flash", provider_routing=routing_data)
    assert client._resolve_provider_routing(route_ds, "deepseek") is None

    route_goog = RouteConfig(provider="google", model="gemini-3.5-flash-lite", provider_routing=routing_data)
    assert client._resolve_provider_routing(route_goog, "google") is None

    route_compat = RouteConfig(provider="openai_compatible", model="custom-m", base_url="https://api.test.com/v1", provider_routing=routing_data)
    assert client._resolve_provider_routing(route_compat, "openai_compatible") is None


def test_openrouter_provider_build_payload():
    """
    4. OpenRouterProvider().build_payload:
       - con provider_routing -> payload['provider'] presente con i valori passati.
       - con provider_routing=None -> chiave 'provider' NON presente nel payload (retrocompatibile).
    """
    provider = OpenRouterProvider()
    messages = [{"role": "user", "content": "hello"}]

    # Con provider_routing
    routing_data = {"only": ["deepinfra"], "sort": "throughput"}
    payload_with = provider.build_payload(
        model="deepseek/deepseek-v4-flash",
        messages=messages,
        provider_routing=routing_data
    )
    assert "provider" in payload_with
    assert payload_with["provider"] == routing_data

    # Senza provider_routing (default None)
    payload_without = provider.build_payload(
        model="deepseek/deepseek-v4-flash",
        messages=messages,
        provider_routing=None
    )
    assert "provider" not in payload_without


def test_end_to_end_openrouter_provider_routing_sent_in_body(tmp_path, monkeypatch):
    """
    5. Test end-to-end: un job con route OpenRouter e provider_routing impostato
    invia nel payload JSON della richiesta HTTP (requests.post) l'oggetto 'provider' atteso.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    general_content = """version: "2.0.0"
pricing_staleness_warning_days: 3
mock_llm: false
streaming: true
show_monitor: false
"""
    (config_dir / "general.yaml").write_text(general_content, encoding="utf-8")

    outline_content = """max_attempts: 1
max_output_chars: 10000
primary:
  provider: "openrouter"
  model: "deepseek/deepseek-v4-flash"
  timeout_seconds: 60
  provider_routing:
    only:
      - "deepinfra"
      - "together"
    quantizations:
      - "fp8"
      - "bf16"
    sort: "throughput"
    allow_fallbacks: false
"""
    (config_dir / "outline.yaml").write_text(outline_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")

    client = LLMClient()

    mock_resp_json = {
        "id": "chatcmpl-or-provider-test",
        "object": "chat.completion",
        "created": 123456789,
        "model": "deepseek/deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"summary": "Risposta completata con successo."}),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = mock_resp_json
    mock_post_resp.text = json.dumps(mock_resp_json)

    with patch("requests.post", return_value=mock_post_resp) as mock_post:
        res = client.call_structured(
            job_name="outline",
            system_prompt="Sei un assistente.",
            prompt="Genera outline.",
            response_model=DummyResponseSchema,
        )

        assert res.summary == "Risposta completata con successo."
        assert mock_post.called
        call_args, call_kwargs = mock_post.call_args
        sent_payload = call_kwargs.get("json") or json.loads(call_kwargs.get("data", "{}"))

        assert "provider" in sent_payload
        assert sent_payload["provider"] == {
            "only": ["deepinfra", "together"],
            "quantizations": ["fp8", "bf16"],
            "sort": "throughput",
            "allow_fallbacks": False
        }


def test_other_provider_adapters_accept_and_ignore_provider_routing():
    """
    6. Verificare che gli altri 3 provider adapter (deepseek, google, openai_compatible)
    accettino il parametro provider_routing senza sollevare TypeError e senza inserire
    la chiave 'provider' nel payload.
    """
    messages = [{"role": "user", "content": "hello"}]
    routing_data = {"only": ["dummy"], "sort": "throughput"}

    # 1. DeepSeekProvider
    ds = DeepSeekProvider()
    p_ds = ds.build_payload(model="deepseek-v4-flash", messages=messages, provider_routing=routing_data)
    assert "provider" not in p_ds

    # 2. GoogleProvider
    goog = GoogleProvider()
    p_goog = goog.build_payload(model="gemini-3.5-flash-lite", messages=messages, provider_routing=routing_data)
    assert "provider" not in p_goog

    # 3. OpenAICompatibleProvider
    compat = OpenAICompatibleProvider()
    p_compat = compat.build_payload(model="custom-model", messages=messages, provider_routing=routing_data)
    assert "provider" not in p_compat


def test_rt_config_has_no_global_provider_routing_field():
    """
    Verifica architetturale: RTConfig non deve avere alcun campo relativo
    a provider routing globale.
    """
    cfg_fields = RTConfig.model_fields
    assert "openrouter_provider_routing" not in cfg_fields
    assert "provider_routing" not in cfg_fields
