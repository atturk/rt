"""
tests/test_llm_config.py
Test per la configurazione ufficiale DeepSeek, Thinking Mode Low,
gestione sicura delle credenziali e assenza di fallback silenzioso.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import load_config, get_api_key, load_env_file, RTConfig, LLMModelConfig
from rt.llm.client import LLMClient, LLMError
from rt.pipeline.smoke_test import run_smoke_test, SmokeTestResponse


class SampleModel(BaseModel):
    summary: str
    item_count: int


def test_config_defaults_and_yaml_parsing():
    """Verifica che la configurazione del template config.example/ sia un guscio vuoto (provider/model a None) con parametri di tuning corretti."""
    from rt.core.config import _load_config_dir
    cfg = _load_config_dir("config.example") if os.path.isdir("config.example") else load_config()
    assert cfg.version == "2.0.0"
    assert cfg.mock_llm is False

    for job_name in ["outline", "rewrite", "review_asr", "review_science"]:
        job_cfg = cfg.llm.get(job_name)
        assert job_cfg is not None, f"Job {job_name} non configurato!"
        assert job_cfg.primary.provider is None
        assert job_cfg.primary.model is None
        assert job_cfg.primary.is_configured is False
        expected_effort = "high" if job_name in ("rewrite", "review_science") else "low"

        assert job_cfg.reasoning_effort == expected_effort
        assert job_cfg.temperature is None, "In thinking mode temperature non deve influenzare il sampling"


def test_secret_management_and_no_desktop_leak(tmp_path, monkeypatch):
    """Verifica che le chiavi provengano dalle env vars dedicate o .env e mai da file Desktop."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args: None)
    
    for provider_name, env_var in [("deepseek", "DEEPSEEK_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")]:
        monkeypatch.delenv(env_var, raising=False)
        assert get_api_key(provider_name) is None

        test_secret = f"sk-test-{provider_name}-secret-key-12345678"
        monkeypatch.setenv(env_var, test_secret)
        assert get_api_key(provider_name) == test_secret

        cfg = load_config()
        cfg_dump = cfg.model_dump_json()
        assert test_secret not in cfg_dump, f"Secret {env_var} esposto nel dump della configurazione!"


def test_secret_from_dotenv_file(tmp_path, monkeypatch):
    """Verifica caricamento sicuro di DEEPSEEK_API_KEY e OPENROUTER_API_KEY dal file .env locale."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=sk-dotenv-test-key-99999\n"
        "OPENROUTER_API_KEY=sk-or-dotenv-test-key-88888\n",
        encoding="utf-8"
    )

    load_env_file(str(env_file))
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-dotenv-test-key-99999"
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-dotenv-test-key-88888"


def test_client_request_construction_with_thinking_low(monkeypatch):
    """Verifica i parametri inviati a DeepSeek: thinking enabled, reasoning_effort low, url e headers."""
    test_key = "sk-test-deepseek-key-abcdef"
    monkeypatch.setenv("DEEPSEEK_API_KEY", test_key)

    client = LLMClient(force_mock=False)

    captured_url = None
    captured_headers = None
    captured_json = None

    def mock_post(url, headers=None, json=None, timeout=None, **kwargs):
        nonlocal captured_url, captured_headers, captured_json
        captured_url = url
        captured_headers = headers
        captured_json = json

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"summary": "Analisi biochimica", "item_count": 3}',
                        "reasoning_content": "Internal model chain-of-thought..."
                    }
                }
            ]
        }
        return mock_resp

    client.config.llm["outline"].provider = "deepseek"
    client.config.llm["outline"].base_url = "https://api.deepseek.com"
    client.config.llm["outline"].model = "deepseek-v4-flash"
    client.config.llm["outline"].reasoning_effort = "low"

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Genera riassunto",
            system_prompt="Sei un assistente scientifico",
            response_model=SampleModel,
            job_name="outline"
        )

    # Verifiche sull'endpoint e headers DeepSeek
    assert captured_url == "https://api.deepseek.com/chat/completions"
    assert captured_headers["Authorization"] == f"Bearer {test_key}"
    assert captured_headers["Content-Type"] == "application/json"

    # Verifiche sui parametri del payload DeepSeek
    assert captured_json["model"] == "deepseek-v4-flash"
    assert captured_json["thinking"] == {"type": "enabled"}
    assert captured_json["reasoning_effort"] == "low"
    assert captured_json["response_format"] == {"type": "json_object"}
    assert "temperature" not in captured_json

    assert res.summary == "Analisi biochimica"
    assert res.item_count == 3
    assert not hasattr(res, "reasoning_content")


def test_client_request_construction_openrouter_flash_0731(monkeypatch):
    """Verifica i parametri esatti inviati a OpenRouter con deepseek-v4-flash-0731."""
    test_key = "sk-or-v1-testkey123456"
    monkeypatch.setenv("OPENROUTER_API_KEY", test_key)

    client = LLMClient(force_mock=False)
    client.config.llm["outline"].reasoning_effort = "low"

    captured_url = None
    captured_headers = None
    captured_json = None

    def mock_post(url, headers=None, json=None, timeout=None, **kwargs):
        nonlocal captured_url, captured_headers, captured_json
        captured_url = url
        captured_headers = headers
        captured_json = json

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"summary": "Test OpenRouter", "item_count": 42}',
                        "reasoning_content": "OpenRouter reasoning..."
                    }
                }
            ]
        }
        return mock_resp

    # Test con modello 'deepseek-v4-flash-0731' (deve normalizzarsi a 'deepseek/deepseek-v4-flash-0731')
    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Genera test",
            system_prompt="Assistente OpenRouter",
            response_model=SampleModel,
            job_name="outline",
            override_provider="openrouter",
            override_model="deepseek-v4-flash-0731"
        )

    assert captured_url == "https://openrouter.ai/api/v1/chat/completions"
    assert captured_headers["Authorization"] == f"Bearer {test_key}"
    assert captured_headers["HTTP-Referer"] == "https://github.com/attilioturco/trt"
    assert captured_headers["X-Title"] == "RT Academic Workflow"

    # Il modello deve essere normalizzato con prefisso vendor
    assert captured_json["model"] == "deepseek/deepseek-v4-flash-0731"
    assert captured_json["reasoning"] in ({"enabled": True, "effort": "low"}, {"max_tokens": 4098})
    assert captured_json["response_format"] == {"type": "json_object"}
    assert res.summary == "Test OpenRouter"
    assert res.item_count == 42


def test_no_silent_fallback_on_missing_api_key(monkeypatch):
    """Verifica che senza chiave API il client sollevi LLMError sia per DeepSeek che per OpenRouter."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = LLMClient(force_mock=False)

    # 1. Fallimento esplicito per DeepSeek
    client.config.llm["outline"].provider = "deepseek"
    with pytest.raises(LLMError) as exc_info_ds:
        client.call_structured(
            prompt="Test",
            system_prompt="Test system",
            response_model=SampleModel,
            job_name="outline",
            override_provider="deepseek"
        )
    assert "API key mancante per il provider 'deepseek'" in str(exc_info_ds.value)
    assert "DEEPSEEK_API_KEY" in str(exc_info_ds.value)

    # 2. Fallimento esplicito per OpenRouter
    with pytest.raises(LLMError) as exc_info_or:
        client.call_structured(
            prompt="Test",
            system_prompt="Test system",
            response_model=SampleModel,
            job_name="outline",
            override_provider="openrouter"
        )
    assert "API key mancante per il provider 'openrouter'" in str(exc_info_or.value)
    assert "OPENROUTER_API_KEY" in str(exc_info_or.value)


def test_smoke_test_execution_with_mocked_network(monkeypatch):
    """Verifica che il modulo smoke_test validi le risposte sia per DeepSeek che per OpenRouter."""
    test_key_ds = "sk-deepseek-smoke-key"
    test_key_or = "sk-openrouter-smoke-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", test_key_ds)
    monkeypatch.setenv("OPENROUTER_API_KEY", test_key_or)

    def mock_post(url, headers=None, json=None, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"status": "OK", "message": "LLM operational", "test_id": 42}',
                        "reasoning_content": "Chain-of-thought internal analysis..."
                    }
                }
            ]
        }
        return mock_resp

    with patch("requests.post", side_effect=mock_post):
        # Test DeepSeek
        result_ds = run_smoke_test(provider="deepseek", model="deepseek-v4-flash", verbose=False)
        assert result_ds["connection"] == "OK"
        assert result_ds["provider"] == "deepseek"
        assert result_ds["model"] == "deepseek-v4-flash"
        assert result_ds["schema_validation"] == "OK"
        assert result_ds["test_id"] == 42

        # Test OpenRouter con deepseek-v4-flash-0731
        result_or = run_smoke_test(provider="openrouter", model="deepseek/deepseek-v4-flash-0731", verbose=False)
        assert result_or["connection"] == "OK"
        assert result_or["provider"] == "openrouter"
        assert result_or["model"] == "deepseek/deepseek-v4-flash-0731"
        assert result_or["schema_validation"] == "OK"
        assert result_or["test_id"] == 42

        # Test Google Gemini (google_1 di default)
        monkeypatch.setenv("GOOGLE_API_KEY_1", "AIzaSyFakeGoogleKey1")
        result_google = run_smoke_test(provider="google", model="gemini-2.5-flash", verbose=False)
        assert result_google["connection"] == "OK"
        assert result_google["provider"] == "google"
        assert result_google["credential"] == "google_1"
        assert result_google["model"] == "gemini-2.5-flash"
        assert result_google["schema_validation"] == "OK"
        assert result_google["test_id"] == 42

        # Test Google Gemini con credenziale esplicita google_2
        monkeypatch.setenv("GOOGLE_API_KEY_2", "AIzaSyFakeGoogleKey2")
        result_google2 = run_smoke_test(provider="google", credential="google_2", model="gemini-2.5-flash", verbose=False)
        assert result_google2["connection"] == "OK"
        assert result_google2["provider"] == "google"
        assert result_google2["credential"] == "google_2"
        assert result_google2["model"] == "gemini-2.5-flash"
        assert result_google2["schema_validation"] == "OK"
        assert result_google2["test_id"] == 42


# ======================================================================
# SPECIFIC BUG SCENARIOS (Casi A, B, C, D, E richiesti da specifica)
# ======================================================================

def test_bug_case_a_reasoning_and_clean_json_content(monkeypatch):
    """Caso A: reasoning_content='...' e content='{"summary": "...", "item_count": 1}' -> deve parsare content."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-case-a")
    client = LLMClient(force_mock=False)

    def mock_post(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"summary": "Sintesi corretta", "item_count": 5}',
                        "reasoning_content": "Pensiero interno molto elaborato che non deve essere parsato."
                    }
                }
            ]
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Genera",
            system_prompt="Sistema",
            response_model=SampleModel,
            job_name="outline"
        )

    assert res.summary == "Sintesi corretta"
    assert res.item_count == 5


def test_bug_case_b_empty_content_does_not_call_json_loads(monkeypatch):
    """Caso B: reasoning_content='...' e content='' -> non deve chiamare json.loads('') né sollevare 'Expecting value: line 1 column 1'."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-case-b")
    client = LLMClient(force_mock=False)

    def mock_post(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": "",
                        "reasoning_content": "Token esauriti durante il ragionamento interno prima dell'emissione."
                    }
                }
            ]
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(LLMError) as exc_info:
            client.call_structured(
                prompt="Genera",
                system_prompt="Sistema",
                response_model=SampleModel,
                job_name="outline",
                max_retries=1
            )

    err_str = str(exc_info.value)
    # Deve diagnosticare chiaramente content vuoto e finish_reason length, NON Expecting value: line 1 column 1
    assert "Expecting value: line 1 column 1" not in err_str
    assert "Content vuoto ricevuto dal modello" in err_str or "finish_reason='length'" in err_str


def test_bug_case_c_content_wrapped_in_markdown_fences(monkeypatch):
    """Caso C: reasoning_content='...' e content='```json\\n{...}\\n```' -> deve estrarre il JSON finale pulito."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-case-c")
    client = LLMClient(force_mock=False)

    def mock_post(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "```json\n{\n  \"summary\": \"Estratto da markdown fences\",\n  \"item_count\": 7\n}\n```",
                        "reasoning_content": "Reasoning interno prima dei blocchi di codice markdown..."
                    }
                }
            ]
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Genera",
            system_prompt="Sistema",
            response_model=SampleModel,
            job_name="outline"
        )

    assert res.summary == "Estratto da markdown fences"
    assert res.item_count == 7


def test_bug_case_d_fake_json_in_reasoning_is_never_used(monkeypatch):
    """Caso D: reasoning_content contiene JSON fittizio ma content è vuoto -> NON deve usare il reasoning come risposta."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-case-d")
    client = LLMClient(force_mock=False)

    def mock_post(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "",
                        "reasoning_content": 'Nel ragionamento ho pensato a questo JSON: {"summary": "FAKE", "item_count": 999}'
                    }
                }
            ]
        }
        return resp

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(LLMError) as exc_info:
            client.call_structured(
                prompt="Genera",
                system_prompt="Sistema",
                response_model=SampleModel,
                job_name="outline",
                max_retries=0
            )

    err_str = str(exc_info.value)
    # Non deve aver accettato il fake JSON dal reasoning
    assert "Content vuoto ricevuto dal modello" in err_str


def test_bug_case_e_schema_invalid_content_triggers_repair(monkeypatch):
    """Caso E: content contiene JSON valido ma schema Pydantic non conforme -> deve passare dal repair/retry."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-case-e")
    client = LLMClient(force_mock=False)

    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200

        if call_count == 1:
            # Primo tentativo: JSON valido ma privo del campo obbligatorio item_count
            resp.json.return_value = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"summary": "Incompleto"}',
                            "reasoning_content": "Primo tentativo..."
                        }
                    }
                ]
            }
        else:
            # Secondo tentativo (repair): JSON completo e valido
            resp.json.return_value = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"summary": "Riparato con successo", "item_count": 10}',
                            "reasoning_content": "Riparazione effettuata..."
                        }
                    }
                ]
            }
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Genera",
            system_prompt="Sistema",
            response_model=SampleModel,
            job_name="outline",
            max_retries=2
        )

    assert call_count == 2, "Il client doveva effettuare il retry di repair!"
    assert res.summary == "Riparato con successo"
    assert res.item_count == 10


def test_deepseek_build_payload_respects_capabilities():
    """
    Verifica che DeepSeekProvider.build_payload consulti get_capabilities()
    in base alla modalità thinking:
    - con thinking=False e temperature=0.7: supports_temperature=True, payload contiene 'temperature': 0.7
    - con thinking=True e temperature=0.7: supports_temperature=False, 'temperature' è assente
    """
    from rt.llm.providers.deepseek import DeepSeekProvider
    from rt.llm.capabilities import get_capabilities

    provider = DeepSeekProvider()
    caps_chat = get_capabilities("deepseek", thinking_mode=False)
    assert caps_chat.supports_temperature is True

    caps_thinking = get_capabilities("deepseek", thinking_mode=True)
    assert caps_thinking.supports_temperature is False

    # Con thinking=False e temperature=0.7, il payload DEVE contenere "temperature": 0.7
    payload_chat = provider.build_payload(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hello"}],
        thinking=False,
        temperature=0.7
    )
    assert payload_chat.get("temperature") == 0.7
    assert payload_chat.get("thinking") == {"type": "disabled"}

    # Con thinking=True e temperature=0.7, temperature DEVE restare assente indipendentemente dal valore
    payload_thinking = provider.build_payload(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": "hello"}],
        thinking=True,
        temperature=0.7
    )
    assert "temperature" not in payload_thinking, "temperature deve restare assente in thinking mode"
    assert payload_thinking.get("thinking") == {"type": "enabled"}


def test_base_url_validation_cross_provider_mismatch():
    """
    Verifica che RouteConfig impedisca configurazioni errate dovute a copia-incolla
    di base_url tra provider diversi, consentendo endpoint corretti, None o custom.
    """
    from rt.core.config import RouteConfig
    from rt.llm.providers import get_provider

    # 1. Route openrouter senza base_url: continua a funzionare e risolve l'endpoint corretto
    rc_or = RouteConfig(provider="openrouter", model="openrouter/free")
    assert rc_or.base_url is None
    p_or = get_provider(rc_or.provider)
    assert p_or.get_endpoint(rc_or.base_url) == "https://openrouter.ai/api/v1/chat/completions"

    # 2. Route google con base_url deepseek: solleva ValueError alla costruzione di RouteConfig
    with pytest.raises(ValueError) as exc_info_google:
        RouteConfig(provider="google", model="gemini-2.5-flash", base_url="https://api.deepseek.com")
    assert "corrisponde all'endpoint di default del provider 'deepseek'" in str(exc_info_google.value)
    assert "provider='google'" in str(exc_info_google.value)

    # 3. Route deepseek con base_url openrouter: solleva ValueError allo stesso modo
    with pytest.raises(ValueError) as exc_info_ds:
        RouteConfig(provider="deepseek", model="deepseek-chat", base_url="https://openrouter.ai/api/v1")
    assert "corrisponde all'endpoint di default del provider 'openrouter'" in str(exc_info_ds.value)
    assert "provider='deepseek'" in str(exc_info_ds.value)

    # 4. Route con base_url custom non riconducibile a provider noti: accettata senza errori
    rc_proxy_google = RouteConfig(
        provider="google",
        model="gemini-2.5-flash",
        base_url="https://my-internal-proxy.example.com/v1"
    )
    assert rc_proxy_google.base_url == "https://my-internal-proxy.example.com/v1"

    rc_proxy_ds = RouteConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://my-internal-proxy.example.com/v1"
    )
    assert rc_proxy_ds.base_url == "https://my-internal-proxy.example.com/v1"


def test_load_config_with_primary_routes_list_yaml(tmp_path):
    """Verifica che un file YAML con sintassi di lista per primary_routes venga caricato correttamente tramite PyYAML."""
    yaml_content = """version: "2.0.0"
jobs:
  outline:
    primary_routes:
      - provider: "google"
        credential: "google_1"
        model: "gemini-2.5-flash"
      - provider: "google"
        credential: "google_2"
        model: "gemini-2.5-flash"
    round_robin: true
"""
    cfg_file = tmp_path / "rt.config.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(str(cfg_file))
    assert cfg.version == "2.0.0"
    outline_job = cfg.jobs["outline"]
    assert outline_job.primary_routes is not None
    assert len(outline_job.primary_routes) == 2
    assert outline_job.primary_routes[0].credential == "google_1"
    assert outline_job.primary_routes[1].credential == "google_2"
    assert outline_job.primary.credential == "google_1"
    assert outline_job.secondary.credential == "google_2"
    assert outline_job.round_robin is True




