"""
tests/test_pricing.py
Test di unità per rt.llm.pricing:
- Formalizzazione di openrouter/free come tier a costo 0.0
- Risoluzione non ambigua dei modelli senza collisioni per substring parziali
- Nessun match silenzioso per gemini-3.5-flash verso gemini-3.5-flash-lite
- Gestione deterministica e fallback pulito (None se modello sconosciuto)
"""

import pytest
from rt.llm.pricing import calculate_cost, DEFAULT_PRICING, ModelPricing


def test_openrouter_free_tier():
    """Verifica che openrouter/free sia formalizzato a costo zero esatto (0.0, non None)."""
    cost = calculate_cost("openrouter", "openrouter/free", input_tokens=1000, output_tokens=500)
    assert cost == 0.0
    assert cost is not None

    cost_with_reasoning = calculate_cost("openrouter", "openrouter/free", input_tokens=5000, output_tokens=2000, reasoning_tokens=1000)
    assert cost_with_reasoning == 0.0


def test_gemini_flash_does_not_silently_match_flash_lite():
    """
    Verifica che gemini-3.5-flash NON matchi silenziosamente gemini-3.5-flash-lite:
    restituisce None (costo sconosciuto non stimato) invece di un costo fittizio.
    """
    cost_lite = calculate_cost("google", "gemini-3.5-flash-lite", input_tokens=1000, output_tokens=500)
    assert cost_lite is not None
    assert cost_lite > 0.0

    cost_flash = calculate_cost("google", "gemini-3.5-flash", input_tokens=1000, output_tokens=500)
    assert cost_flash is None, f"gemini-3.5-flash deve restituire None, invece ha restituito {cost_flash}"
    assert cost_flash != cost_lite


def test_unambiguous_matching_llama():
    """Verifica che modelli non censiti come meta-llama/unknown-llama-model-xyz non producano match ambigui."""
    cost = calculate_cost("openrouter", "meta-llama/unknown-llama-model-xyz", input_tokens=1000, output_tokens=500)
    assert cost is None


def test_provider_prefix_normalization():
    """Verifica che la normalizzazione del prefisso provider funzioni correttamente."""
    cost_raw = calculate_cost("google", "gemini-2.0-flash", input_tokens=1000, output_tokens=500)
    cost_prefixed = calculate_cost("google", "google/gemini-2.0-flash", input_tokens=1000, output_tokens=500)
    assert cost_raw is not None
    assert cost_raw == cost_prefixed


def test_deterministic_pricing_values():
    """Verifica il calcolo corretto del costo per modelli noti."""
    # deepseek-chat: 0.14/M in, 0.28/M out -> 1M in + 1M out = 0.42
    cost = calculate_cost("deepseek", "deepseek-chat", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.42


# ======================================================================
# TASK 55: OPENROUTER DYNAMIC PRICING & CONFIG WIZARD PRICING DETECTION
# ======================================================================

def test_dynamic_openrouter_pricing_fetch_success():
    """Verifica che un modello OpenRouter non in DEFAULT_PRICING recuperi il prezzo via API."""
    import rt.llm.pricing as pr
    from unittest.mock import patch, MagicMock

    # Reset cache
    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False
    pr._OPENROUTER_RETRY_AT = 0.0

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "data": [
            {
                "id": "openai/gpt-5.6-luna",
                "pricing": {
                    "prompt": "0.0000015",      # $1.50 per 1M token
                    "completion": "0.0000060"    # $6.00 per 1M token
                }
            }
        ]
    }

    with patch("requests.get", return_value=fake_resp):
        cost = pr.calculate_cost("openrouter", "openai/gpt-5.6-luna", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost is not None
        # 1.50 + 6.00 = 7.50
        assert cost == 7.50


def test_dynamic_openrouter_pricing_fetch_failure_returns_none():
    """Verifica che se la richiesta dinamica a OpenRouter fallisce, ritorna None senza sollevare eccezioni."""
    import rt.llm.pricing as pr
    from unittest.mock import patch

    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False
    pr._OPENROUTER_RETRY_AT = 0.0

    with patch("requests.get", side_effect=Exception("Connection timeout")):
        cost = pr.calculate_cost("openrouter", "some-brand-new/unknown-model-xyz", input_tokens=1000, output_tokens=1000)
        assert cost is None


def test_reasoning_tokens_counted_once_per_provider():
    # OpenRouter: completion_tokens (1M) include già 600k reasoning_tokens -> non vanno sommati due volte
    # deepseek/deepseek-r1: 0.55/M in, 2.19/M out
    cost_or = calculate_cost(
        "openrouter", "deepseek/deepseek-r1",
        input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=600_000,
    )
    assert cost_or == pytest.approx(0.55 + 2.19)

    # OpenRouter / OpenAI-compatibile con reasoning_per_million diverso da output_per_million:
    # 400k output normale @ $2/M + 600k reasoning @ $4/M = $0.80 + $2.40 = $3.20
    custom = {
        "openrouter": {"m/reason": {"input_per_million": 1.0, "output_per_million": 2.0, "reasoning_per_million": 4.0}},
        "openai_compatible": {"m/reason": {"input_per_million": 1.0, "output_per_million": 2.0}},
        "anthropic": {"claude-sonnet": {"input_per_million": 3.0, "output_per_million": 15.0}},
    }
    assert calculate_cost(
        "openrouter", "m/reason",
        input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=600_000,
        custom_pricing=custom,
    ) == pytest.approx(1.0 + 0.8 + 2.4)

    assert calculate_cost(
        "openai_compatible", "m/reason",
        input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=600_000,
        custom_pricing=custom,
    ) == pytest.approx(1.0 + 2.0)

    assert calculate_cost(
        "deepseek", "deepseek-reasoner",
        input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=600_000,
    ) == pytest.approx(0.55 + 2.19)

    assert calculate_cost(
        "anthropic", "claude-sonnet",
        input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=600_000,
        custom_pricing=custom,
    ) == pytest.approx(3.0 + 15.0)

    # Gemini nativo (google): candidatesTokenCount (400k) NON include thoughtsTokenCount (600k)
    # gemini-2.5-flash: 0.075/M in, 0.30/M out -> 0.075 + 0.12 + 0.18 = 0.375
    assert calculate_cost(
        "google", "gemini-2.5-flash",
        input_tokens=1_000_000, output_tokens=400_000, reasoning_tokens=600_000,
    ) == pytest.approx(0.075 + 0.30)


def test_llm_client_extracts_usage_and_avoids_double_counting(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from pydantic import BaseModel
    from rt.core.config import JobRoutingConfig, RTConfig, RouteConfig
    from rt.llm.client import LLMClient
    from rt.llm.telemetry import TelemetryStore, use_telemetry

    class _Out(BaseModel):
        ok: bool

    def run_case(provider, model, usage, base_url=None, credential=None):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza")
        monkeypatch.setenv("GOOGLE_API_KEY_1", "AIza")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        cred = credential or ("google_1" if provider == "google" else provider)
        route = RouteConfig(provider=provider, credential=cred, model=model, base_url=base_url)
        cfg = RTConfig(mock_llm=False, jobs={"review": JobRoutingConfig(primary=route)})
        monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)

        resp = MagicMock()
        resp.status_code = 200
        body = {
            "id": "r1",
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
            "usage": usage,
        }
        resp.json.return_value = body
        resp.content = json.dumps(body).encode("utf-8")
        monkeypatch.setattr("rt.llm.client.requests.post", MagicMock(return_value=resp))

        telemetry = TelemetryStore()
        with use_telemetry(telemetry):
            LLMClient(force_mock=False).call_structured(
                prompt="p", system_prompt="s", response_model=_Out, job_name="review", stream=False,
            )
        return telemetry._records[0].estimated_cost

    # OpenRouter: completion_tokens include già reasoning_tokens -> 0.55 + 2.19 = 2.74
    assert run_case(
        "openrouter", "deepseek/deepseek-r1",
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000,
         "completion_tokens_details": {"reasoning_tokens": 600_000}},
    ) == pytest.approx(2.74)

    # Google OpenAI-compat con total == prompt + completion + reasoning (separati): 0.075 + 0.12 + 0.18 = 0.375
    assert run_case(
        "google", "gemini-2.5-flash",
        {"prompt_tokens": 1_000_000, "completion_tokens": 400_000, "total_tokens": 2_000_000,
         "completion_tokens_details": {"reasoning_tokens": 600_000}},
    ) == pytest.approx(0.375)

    # Google OpenAI-compat con total == prompt + completion (inclusi): 0.075 + 0.30 = 0.375 (non 0.555!)
    assert run_case(
        "google", "gemini-2.5-flash",
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000,
         "completion_tokens_details": {"reasoning_tokens": 600_000}},
    ) == pytest.approx(0.375)

    # OpenAI-compatibile con custom pricing
    from rt.llm.credentials import CredentialRef, GLOBAL_CREDENTIALS
    GLOBAL_CREDENTIALS.register(CredentialRef(name="local_test_oai", provider="openai_compatible", env_var="RT_LOCAL_TEST_OAI_KEY"))
    monkeypatch.setenv("RT_LOCAL_TEST_OAI_KEY", "sk-local")
    route = RouteConfig(provider="openai_compatible", credential="local_test_oai", model="m-reason", base_url="http://localhost:8000/v1")
    cfg = RTConfig(
        mock_llm=False,
        pricing={"openai_compatible": {"m-reason": {"input_per_million": 0.55, "output_per_million": 2.19}}},
        jobs={"review": JobRoutingConfig(primary=route)},
    )
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    resp = MagicMock()
    resp.status_code = 200
    body = {
        "id": "r2",
        "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000,
                  "completion_tokens_details": {"reasoning_tokens": 600_000}},
    }
    resp.json.return_value = body
    resp.content = json.dumps(body).encode("utf-8")
    monkeypatch.setattr("rt.llm.client.requests.post", MagicMock(return_value=resp))
    telemetry = TelemetryStore()
    with use_telemetry(telemetry):
        LLMClient(force_mock=False).call_structured(
            prompt="p", system_prompt="s", response_model=_Out, job_name="review", stream=False,
        )
    assert telemetry._records[0].estimated_cost == pytest.approx(2.74)


def test_openrouter_batch_models_populates_on_first_call():
    import rt.llm.pricing as pr
    from unittest.mock import MagicMock, patch

    pr._OPENROUTER_BATCH_MODELS.clear()
    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False
    pr._OPENROUTER_RETRY_AT = 0.0

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "data": [
            {"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
            {"id": "openai/gpt-4o:batch", "pricing": {"prompt": "0.00000125", "completion": "0.000005"}},
            {"id": "anthropic/claude-3.5-sonnet:batch", "pricing": {"prompt": "0.0000015", "completion": "0.0000075"}},
        ]
    }
    try:
        with patch("requests.get", return_value=fake_resp) as get_mock:
            models = pr.openrouter_batch_models()
            assert models == ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]
            assert pr.openrouter_batch_models() == models
            assert get_mock.call_count == 1
    finally:
        pr._OPENROUTER_BATCH_MODELS.clear()
        pr._OPENROUTER_DYNAMIC_CACHE.clear()
        pr._OPENROUTER_DYNAMIC_FETCHED = True




def test_openrouter_models_retry_after_a_network_error():
    """Un errore di rete al primo tentativo non lascia il menu senza voci ':batch' per sempre."""
    import rt.llm.pricing as pr
    from unittest.mock import MagicMock, patch

    pr._OPENROUTER_BATCH_MODELS.clear()
    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False
    pr._OPENROUTER_RETRY_AT = 0.0
    pr._OPENROUTER_RETRY_AT = 0.0
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"data": [{"id": "openai/gpt-4o:batch", "pricing": {"prompt": "0.000001", "completion": "0.000004"}}]}
    try:
        with patch("requests.get", side_effect=OSError("rete")) as get_mock:
            assert pr.openrouter_batch_models() == []
            assert pr.openrouter_batch_models() == []  # niente nuovo tentativo subito
            assert get_mock.call_count == 1
        pr._OPENROUTER_RETRY_AT = 0.0  # passati i 5 minuti
        with patch("requests.get", return_value=ok):
            assert pr.openrouter_batch_models() == ["openai/gpt-4o"]
    finally:
        pr._OPENROUTER_BATCH_MODELS.clear()
        pr._OPENROUTER_DYNAMIC_CACHE.clear()
        pr._OPENROUTER_DYNAMIC_FETCHED = True
        pr._OPENROUTER_RETRY_AT = 0.0
