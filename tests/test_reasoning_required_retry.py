"""
tests/test_reasoning_required_retry.py
Test suite dedicata per ReasoningRequiredFailure (OpenRouter free-tier):
- test_classify_failure_reasoning_required: classificazione deterministica e non-regressione su HTTP 400 generici
- test_reasoning_required_retry_recovers_on_second_attempt: retry same-route con payload invariato (thinking=False)
- test_reasoning_required_escalates_thinking_after_two_consecutive_failures: escalation locale a thinking=True solo sul 3° tentativo
- test_reasoning_required_exhausts_to_normal_failover: esaurimento dei retry same-route e fallback cross-route standard
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RTConfig, RouteConfig, JobRoutingConfig, JobFallbackConfig
from rt.llm.client import LLMClient, LLMError
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.errors import (
    ReasoningRequiredFailure,
    UnknownProviderFailure,
    classify_failure
)
from rt.llm.telemetry import GLOBAL_TELEMETRY


class SampleModel(BaseModel):
    summary: str
    item_count: int


def test_classify_failure_reasoning_required():
    """
    Verifica che classify_failure riconosca i vari pattern di ReasoningRequiredFailure su HTTP 400,
    e mantenga UnknownProviderFailure per altri codici 400 generici.
    """
    raw_err = '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400}}'
    fail = classify_failure(
        http_status=400,
        raw_response=raw_err,
        provider="openrouter",
        model="openrouter/free"
    )
    assert isinstance(fail, ReasoningRequiredFailure)
    assert fail.failure_class == "reasoning_required"
    assert fail.http_status == 400
    assert "Reasoning is mandatory" in fail.message

    # Varianti sintattiche
    fail2 = classify_failure(
        http_status=400,
        raw_response='{"error":"Reasoning is required for this model"}',
        provider="openrouter",
        model="openrouter/free"
    )
    assert isinstance(fail2, ReasoningRequiredFailure)
    assert fail2.failure_class == "reasoning_required"

    fail3 = classify_failure(
        http_status=400,
        raw_response='{"error":"Reasoning cannot be disabled for free endpoint"}',
        provider="openrouter",
        model="openrouter/free"
    )
    assert isinstance(fail3, ReasoningRequiredFailure)
    assert fail3.failure_class == "reasoning_required"

    # Non-regressione: HTTP 400 generico non correlato al reasoning
    fail_generic = classify_failure(
        http_status=400,
        raw_response='{"error":{"message":"Invalid request body","code":400}}',
        provider="openrouter",
        model="openrouter/free"
    )
    assert isinstance(fail_generic, UnknownProviderFailure)
    assert fail_generic.failure_class == "unknown_error"

    # Non-regressione: HTTP 500 anche se menziona reasoning non è 400
    fail_500 = classify_failure(
        http_status=500,
        raw_response='{"error":"Internal error with reasoning engine"}',
        provider="openrouter",
        model="openrouter/free"
    )
    assert not isinstance(fail_500, ReasoningRequiredFailure)


def test_reasoning_required_retry_recovers_on_second_attempt(monkeypatch):
    """
    Tentativo 1 fallisce con HTTP 400 'Reasoning is mandatory...',
    Tentativo 2 riesce con HTTP 200.
    Assert:
    - esattamente 2 chiamate HTTP;
    - entrambi i payload hanno reasoning == {"enabled": False};
    - risultato finale valido;
    - config invariata.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 0  # Isola dal budget timeout

    client.config.jobs["review_asr"] = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            reasoning_effort="low",
            timeout_seconds=30
        )
    )

    captured_payloads = []
    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_payloads.append(dict(json) if json else {})

        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count == 1:
            resp.status_code = 400
            err_msg = '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400,"metadata":{"provider_name":null}}}'
            resp.content = err_msg.encode("utf-8")
            resp.text = err_msg
        else:
            resp.status_code = 200
            ok_json = {"choices": [{"message": {"content": '{"summary": "ASR ok", "item_count": 5}'}}]}
            resp.json.return_value = ok_json
            resp.iter_lines.return_value = []
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Analizza trascrizione",
            system_prompt="Sei un reviewer ASR",
            response_model=SampleModel,
            job_name="review_asr",
            show_monitor=False
        )

    assert call_count == 2
    assert len(captured_payloads) == 2
    # Entrambi i tentativi devono avere reasoning omesso (nessuna escalation necessaria dopo 1 fallimento)
    assert "reasoning" not in captured_payloads[0]
    assert "reasoning" not in captured_payloads[1]
    assert res.summary == "ASR ok"
    assert res.item_count == 5

    # Verifica che la route config originale NON sia stata mutata
    job_cfg = client.config.jobs["review_asr"]
    assert job_cfg.primary.thinking is False


def test_reasoning_required_escalates_thinking_after_two_consecutive_failures(monkeypatch):
    """
    Tentativi 1 e 2 falliscono con HTTP 400 'Reasoning is mandatory...',
    Tentativo 3 riesce con HTTP 200.
    Assert:
    - esattamente 3 chiamate HTTP;
    - payload 1 e 2 con reasoning == {"enabled": False};
    - payload 3 con reasoning == {"enabled": True, "effort": "low"} (escalation locale);
    - risultato finale valido;
    - la config del job e della route rimane immutata con thinking=False.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 0

    client.config.jobs["review_asr"] = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            reasoning_effort="low",
            timeout_seconds=30
        )
    )

    captured_payloads = []
    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_payloads.append(dict(json) if json else {})

        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count in (1, 2):
            resp.status_code = 400
            err_msg = '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400,"metadata":{"provider_name":null}}}'
            resp.content = err_msg.encode("utf-8")
            resp.text = err_msg
        else:
            resp.status_code = 200
            ok_json = {"choices": [{"message": {"content": '{"summary": "ASR escalated ok", "item_count": 10}'}}]}
            resp.json.return_value = ok_json
            resp.iter_lines.return_value = []
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Analizza trascrizione",
            system_prompt="Sei un reviewer ASR",
            response_model=SampleModel,
            job_name="review_asr",
            show_monitor=False
        )

    assert call_count == 3
    assert len(captured_payloads) == 3
    # Payload 1 e 2 con thinking=False (reasoning omesso su OpenRouter)
    assert "reasoning" not in captured_payloads[0]
    assert "reasoning" not in captured_payloads[1]
    # Payload 3 con thinking forzato a True via escalation locale
    assert captured_payloads[2]["reasoning"] == {"enabled": True, "effort": "low"}
    assert res.summary == "ASR escalated ok"
    assert res.item_count == 10

    # Invariante: route e job config NON devono essere mutate
    job_cfg = client.config.jobs["review_asr"]
    assert job_cfg.primary.thinking is False


def test_reasoning_required_exhausts_to_normal_failover(monkeypatch):
    """
    Tutti e 3 i tentativi sulla route primaria falliscono con HTTP 400 (anche il 3° con thinking=True).
    Il client procede al failover su fallback.generic configurato su deepseek.
    Assert:
    - 4 chiamate HTTP totali (3 su OpenRouter, 1 su DeepSeek);
    - failover su fallback.generic senza modifiche a router.py;
    - risultato finale valido restituito da DeepSeek.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-key-67890")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 0

    client.config.jobs["review_asr"] = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            reasoning_effort="low",
            timeout_seconds=30
        ),
        fallback=JobFallbackConfig(
            generic=RouteConfig(
                route_id="r_deepseek_fallback",
                provider="deepseek",
                credential="deepseek",
                model="deepseek-chat",
                thinking=False,
                timeout_seconds=30
            )
        )
    )

    captured_urls = []
    captured_payloads = []
    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_urls.append(url)
        captured_payloads.append(dict(json) if json else {})

        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count in (1, 2, 3):
            # Tutte e 3 le chiamate su OpenRouter falliscono
            resp.status_code = 400
            err_msg = '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400,"metadata":{"provider_name":null}}}'
            resp.content = err_msg.encode("utf-8")
            resp.text = err_msg
        else:
            # 4ª chiamata: atterra su DeepSeek e ha successo
            resp.status_code = 200
            ok_json = {"choices": [{"message": {"content": '{"summary": "Fallback DeepSeek ok", "item_count": 99}'}}]}
            resp.json.return_value = ok_json
            resp.iter_lines.return_value = []
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Analizza trascrizione",
            system_prompt="Sei un reviewer ASR",
            response_model=SampleModel,
            job_name="review_asr",
            show_monitor=False
        )

    assert call_count == 4
    # Le prime 3 chiamate sono andate all'endpoint OpenRouter
    assert captured_urls[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured_urls[1] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured_urls[2] == "https://openrouter.ai/api/v1/chat/completions"
    # La 4ª chiamata è andata all'endpoint DeepSeek di fallback
    assert captured_urls[3] == "https://api.deepseek.com/chat/completions"

    # Verifiche payload: 1 e 2 senza thinking (reasoning omesso), 3 con escalation
    assert "reasoning" not in captured_payloads[0]
    assert "reasoning" not in captured_payloads[1]
    assert captured_payloads[2]["reasoning"] == {"enabled": True, "effort": "low"}

    assert res.summary == "Fallback DeepSeek ok"
    assert res.item_count == 99

    # Config invariata
    job_cfg = client.config.jobs["review_asr"]
    assert job_cfg.primary.thinking is False
