"""
tests/test_telemetry.py
Unit tests per il sistema di telemetria LLM, provider abstraction (DeepSeek / OpenRouter),
streaming SSE mock, calcolo costi e configurazione provider switching.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.llm.telemetry import LLMTelemetryRecord, TelemetryStore, GLOBAL_TELEMETRY
from rt.llm.pricing import ModelPricing, calculate_cost, DEFAULT_PRICING
from rt.llm.providers import get_provider
from rt.llm.providers.base import NormalizedResponse, StreamChunk
from rt.llm.providers.deepseek import DeepSeekProvider
from rt.llm.providers.openrouter import OpenRouterProvider
from rt.llm.client import LLMClient, LLMError
from rt.core.config import RTConfig, LLMModelConfig


class SampleResponseModel(BaseModel):
    ok: bool


# ======================================================================
# 1. TEST TELEMETRY NORMALIZATION & STORE
# ======================================================================

def test_telemetry_record_creation_and_store():
    store = TelemetryStore()
    store.clear()

    rec = LLMTelemetryRecord(
        request_id="req_test_001",
        job="rewrite",
        unit_id="3.1",
        provider="openrouter",
        model="deepseek/deepseek-v4-pro",
        input_tokens=150,
        reasoning_tokens=50,
        output_tokens=200,
        total_tokens=400,
        latency_ms=1234.5,
        finish_reason="stop",
        status="success",
        estimated_cost=0.00045,
        streaming=True
    )
    store.add(rec)

    assert len(store.get_all()) == 1
    last = store.get_last()
    assert last is not None
    assert last.request_id == "req_test_001"
    assert last.job == "rewrite"
    assert last.unit_id == "3.1"
    assert last.input_tokens == 150
    assert last.reasoning_tokens == 50
    assert last.output_tokens == 200
    assert last.total_tokens == 400
    assert last.estimated_cost == 0.00045

    summary = store.get_summary()
    assert summary["total_requests"] == 1
    assert summary["total_input_tokens"] == 150
    assert summary["total_output_tokens"] == 200
    assert summary["total_reasoning_tokens"] == 50
    assert summary["total_tokens"] == 400
    assert summary["total_estimated_cost_usd"] == 0.00045


# ======================================================================
# 2. TEST PROVIDER ABSTRACTION (DeepSeek vs OpenRouter)
# ======================================================================

def test_provider_factory_registry():
    ds_provider = get_provider("deepseek")
    assert isinstance(ds_provider, DeepSeekProvider)
    assert ds_provider.name == "deepseek"

    or_provider = get_provider("openrouter")
    assert isinstance(or_provider, OpenRouterProvider)
    assert or_provider.name == "openrouter"

    # Case insensitive
    assert isinstance(get_provider("OpenRouter"), OpenRouterProvider)
    assert isinstance(get_provider("DEEPSEEK"), DeepSeekProvider)

    # Provider sconosciuto solleva ValueError
    with pytest.raises(ValueError) as exc:
        get_provider("unknown_provider")
    assert "non riconosciuto" in str(exc.value)


def test_provider_endpoint_and_headers():
    ds = get_provider("deepseek")
    assert ds.get_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert ds.get_endpoint("https://api.deepseek.com/chat/completions") == "https://api.deepseek.com/chat/completions"
    ds_headers = ds.get_headers("ds-key-123")
    assert ds_headers["Authorization"] == "Bearer ds-key-123"
    assert ds_headers["Content-Type"] == "application/json"

    or_p = get_provider("openrouter")
    assert or_p.get_endpoint("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1/chat/completions"
    or_headers = or_p.get_headers("or-key-456")
    assert or_headers["Authorization"] == "Bearer or-key-456"
    assert or_headers["Content-Type"] == "application/json"
    assert "HTTP-Referer" in or_headers
    assert "X-Title" in or_headers


def test_provider_payload_reasoning_translation():
    messages = [{"role": "user", "content": "Hello"}]

    # DeepSeek thinking payload
    ds = get_provider("deepseek")
    ds_payload = ds.build_payload(
        model="deepseek-v4-flash",
        messages=messages,
        max_tokens=4000,
        thinking=True,
        reasoning_effort="low",
        stream=True
    )
    assert ds_payload["thinking"] == {"type": "enabled"}
    assert ds_payload["reasoning_effort"] == "low"
    assert ds_payload["stream"] is True
    assert ds_payload["stream_options"] == {"include_usage": True}

    # OpenRouter reasoning payload
    or_p = get_provider("openrouter")
    or_payload = or_p.build_payload(
        model="deepseek/deepseek-v4-pro",
        messages=messages,
        max_tokens=4000,
        thinking=True,
        reasoning_effort="low",
        stream=True
    )
    assert or_payload["reasoning"] == {"enabled": True, "effort": "low"}
    assert or_payload["stream"] is True
    assert or_payload["stream_options"] == {"include_usage": True}

    # OpenRouter con max_thinking_tokens: reasoning_effort viene ignorato
    or_payload_capped = or_p.build_payload(
        model="~deepseek/deepseek-v4-flash-latest",
        messages=messages,
        thinking=True,
        reasoning_effort="high",
        max_thinking_tokens=2000
    )
    assert or_payload_capped["model"] == "~deepseek/deepseek-v4-flash-latest"
    assert or_payload_capped["reasoning"] == {"max_tokens": 2000}
    assert "effort" not in or_payload_capped["reasoning"]

    # DeepSeek platform con max_thinking_tokens: viene ignorato e reasoning_effort è inviato a root
    ds_payload_capped = ds.build_payload(
        model="~deepseek/deepseek-v4-flash-latest",
        messages=messages,
        thinking=True,
        reasoning_effort="high",
        max_thinking_tokens=2000
    )
    assert ds_payload_capped["model"] == "deepseek-v4-flash-latest"
    assert ds_payload_capped["thinking"] == {"type": "enabled"}
    assert ds_payload_capped["reasoning_effort"] == "high"
    assert "max_thinking_tokens" not in ds_payload_capped
    assert "reasoning" not in ds_payload_capped


def test_provider_response_normalization_identical_contract():
    ds = get_provider("deepseek")
    or_p = get_provider("openrouter")

    # Mock risposta DeepSeek
    raw_ds = {
        "id": "gen_ds_001",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": '{"ok": true}',
                    "reasoning_content": "DeepSeek internal reasoning"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 20}
        }
    }

    # Mock risposta OpenRouter
    raw_or = {
        "id": "gen_or_001",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": '{"ok": true}',
                    "reasoning": "OpenRouter internal reasoning"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 20}
        }
    }

    norm_ds = ds.normalize_response(raw_ds, model_name="deepseek-v4-flash")
    norm_or = or_p.normalize_response(raw_or, model_name="deepseek/deepseek-v4-pro")

    for norm in [norm_ds, norm_or]:
        assert isinstance(norm, NormalizedResponse)
        assert norm.content == '{"ok": true}'
        assert norm.reasoning is not None
        assert norm.usage["total_tokens"] == 150
        assert norm.finish_reason == "stop"
        assert norm.request_id is not None


# ======================================================================
# 3. TEST STREAMING WITH MOCK SSE
# ======================================================================

def test_streaming_sse_parsing_deepseek():
    ds = get_provider("deepseek")

    chunk_line1 = 'data: {"id": "req_1", "choices": [{"delta": {"reasoning_content": "Reasoning chunk 1"}}]}'
    chunk_line2 = 'data: {"id": "req_1", "choices": [{"delta": {"content": "{\\"ok\\":"}}]}'
    chunk_line3 = 'data: {"id": "req_1", "choices": [{"delta": {"content": " true}"}, "finish_reason": "stop"}]}'
    usage_line = 'data: {"id": "req_1", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}'
    done_line = 'data: [DONE]'

    c1 = ds.parse_stream_line(chunk_line1)
    assert c1 is not None
    assert c1.reasoning_delta == "Reasoning chunk 1"
    assert c1.content_delta is None

    c2 = ds.parse_stream_line(chunk_line2)
    assert c2 is not None
    assert c2.content_delta == '{"ok":'

    c3 = ds.parse_stream_line(chunk_line3)
    assert c3 is not None
    assert c3.content_delta == ' true}'
    assert c3.finish_reason == "stop"

    c_usage = ds.parse_stream_line(usage_line)
    assert c_usage is not None
    assert c_usage.usage["total_tokens"] == 15

    c_done = ds.parse_stream_line(done_line)
    assert c_done is None


def test_streaming_sse_parsing_openrouter():
    or_p = get_provider("openrouter")

    chunk_line1 = 'data: {"id": "or_req_1", "choices": [{"delta": {"reasoning": "OR Reasoning chunk"}}]}'
    chunk_line2 = 'data: {"id": "or_req_1", "choices": [{"delta": {"content": "{\\"ok\\": true}"}, "finish_reason": "stop"}]}'
    usage_line = 'data: {"id": "or_req_1", "choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}}'
    done_line = 'data: [DONE]'

    c1 = or_p.parse_stream_line(chunk_line1)
    assert c1 is not None
    assert c1.reasoning_delta == "OR Reasoning chunk"

    c2 = or_p.parse_stream_line(chunk_line2)
    assert c2 is not None
    assert c2.content_delta == '{"ok": true}'
    assert c2.finish_reason == "stop"

    c_usage = or_p.parse_stream_line(usage_line)
    assert c_usage is not None
    assert c_usage.usage["total_tokens"] == 18

    assert or_p.parse_stream_line(done_line) is None


def test_client_streaming_execution_with_mock_iter_lines(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-mock-stream-test")
    client = LLMClient(force_mock=False)

    stream_lines = [
        'data: {"id": "req_str_1", "choices": [{"delta": {"reasoning_content": "Thinking..."}}]}',
        'data: {"id": "req_str_1", "choices": [{"delta": {"content": "{\\"ok\\": "}}]}',
        'data: {"id": "req_str_1", "choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}]}',
        'data: {"id": "req_str_1", "choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}',
        'data: [DONE]'
    ]


    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = stream_lines

    with patch("requests.post", return_value=mock_resp):
        res = client.call_structured(
            prompt='{"ok": true}',
            system_prompt="Return json",
            response_model=SampleResponseModel,
            job_name="outline",
            show_monitor=False
        )

    assert res.ok is True
    last_rec = GLOBAL_TELEMETRY.get_last()
    assert last_rec is not None
    assert last_rec.input_tokens == 20
    assert last_rec.output_tokens == 10
    assert last_rec.total_tokens == 30
    assert last_rec.finish_reason == "stop"
    assert last_rec.streaming is True
    assert last_rec.status == "success"


# ======================================================================
# 4. TEST COST CALCULATION
# ======================================================================

def test_cost_calculation_deepseek():
    # DeepSeek pricing standard: in: 0.14 / 1M, out: 0.28 / 1M
    # 1,000,000 input + 1,000,000 output -> $0.14 + $0.28 = $0.42
    cost = calculate_cost(
        provider="deepseek",
        model="deepseek-v4-flash",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        reasoning_tokens=0
    )
    assert cost == 0.42

    # Piccola richiesta: 1000 input, 500 output
    # cost_in = (1000/1M)*0.14 = 0.00014
    # cost_out = (500/1M)*0.28 = 0.00014
    # totale = 0.00028
    cost_small = calculate_cost(
        provider="deepseek",
        model="deepseek-v4-flash",
        input_tokens=1000,
        output_tokens=500
    )
    assert cost_small == 0.00028


def test_cost_calculation_custom_pricing():
    custom_pricing = {
        "openrouter": {
            "custom/model": {
                "input_per_million": 2.00,
                "output_per_million": 4.00
            }
        }
    }

    cost = calculate_cost(
        provider="openrouter",
        model="custom/model",
        input_tokens=500_000,
        output_tokens=250_000,
        custom_pricing=custom_pricing
    )
    # (500k/1M)*2 + (250k/1M)*4 = 1.00 + 1.00 = 2.00
    assert cost == 2.00


# ======================================================================
# 5. TEST CONFIG & PROVIDER SWITCHING
# ======================================================================

def test_provider_switching_via_override(monkeypatch):
    """Dimostra che provider=deepseek e provider=openrouter usano lo stesso contratto interno."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-switch")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-switch")

    client = LLMClient(force_mock=False)

    captured_providers = []

    def mock_post(url, headers=None, json=None, timeout=None, **kwargs):
        auth = headers.get("Authorization", "")
        if "sk-ds-switch" in auth:
            captured_providers.append("deepseek")
        elif "sk-or-switch" in auth:
            captured_providers.append("openrouter")

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"ok": true}'}
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        # Chiamata 1: DeepSeek
        res_ds = client.call_structured(
            prompt='{"ok": true}',
            system_prompt="system",
            response_model=SampleResponseModel,
            job_name="outline",
            override_provider="deepseek",
            override_model="deepseek-v4-flash",
            stream=False,
            show_monitor=False
        )
        assert res_ds.ok is True

        # Chiamata 2: OpenRouter (stesso identico contratto e model)
        res_or = client.call_structured(
            prompt='{"ok": true}',
            system_prompt="system",
            response_model=SampleResponseModel,
            job_name="outline",
            override_provider="openrouter",
            override_model="deepseek/deepseek-v4-pro",
            stream=False,
            show_monitor=False
        )
        assert res_or.ok is True

    assert captured_providers == ["deepseek", "openrouter"]


def test_unknown_provider_raises_error(monkeypatch):
    client = LLMClient(force_mock=False)
    with pytest.raises(LLMError) as exc:
        client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=SampleResponseModel,
            override_provider="non_existent_provider"
        )
    assert "non configurato o non supportato" in str(exc.value)


def test_max_thinking_tokens_config_and_client_integration(monkeypatch):
    from rt.core.config import LLMModelConfig
    
    # Test 1: parsing con nome standard
    cfg1 = LLMModelConfig(max_thinking_tokens=1500)
    assert cfg1.max_thinking_tokens == 1500

    # Test 2: parsing con alias max_reasoning_tokens
    cfg2 = LLMModelConfig.model_validate({"max_reasoning_tokens": 3000})
    assert cfg2.max_thinking_tokens == 3000

    # Test 3: client invia max_thinking_tokens al provider
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    client = LLMClient(force_mock=False)
    
    captured_payloads = []
    def mock_post(url, headers, json, timeout):
        captured_payloads.append(json)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        # Override job con max_thinking_tokens
        client.config.llm["outline"].max_thinking_tokens = 2500
        client.config.llm["outline"].provider = "openrouter"
        client.config.llm["outline"].model = "deepseek/deepseek-v4-flash-latest"
        
        client.call_structured(
            prompt='{"ok": true}',
            system_prompt="system",
            response_model=SampleResponseModel,
            job_name="outline",
            stream=False,
            show_monitor=False
        )
        
        assert len(captured_payloads) == 1
        assert captured_payloads[0]["reasoning"] == {"max_tokens": 2500}
        assert "effort" not in captured_payloads[0]["reasoning"]

