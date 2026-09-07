"""
tests/test_openai_compatible_provider.py
Unit test e test di integrazione per il provider generico OpenAICompatibleProvider
e la registrazione dichiarativa di credenziali custom da YAML.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RouteConfig, JobRoutingConfig, RTConfig, load_config
from rt.llm.providers.openai_compatible import OpenAICompatibleProvider
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
from rt.llm.client import LLMClient


class DummySchema(BaseModel):
    title: str
    points: list[str]


def test_openai_compatible_build_payload():
    """Verifica che build_payload non includa campi proprietari di vendor (thinking, reasoning)."""
    provider = OpenAICompatibleProvider()
    assert provider.name == "openai_compatible"

    payload = provider.build_payload(
        model="mistral-large-latest",
        messages=[{"role": "user", "content": "Analizza il testo"}],
        max_tokens=4096,
        thinking=True,
        reasoning_effort="high",
        temperature=0.3,
        response_format={"type": "json_object"},
        stream=True,
        max_thinking_tokens=2048,
    )

    assert "thinking" not in payload
    assert "reasoning" not in payload
    assert "reasoning_effort" not in payload
    assert "max_thinking_tokens" not in payload

    assert payload["model"] == "mistral-large-latest"
    assert payload["messages"] == [{"role": "user", "content": "Analizza il testo"}]
    assert payload["max_tokens"] == 4096
    assert payload["temperature"] == 0.3
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_openai_compatible_uses_json_schema_when_available():
    """Molti server OpenAI-compatible locali (LM Studio/llama.cpp) rifiutano
    response_format.type == 'json_object' con l'errore "must be 'json_schema' or 'text'".
    Se è disponibile lo schema del modello di risposta atteso, build_payload deve costruire
    un response_format di tipo 'json_schema' invece del generico 'json_object'."""
    provider = OpenAICompatibleProvider()

    class DummyResponseModel(BaseModel):
        summary: str
        items: list

    payload = provider.build_payload(
        model="google/gemma-4-26b-a4b-qat",
        messages=[{"role": "user", "content": "Analizza il testo"}],
        response_format={"type": "json_object"},
        response_json_schema=DummyResponseModel.model_json_schema(),
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == DummyResponseModel.model_json_schema()
    assert "properties" in payload["response_format"]["json_schema"]["schema"]

    # Senza response_json_schema, comportamento invariato (json_object generico passato dal chiamante)
    payload_fallback = provider.build_payload(
        model="google/gemma-4-26b-a4b-qat",
        messages=[{"role": "user", "content": "Analizza il testo"}],
        response_format={"type": "json_object"},
        response_json_schema=None,
    )
    assert payload_fallback["response_format"] == {"type": "json_object"}


def test_openai_compatible_endpoint_and_headers():
    """Verifica endpoint validation, stripping trailing slash e gestione /chat/completions."""
    provider = OpenAICompatibleProvider()

    # Senza base_url solleva ValueError
    with pytest.raises(ValueError, match="richiede un 'base_url' esplicito"):
        provider.get_endpoint(None)

    with pytest.raises(ValueError, match="richiede un 'base_url' esplicito"):
        provider.get_endpoint("")

    # Con base_url standard
    ep1 = provider.get_endpoint("https://api.mistral.ai/v1")
    assert ep1 == "https://api.mistral.ai/v1/chat/completions"

    # Con trailing slash
    ep2 = provider.get_endpoint("https://api.mistral.ai/v1/")
    assert ep2 == "https://api.mistral.ai/v1/chat/completions"

    # Con /chat/completions già incluso
    ep3 = provider.get_endpoint("https://api.mistral.ai/v1/chat/completions")
    assert ep3 == "https://api.mistral.ai/v1/chat/completions"

    # Headers
    headers = provider.get_headers("my-secret-key-123")
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer my-secret-key-123"


def test_openai_compatible_route_config_validation():
    """Verifica che RouteConfig richieda base_url per openai_compatible."""
    GLOBAL_CREDENTIALS.register(
        CredentialRef(name="test_openai_compat_route_cred", provider="openai_compatible", env_var="TEST_VAR")
    )

    # Senza base_url deve fallire
    with pytest.raises(ValueError, match="richiede 'base_url' esplicito nella route"):
        RouteConfig(
            provider="openai_compatible",
            model="mistral-large-latest",
            credential="test_openai_compat_route_cred",
        )

    # Con base_url e credenziale valida deve riuscire
    route = RouteConfig(
        provider="openai_compatible",
        model="mistral-large-latest",
        credential="test_openai_compat_route_cred",
        base_url="https://api.mistral.ai/v1",
    )
    assert route.provider == "openai_compatible"
    assert route.model == "mistral-large-latest"
    assert route.base_url == "https://api.mistral.ai/v1"


def test_openai_compatible_streaming_and_normalization():
    """Verifica parse_stream_line e normalize_response."""
    provider = OpenAICompatibleProvider()

    # Parse stream line standard
    line = 'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Ciao"},"finish_reason":null}],"model":"mistral-large"}'
    chunk = provider.parse_stream_line(line)
    assert chunk is not None
    assert chunk.content_delta == "Ciao"
    assert chunk.finish_reason is None
    assert chunk.resolved_model == "mistral-large"

    # [DONE] line
    assert provider.parse_stream_line("data: [DONE]") is None
    assert provider.parse_stream_line("") is None
    assert provider.parse_stream_line("invalid json data: {foo}") is None

    # Normalizzazione risposta completa
    raw_response = {
        "id": "chatcmpl-123",
        "model": "mistral-large",
        "choices": [
            {
                "message": {"role": "assistant", "content": '{"title": "Test", "points": ["P1"]}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    norm = provider.normalize_response(raw_response, model_name="mistral-large-latest")
    assert norm.content == '{"title": "Test", "points": ["P1"]}'
    assert norm.finish_reason == "stop"
    assert norm.provider == "openai_compatible"
    assert norm.model == "mistral-large-latest"
    assert norm.resolved_model == "mistral-large"
    assert norm.request_id == "chatcmpl-123"


def test_openai_compatible_e2e_call_structured(monkeypatch):
    """Verifica chiamata end-to-end con LLMClient e mock di requests.post."""
    GLOBAL_CREDENTIALS.register(
        CredentialRef(
            name="test_openai_compat_e2e_cred",
            provider="openai_compatible",
            env_var="TEST_OPENAI_COMPAT_KEY",
        )
    )
    monkeypatch.setenv("TEST_OPENAI_COMPAT_KEY", "sk-mistral-test-key-123")
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        primary=RouteConfig(
            provider="openai_compatible",
            credential="test_openai_compat_e2e_cred",
            model="mistral-large-latest",
            base_url="https://api.mistral.ai/v1",
            thinking=False,
            timeout_seconds=60,
        )
    )

    mock_resp_json = {
        "id": "gen-12345",
        "model": "mistral-large-latest",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"title": "Biochimica", "points": ["Glicolisi", "Ciclo di Krebs"]}),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
    }

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = mock_resp_json
    mock_post_resp.text = json.dumps(mock_resp_json)

    with patch("requests.post", return_value=mock_post_resp) as mock_post:
        result = client.call_structured(
            job_name="outline",
            system_prompt="Sei un assistente didattico.",
            prompt="Genera outline.",
            response_model=DummySchema,
            stream=False,
        )

        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.mistral.ai/v1/chat/completions"
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-mistral-test-key-123"

        body = call_args[1]["json"]
        assert body["model"] == "mistral-large-latest"
        assert "thinking" not in body

        assert isinstance(result, DummySchema)
        assert result.title == "Biochimica"
        assert result.points == ["Glicolisi", "Ciclo di Krebs"]


def test_yaml_config_loading_with_custom_credentials(tmp_path, monkeypatch):
    """Verifica che una configurazione YAML con custom credentials e job openai_compatible si carichi correttamente."""
    yaml_content = """
version: "2.0.0"
credentials:
  - name: "mistral_yaml_test"
    provider: "openai_compatible"
    env_var: "MISTRAL_API_KEY_TEST"

jobs:
  outline:
    primary:
      provider: "openai_compatible"
      credential: "mistral_yaml_test"
      model: "mistral-large-latest"
      base_url: "https://api.mistral.ai/v1"
      thinking: false
      timeout_seconds: 180
"""
    config_file = tmp_path / "rt.config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    # Carica la configurazione: la registrazione della credenziale deve avvenire prima della validazione
    cfg = load_config(str(config_file))

    assert "outline" in cfg.jobs
    outline_route = cfg.jobs["outline"].primary
    assert outline_route.provider == "openai_compatible"
    assert outline_route.credential == "mistral_yaml_test"
    assert outline_route.base_url == "https://api.mistral.ai/v1"
    assert GLOBAL_CREDENTIALS.validate_credential("openai_compatible", "mistral_yaml_test") is True
    assert GLOBAL_CREDENTIALS.get_env_var_name("mistral_yaml_test") == "MISTRAL_API_KEY_TEST"


def test_credential_registry_get_env_var_name():
    """Verifica il metodo get_env_var_name su credenziali note, custom e inesistenti."""
    assert GLOBAL_CREDENTIALS.get_env_var_name("deepseek") == "DEEPSEEK_API_KEY"
    assert GLOBAL_CREDENTIALS.get_env_var_name("openrouter") == "OPENROUTER_API_KEY"
    assert GLOBAL_CREDENTIALS.get_env_var_name("google_1") == "GOOGLE_API_KEY_1"
    assert GLOBAL_CREDENTIALS.get_env_var_name("google_2") == "GOOGLE_API_KEY_2"
    assert GLOBAL_CREDENTIALS.get_env_var_name("mock") is None
    assert GLOBAL_CREDENTIALS.get_env_var_name("non_existent_cred") is None
