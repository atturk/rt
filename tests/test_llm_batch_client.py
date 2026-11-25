"""Test unitari per LLMClient e RouteConfig in modalità batch (Fase 2)."""
import json
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from rt.core.config import JobFallbackConfig, JobRoutingConfig, RTConfig, RouteConfig
from rt.llm import deferred
from rt.llm.client import LLMClient
from rt.llm.deferred import use_batch_fallback, use_job_id
from rt.llm.errors import DeferredCall, RateLimitFailure, SchemaFailure
from rt.llm.providers.base import NormalizedResponse
from rt.llm.telemetry import TelemetryStore, use_telemetry


class _Reply(BaseModel):
    answer: str


def _make_config(*, batch: bool = True, provider: str = "openrouter", model: str = "openai/gpt-4o", fallback=None):
    route = RouteConfig(provider=provider, credential=provider, model=model, batch=batch)
    return RTConfig(
        mock_llm=False,
        jobs={
            "review": JobRoutingConfig(primary=route, fallback=fallback or JobFallbackConfig()),
            "outline": JobRoutingConfig(primary=route),
            "study_note": JobRoutingConfig(primary=route),
        },
    )


def test_route_config_batch_validation(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")

    r_ok = RouteConfig(provider="openrouter", credential="openrouter", model="openai/gpt-4o", batch=True)
    assert r_ok.batch is True

    with pytest.raises(ValueError, match="non supporta la modalità batch"):
        RouteConfig(provider="deepseek", credential="deepseek", model="deepseek-chat", batch=True)

    with pytest.raises(ValueError, match="non supporta la modalità batch"):
        RouteConfig(provider="openai_compatible", credential="deepseek", model="m", base_url="http://localhost:8000/v1", batch=True)


def test_batch_call_defers_then_serves_from_done_cache(rt_db, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _make_config(batch=True)
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

    post_spy = MagicMock(side_effect=AssertionError("Nessuna chiamata HTTP sincrona consentita in batch"))
    monkeypatch.setattr("rt.llm.client.requests.post", post_spy)

    client = LLMClient(force_mock=False)
    with use_job_id("job-batch-1"):
        with pytest.raises(DeferredCall) as exc_info:
            client.call_structured(
                prompt="Domanda di test",
                system_prompt="Sistema",
                response_model=_Reply,
                job_name="review",
                unit_id="1.1",
            )

    dc = exc_info.value
    assert dc.provider == "openrouter"
    assert dc.model == "openai/gpt-4o:batch"
    assert dc.job_id == "job-batch-1"

    entry = deferred.get(dc.key)
    assert entry is not None
    assert entry.state == "pending"
    assert entry.request["model"] == "openai/gpt-4o:batch"
    assert entry.request["stream"] is False

    # Simula invio e completamento del lotto con uso e costo
    deferred.mark_submitted([dc.key], "batch-or-1")
    deferred.store_results("batch-or-1", {
        dc.key: NormalizedResponse(
            content=json.dumps({"answer": "risposta dal lotto"}),
            provider="openrouter",
            model="openai/gpt-4o:batch",
            resolved_model="openai/gpt-4o",
            usage={"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.00042},
            finish_reason="stop",
            request_id="req-batch-1",
        )
    })

    telemetry = TelemetryStore()
    with use_telemetry(telemetry), use_job_id("job-batch-1"):
        res = client.call_structured(
            prompt="Domanda di test",
            system_prompt="Sistema",
            response_model=_Reply,
            job_name="review",
            unit_id="1.1",
        )

    assert res.answer == "risposta dal lotto"
    assert post_spy.call_count == 0
    recs = telemetry._records
    assert len(recs) == 1
    assert recs[0].status == "success"
    assert recs[0].model == "openai/gpt-4o:batch"
    assert recs[0].estimated_cost == pytest.approx(0.00042)


def test_batch_error_cache_raises_and_clears_key_for_retry(rt_db, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _make_config(batch=True)
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

    client = LLMClient(force_mock=False)
    with pytest.raises(DeferredCall) as exc_info:
        client.call_structured(
            prompt="Domanda",
            system_prompt="Sys",
            response_model=_Reply,
            job_name="review",
            max_retries=0,
        )
    key = exc_info.value.key
    deferred.mark_submitted([key], "batch-err")
    deferred.store_results("batch-err", {key: {"error": "Rate limit exceeded (429)"}})

    with pytest.raises(RateLimitFailure):
        client.call_structured(
            prompt="Domanda",
            system_prompt="Sys",
            response_model=_Reply,
            job_name="review",
            max_retries=0,
        )
    # La chiave in errore viene azzerata dopo il sollevamento
    assert deferred.get(key) is None


def test_batch_images_fall_back_to_immediate_sync_call(rt_db, monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _make_config(batch=True)
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "id": "sync-1",
        "choices": [{"message": {"content": '{"answer": "da immagine"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    fake_resp.content = json.dumps(fake_resp.json.return_value).encode("utf-8")
    post_mock = MagicMock(return_value=fake_resp)
    monkeypatch.setattr("rt.llm.client.requests.post", post_mock)

    client = LLMClient(force_mock=False)
    with caplog.at_level("INFO"):
        res = client.call_structured(
            prompt="Descrivi",
            system_prompt="Sys",
            response_model=_Reply,
            job_name="review",
            image_data_url="data:image/png;base64,AAAA",
            stream=False,
        )
    assert res.answer == "da immagine"
    assert post_mock.call_count == 1
    assert "immagini: chiamata immediata" in caplog.text


def test_interactive_and_batch_fallback_never_defer(rt_db, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _make_config(batch=True)
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    payload_dict = {
        "id": "sync-2",
        "choices": [{"message": {"content": '{"answer": "sincrona"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    fake_resp.json.return_value = payload_dict
    fake_resp.content = json.dumps(payload_dict).encode("utf-8")
    post_mock = MagicMock(return_value=fake_resp)
    monkeypatch.setattr("rt.llm.client.requests.post", post_mock)

    # 1. interactive=True (es. chat Studio / recall live)
    res1 = LLMClient(force_mock=False, interactive=True).call_structured(
        prompt="Chiedi", system_prompt="Sys", response_model=_Reply, job_name="review", stream=False,
    )
    assert res1.answer == "sincrona"

    # 2. job_name interattivo
    res2 = LLMClient(force_mock=False).call_structured(
        prompt="Nota", system_prompt="Sys", response_model=_Reply, job_name="study_note", stream=False,
    )
    assert res2.answer == "sincrona"

    # 3. batch_fallback=True
    with use_batch_fallback(True):
        res3 = LLMClient(force_mock=False).call_structured(
            prompt="Ripresa", system_prompt="Sys", response_model=_Reply, job_name="review", stream=False,
        )
    assert res3.answer == "sincrona"
    assert post_mock.call_count == 3


def test_batch_invalid_done_response_clears_cache_and_raises_schema_failure(rt_db, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _make_config(batch=True)
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

    client = LLMClient(force_mock=False)
    with pytest.raises(DeferredCall) as exc_info:
        client.call_structured(
            prompt="Domanda", system_prompt="Sys", response_model=_Reply, job_name="review", max_retries=0,
        )
    key = exc_info.value.key
    deferred.mark_submitted([key], "b-bad")
    deferred.store_results("b-bad", {
        key: NormalizedResponse(content="non è json", provider="openrouter", model="openai/gpt-4o:batch", finish_reason="stop")
    })
    with pytest.raises(SchemaFailure):
        client.call_structured(
            prompt="Domanda", system_prompt="Sys", response_model=_Reply, job_name="review", max_retries=0,
        )
    assert deferred.get(key) is None


def test_pricing_batch_suffix_applies_half_discount():
    from rt.llm.pricing import calculate_cost
    normal = calculate_cost("openrouter", "openai/gpt-4o-mini", 1_000_000, 1_000_000)
    batch = calculate_cost("openrouter", "openai/gpt-4o-mini:batch", 1_000_000, 1_000_000)
    assert normal is not None and batch is not None
    assert batch == pytest.approx(normal * 0.5)
