"""
tests/test_llm_router.py
Test di conformità per RT 2.0 LLM Routing Engine:
- Credential Registry e Dual-Key Google (google_1, google_2, secret redaction, validazione load-time)
- Round-Robin scheduling (alternanza deterministica e thread-safety)
- Loop Protection (visited_routes e hard cap max_attempts)
- Le 4 Classi di Failover Obbligatorie:
    - Scenario A: Google_1 -> safety block -> Google_2 -> success
    - Scenario B: Google_1 -> HTTP 429 -> OpenRouter -> success
    - Scenario C: Google_1 -> timeout -> DeepSeek -> success
    - Scenario D: Google_1 -> HTTP 401 -> fallback.auth (Google_2) -> success
- Output Explosion Guard (limite rigido caratteri con abort stream e failover)
- Telemetria con execution_id condiviso per l'intera catena di esecuzione
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RTConfig, RouteConfig, JobRoutingConfig, JobFallbackConfig
from rt.llm.client import LLMClient, LLMError, LLMTimeoutError
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRegistry, CredentialRef
from rt.llm.errors import (
    SafetyFailure, RateLimitFailure, TimeoutFailure,
    AuthenticationFailure, OutputLimitFailure
)
from rt.llm.telemetry import GLOBAL_TELEMETRY


class DummyItem(BaseModel):
    title: str
    summary: str


# ======================================================================
# 1. CREDENTIAL REGISTRY, DUAL-KEY GOOGLE & LOAD-TIME VALIDATION
# ======================================================================

def test_credential_registry_resolution(monkeypatch):
    """Verifica risoluzione corretta di credenziali registrate esplicitamente."""
    reg = CredentialRegistry()
    reg.register(CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"))
    reg.register(CredentialRef(name="google_2", provider="google", env_var="GOOGLE_API_KEY_2"))
    reg.register(CredentialRef(name="openrouter", provider="openrouter", env_var="OPENROUTER_API_KEY"))
    reg.register(CredentialRef(name="deepseek", provider="deepseek", env_var="DEEPSEEK_API_KEY"))

    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-google-1-secret")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key-google-2-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek-secret")

    reg.reload_from_env()

    assert reg.get_api_key("google_1") == "key-google-1-secret"
    assert reg.get_api_key("google_2") == "key-google-2-secret"
    assert reg.get_api_key("openrouter") == "key-openrouter-secret"
    assert reg.get_api_key("deepseek") == "key-deepseek-secret"


def test_secret_redaction_in_messages_and_errors(monkeypatch):
    """Verifica che nessun segreto appaia in chiaro nei messaggi sanitizzati."""
    reg = CredentialRegistry()
    reg.register(CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"))
    reg.register(CredentialRef(name="deepseek", provider="deepseek", env_var="DEEPSEEK_API_KEY"))
    monkeypatch.setenv("GOOGLE_API_KEY_1", "AIzaSySecretGoogleKey123")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-deepseek-456")
    reg.reload_from_env()

    raw_msg = "Error contacting endpoint with key AIzaSySecretGoogleKey123 and sk-secret-deepseek-456"
    sanitized = reg.sanitize_secrets(raw_msg)

    assert "AIzaSySecretGoogleKey123" not in sanitized
    assert "sk-secret-deepseek-456" not in sanitized
    assert "[REDACTED:google_1]" in sanitized
    assert "[REDACTED:deepseek]" in sanitized


def test_config_validation_provider_credential_compatibility():
    """Verifica che associare una credenziale errata a un provider sollevi ValueError al load."""
    # Credenziale valida per google
    r_ok = RouteConfig(route_id="r1", provider="google", credential="google_1", model="gemini-2.0-flash")
    assert r_ok.credential == "google_1"

    # Credenziale non valida per google (deepseek su google) -> deve fallire al load!
    with pytest.raises(ValueError, match="incompatibile con il provider"):
        RouteConfig(route_id="r2", provider="google", credential="deepseek", model="gemini-2.0-flash")

    # Credenziale non valida per deepseek (openrouter su deepseek)
    with pytest.raises(ValueError, match="incompatibile con il provider"):
        RouteConfig(route_id="r3", provider="deepseek", credential="openrouter", model="deepseek-chat")


# ======================================================================
# 2. ROUND-ROBIN SCHEDULING & LOOP PROTECTION
# ======================================================================

def test_round_robin_selection_alternation(monkeypatch):
    """Verifica che round_robin: true alterni deterministamente le primary_routes."""
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key2")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        round_robin=True,
        primary_routes=[
            RouteConfig(route_id="google_p1", provider="google", credential="google_1", model="gemini-2.0-flash"),
            RouteConfig(route_id="google_p2", provider="google", credential="google_2", model="gemini-2.5-flash"),
        ]
    )

    r1 = client.router.select_initial_route("outline")
    r2 = client.router.select_initial_route("outline")
    r3 = client.router.select_initial_route("outline")
    r4 = client.router.select_initial_route("outline")

    assert r1.route.route_id == "google_p1"
    assert r2.route.route_id == "google_p2"
    assert r3.route.route_id == "google_p1"
    assert r4.route.route_id == "google_p2"


def test_round_robin_disabled(monkeypatch):
    """Verifica che con round_robin: false la prima route sia sempre selezionata come primaria."""
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key2")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        round_robin=False,
        primary_routes=[
            RouteConfig(route_id="google_p1", provider="google", credential="google_1", model="gemini-2.0-flash"),
            RouteConfig(route_id="google_p2", provider="google", credential="google_2", model="gemini-2.5-flash"),
        ]
    )

    assert client.router.select_initial_route("outline").route.route_id == "google_p1"
    assert client.router.select_initial_route("outline").route.route_id == "google_p1"


def test_round_robin_5_way_cycling(monkeypatch):
    """Verifica che round_robin con 5 primary_routes cicli su tutte e 5 le route in ordine."""
    for i in range(1, 6):
        monkeypatch.setenv(f"GOOGLE_API_KEY_{i}", f"key{i}")
        GLOBAL_CREDENTIALS.register(CredentialRef(name=f"google_{i}", provider="google", env_var=f"GOOGLE_API_KEY_{i}"))
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["rewrite"] = JobRoutingConfig(
        max_attempts=5,
        round_robin=True,
        primary_routes=[
            RouteConfig(route_id=f"google_r{i}", provider="google", credential=f"google_{i}", model="gemini-2.5-flash")
            for i in range(1, 6)
        ]
    )

    expected_ids = [f"google_r{i}" for i in range(1, 6)] * 2 + ["google_r1", "google_r2"]
    actual_ids = [client.router.select_initial_route("rewrite").route.route_id for _ in range(12)]
    assert actual_ids == expected_ids


def test_round_robin_single_route_validation_error(monkeypatch):
    """Verifica che primary_routes con un solo elemento e round_robin: true sollevi ValueError."""
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key1")
    GLOBAL_CREDENTIALS.reload_from_env()

    with pytest.raises(ValueError, match="round_robin è abilitato ma è disponibile una sola route"):
        JobRoutingConfig(
            round_robin=True,
            primary_routes=[
                RouteConfig(route_id="google_p1", provider="google", credential="google_1", model="gemini-2.0-flash")
            ]
        )


def test_loop_protection_prevents_routing_cycles(monkeypatch):
    """Verifica che visited_routes impedisca di tornare su una route già visitata generando loop infiniti."""
    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=5,
        primary_routes=[
            RouteConfig(route_id="route_A", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            generic=RouteConfig(route_id="route_A", provider="google", credential="google_1", model="gemini-2.0-flash")
        )
    )

    # Route_A è già in visited_routes
    visited = {"route_A"}
    fail = RateLimitFailure("429 Too Many Requests")
    next_route = client.router.select_fallback_route("outline", failure=fail, visited_route_ids=visited, current_attempt=1)

    # Il router non deve riproporre route_A
    assert next_route is None


# ======================================================================
# 3. LE 4 CLASSI DI FAILOVER OBBLIGATORIE (SCENARI A, B, C, D)
# ======================================================================

def test_scenario_a_safety_google1_to_google2(monkeypatch):
    """
    SCENARIO A:
    Google_1 -> safety block (finishReason='SAFETY' o promptFeedback) -> fallback.safety (Google_2) -> success.
    Verifica classificazione safety, transizione di credential e condivisione di execution_id.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key-g2")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            safety=RouteConfig(route_id="r_google_2", provider="google", credential="google_2", model="gemini-2.5-flash")
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"

        if call_count == 1:
            # Google 1 invia chunk con finish_reason SAFETY
            chunks = [
                b'data: {"id": "req_safe", "promptFeedback": {"blockReason": "SAFETY"}, "choices": []}\n\n'
            ]
            resp.iter_lines.return_value = chunks
        else:
            # Google 2 invia risposta JSON valida
            valid_json = json.dumps({"title": "Successo Google 2", "summary": "Superato blocco safety"})
            chunks = [
                f'data: {{"id": "req_ok", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 50}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test user",
            system_prompt="Test system",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_scenario_a"
        )

    assert res.title == "Successo Google 2"
    assert call_count == 2

    records = GLOBAL_TELEMETRY.get_all()
    safe_rec = [r for r in records if r.unit_id == "unit_scenario_a"]
    assert len(safe_rec) == 2

    att1, att2 = safe_rec[0], safe_rec[1]
    # Controllo attempt 1
    assert att1.attempt == 1
    assert att1.route_id == "r_google_1"
    assert att1.credential_ref == "google_1"
    assert att1.failure_class == "safety"
    assert att1.status == "error"
    assert att1.fallback_to_credential == "google_2"

    # Controllo attempt 2
    assert att2.attempt == 2
    assert att2.parent_attempt == 1
    assert att2.route_id == "r_google_2"
    assert att2.credential_ref == "google_2"
    assert att2.status == "success"

    # Unicità e continuità di execution_id
    assert att1.execution_id == att2.execution_id
    assert att1.execution_id.startswith("exec_")


def test_scenario_b_rate_limit_google1_to_openrouter(monkeypatch):
    """
    SCENARIO B:
    Google_1 -> HTTP 429 (Rate Limit) -> fallback.rate_limit (OpenRouter) -> success.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct")
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count == 1:
            resp.status_code = 429
            resp.content = b'{"error": {"message": "Resource has been exhausted (e.g. check quota)."}}'
            resp.text = resp.content.decode("utf-8")
            resp.headers = {"Retry-After": "5"}
        else:
            resp.status_code = 200
            valid_json = json.dumps({"title": "Successo OpenRouter", "summary": "Superato rate limit 429"})
            chunks = [
                f'data: {{"id": "req_or", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 40}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test user",
            system_prompt="Test system",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_scenario_b"
        )

    assert res.title == "Successo OpenRouter"
    assert call_count == 2

    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_scenario_b"]
    assert len(records) == 2
    att1, att2 = records[0], records[1]
    assert att1.failure_class == "rate_limit"
    assert att1.http_status == 429
    assert att1.fallback_to_provider == "openrouter"
    assert att2.provider == "openrouter"
    assert att2.status == "success"
    assert att1.execution_id == att2.execution_id


def test_scenario_c_timeout_google1_to_deepseek(monkeypatch):
    """
    SCENARIO C:
    Google_1 -> Timeout wall-clock -> fallback.timeout (DeepSeek) -> success.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    # Nessun timeout retry locale per scattare direttamente sul fallback route
    client.config.retry.max_timeout_retries = 0
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash", timeout_seconds=1)
        ],
        fallback=JobFallbackConfig(
            timeout=RouteConfig(route_id="r_deepseek", provider="deepseek", credential="deepseek", model="deepseek-chat", timeout_seconds=10)
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count == 1:
            # Generatore che supera la deadline di 1 secondo
            def sleeping_generator():
                time.sleep(1.2)
                yield b'data: {"choices": [{"delta": {"content": "late"}}]}\n\n'
            resp.status_code = 200
            resp.iter_lines.side_effect = lambda decode_unicode=False: sleeping_generator()
        else:
            resp.status_code = 200
            valid_json = json.dumps({"title": "Successo DeepSeek", "summary": "Superato timeout Google"})
            chunks = [
                f'data: {{"id": "req_ds", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 45}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test user",
            system_prompt="Test system",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_scenario_c"
        )

    assert res.title == "Successo DeepSeek"
    assert call_count == 2

    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_scenario_c"]
    assert len(records) == 2
    att1, att2 = records[0], records[1]
    assert att1.failure_class == "timeout"
    assert att1.fallback_to_provider == "deepseek"
    assert att2.provider == "deepseek"
    assert att2.status == "success"
    assert att1.execution_id == att2.execution_id


def test_scenario_d_auth_error_google1_to_google2(monkeypatch):
    """
    SCENARIO D:
    Google_1 -> HTTP 401 Unauthorized (chiave errata/scaduta) -> fallback.auth (Google_2) -> success.
    Verifica che non ci sia retry sulla stessa route con chiave non valida e transiti su fallback.auth.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1-invalid")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key-g2-valid")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            auth=RouteConfig(route_id="r_google_2", provider="google", credential="google_2", model="gemini-2.0-flash")
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count == 1:
            resp.status_code = 401
            resp.content = b'{"error": {"message": "API_KEY_INVALID: User not authorized"}}'
            resp.text = resp.content.decode("utf-8")
        else:
            resp.status_code = 200
            valid_json = json.dumps({"title": "Successo Auth Fallback", "summary": "Risolto con Google 2"})
            chunks = [
                f'data: {{"id": "req_auth_ok", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 30}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test user",
            system_prompt="Test system",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_scenario_d"
        )

    assert res.title == "Successo Auth Fallback"
    assert call_count == 2

    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_scenario_d"]
    assert len(records) == 2
    att1, att2 = records[0], records[1]
    assert att1.failure_class == "auth_error"
    assert att1.http_status == 401
    assert att1.fallback_to_credential == "google_2"
    assert att2.credential_ref == "google_2"
    assert att2.status == "success"
    assert att1.execution_id == att2.execution_id


# ======================================================================
# 4. OUTPUT EXPLOSION GUARD (LIMIT RIGIDO 45.000 CARATTERI / CUSTOM)
# ======================================================================

def test_output_explosion_guard_streaming_abort(monkeypatch):
    """Verifica che l'Output Explosion Guard interrompa lo stream non appena supera il limite massimo di caratteri."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    # Imposta un limite custom rigido di 300 caratteri per il test
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=1,
        max_output_chars=300,
        primary_routes=[
            RouteConfig(route_id="r_deepseek", provider="deepseek", credential="deepseek", model="deepseek-chat")
        ]
    )

    def runaway_generator():
        # Genera chunk ripetuti per 1000 caratteri
        for i in range(10):
            yield f'data: {{"id": "runaway", "choices": [{{"delta": {{"content": "{"A" * 100}"}}}}]}}\n\n'.encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.encoding = "utf-8"
    mock_resp.iter_lines.side_effect = lambda decode_unicode=False: runaway_generator()

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(LLMError) as exc_info:
            client.call_structured(
                prompt="Test user",
                system_prompt="Test system",
                response_model=DummyItem,
                job_name="outline",
                unit_id="unit_runaway"
            )

    assert "Output explosion guard attivata" in str(exc_info.value)
    # Verifica telemetria per output_limit (1 primario + 2 same-route retries)
    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_runaway"]
    assert len(records) == 3
    assert all(r.failure_class == "output_limit" for r in records)
    assert all(r.output_chars > 300 for r in records)


def test_output_explosion_guard_streaming_ignores_reasoning(monkeypatch):
    """
    Verifica che l'Output Explosion Guard in streaming calcoli solo content_parts,
    ignorando reasoning_parts: se reasoning_delta supera ampiamente max_output_chars
    ma content_delta finale è contenuto, non viene sollevata OutputLimitFailure
    e la chiamata completa con successo.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    # Limite custom rigido di 300 caratteri
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=1,
        max_output_chars=300,
        primary_routes=[
            RouteConfig(route_id="r_deepseek", provider="deepseek", credential="deepseek", model="deepseek-reasoner")
        ]
    )

    def reasoning_heavy_generator():
        # Genera 1000 caratteri di reasoning (ben oltre la soglia di 300)
        for _ in range(10):
            yield f'data: {{"id": "reasoning_heavy", "choices": [{{"delta": {{"reasoning_content": "{"R" * 100}"}}}}]}}\n\n'.encode("utf-8")
        # Genera un content JSON finale valido e ben al di sotto dei 300 caratteri
        valid_json = json.dumps({"title": "Outline Valida", "summary": "Reasoning ignorato con successo"})
        yield f'data: {{"id": "reasoning_heavy", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 150}}}}\n\n'.encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.encoding = "utf-8"
    mock_resp.iter_lines.side_effect = lambda decode_unicode=False: reasoning_heavy_generator()

    with patch("requests.post", return_value=mock_resp):
        res = client.call_structured(
            prompt="Test prompt",
            system_prompt="Test system",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_reasoning_ok"
        )

    assert res.title == "Outline Valida"
    assert res.summary == "Reasoning ignorato con successo"

    # Verifica telemetria: successo e output_chars riflette solo il contenuto
    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_reasoning_ok"]
    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].output_chars < 300


# ======================================================================
# 5. GENERALIZED LOOP PROTECTION CASCADE & DECOUPLED SAME-ROUTE RETRY
# ======================================================================

def test_generalized_loop_protection_cascade():
    """
    Verifica la cascata generalizzata della Loop Protection:
    Se la route candidata è già visitata:
    1. Cerca una route alternativa configurata non ancora visitata;
    2. Se non trovata o già visitata, passa a fallback.generic;
    3. Se anche generic è già visitata, termina la catena (None).
    """
    cfg = RTConfig(
        jobs={
            "rewrite": JobRoutingConfig(
                round_robin=True,
                max_attempts=5,
                primary=RouteConfig(route_id="r_g1", provider="google", credential="google_1", model="gemini-2.5-flash"),
                secondary=RouteConfig(route_id="r_g2", provider="google", credential="google_2", model="gemini-2.5-flash"),
                fallback=JobFallbackConfig(
                    auth=RouteConfig(route_id="r_g2", provider="google", credential="google_2", model="gemini-2.5-flash"),
                    generic=RouteConfig(route_id="r_or", provider="openrouter", credential="openrouter", model="deepseek/deepseek-chat")
                )
            )
        }
    )
    from rt.llm.router import RoutingEngine
    router = RoutingEngine(cfg)

    auth_err = AuthenticationFailure("401 Unauthorized")

    # Step 1: Inizio su r_g2 (già visitata). Il candidato auth è r_g2 (visitata).
    # La cascata seleziona l'alternativa configurata r_g1.
    res1 = router.select_fallback_route("rewrite", failure=auth_err, visited_route_ids={"r_g2"}, current_attempt=1)
    assert res1 is not None
    assert res1.route.route_id == "r_g1"
    assert res1.route_role == "fallback_alternative_configured"

    # Step 2: Sia r_g2 che r_g1 sono state visitate.
    # La cascata passa a fallback.generic (r_or).
    res2 = router.select_fallback_route("rewrite", failure=auth_err, visited_route_ids={"r_g2", "r_g1"}, current_attempt=2)
    assert res2 is not None
    assert res2.route.route_id == "r_or"
    assert res2.route_role == "fallback_generic"

    # Step 3: Anche generic (r_or) è stata visitata.
    # La cascata termina (None) prevenendo cicli infiniti.
    res3 = router.select_fallback_route("rewrite", failure=auth_err, visited_route_ids={"r_g2", "r_g1", "r_or"}, current_attempt=3)
    assert res3 is None


def test_same_route_timeout_retry_distinct_from_routing_failover(monkeypatch):
    """
    Verifica che il retry bounded per timeout sulla stessa route (retry.max_timeout_retries)
    NON consumi il budget di transizioni tra route diverse (max_attempts).
    Con max_attempts=2 e max_timeout_retries=1:
    - Route 1: Attempt 1 va in timeout -> retry 1 va in timeout (2 tentativi locali sulla stessa route);
    - Failover: Scatta su Route 2 (global_attempt=2) -> successo;
    - Risultato: Successo finale garantito e nessuna terminazione prematura.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 1
    client.config.retry.timeout_backoff_seconds = 0.05
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=2,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash", timeout_seconds=1)
        ],
        fallback=JobFallbackConfig(
            timeout=RouteConfig(route_id="r_deepseek", provider="deepseek", credential="deepseek", model="deepseek-chat", timeout_seconds=10)
        )
    )

    call_count = 0
    route_called = []

    def mock_post(url, headers=None, json=None, timeout=None, stream=None):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.encoding = "utf-8"

        if call_count in (1, 2):
            # Primi due tentativi (entrambi su Route 1 Google): timeout simulato
            route_called.append("google_1")
            def slow_stream():
                time.sleep(1.2)
                yield b'data: {"choices": [{"delta": {"content": "slow"}}]}\n\n'
            resp.status_code = 200
            resp.iter_lines.side_effect = lambda decode_unicode=False: slow_stream()
        else:
            # Terzo tentativo (scattato come routing failover su Route 2 DeepSeek): successo!
            import json as _json_mod
            route_called.append("deepseek")
            resp.status_code = 200
            valid_str = _json_mod.dumps({"title": "Decoupled Retry Success", "summary": "Both local retry and failover worked"})
            chunks = [
                f'data: {{"id": "req_ok", "choices": [{{"delta": {{"content": {_json_mod.dumps(valid_str)}}}}}, {{"delta": {{}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 40}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    GLOBAL_TELEMETRY.clear()

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test prompt",
            system_prompt="Test sys",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_decoupled_test"
        )

    assert res.title == "Decoupled Retry Success"
    assert call_count == 3
    assert route_called == ["google_1", "google_1", "deepseek"]

    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_decoupled_test"]
    assert len(records) == 3

    # Attempt 1: Route 1, timeout, retry_count=0
    assert records[0].route_id == "r_google_1"
    assert records[0].status == "timeout"
    assert records[0].retry_count == 0

    # Attempt 2: Route 1 (same-route retry), timeout, retry_count=1
    assert records[1].route_id == "r_google_1"
    assert records[1].status == "timeout"
    assert records[1].retry_count == 1

    # Attempt 3: Route 2 (routing failover attempt 2), success!
    assert records[2].route_id == "r_deepseek"
    assert records[2].status == "success"
    assert records[2].parent_attempt == 2


def test_unconfigured_job_without_default_raises_value_error():
    """Verifica che la richiesta di configurazione per un job inesistente e senza 'default' sollevi ValueError."""
    import pytest
    from rt.core.config import RTConfig
    from rt.llm.router import RoutingEngine
    config = RTConfig(jobs={}, llm={})
    engine = RoutingEngine(config)
    with pytest.raises(ValueError, match="Nessuna configurazione di routing trovata per il job 'nonexistent'"):
        engine._get_job_config("nonexistent")


def test_unconfigured_job_without_default_raises_value_error_in_llm_client():
    """Verifica che LLMClient._get_job_routing_config sollevi ValueError se un job non è configurato e manca il default."""
    import pytest
    from rt.core.config import RTConfig
    from rt.llm.client import LLMClient
    client = LLMClient(force_mock=True)
    client.config = RTConfig(jobs={}, llm={})
    with pytest.raises(ValueError, match="Nessuna configurazione di routing trovata per il job 'nonexistent'"):
        client._get_job_routing_config("nonexistent")


# ======================================================================
# 7. TASK 63: ROUND-ROBIN POOL EXHAUSTION & PER-JOB FALLBACK COOLDOWN
# ======================================================================

def test_round_robin_pool_exhaustion_before_dedicated_fallback(monkeypatch):
    """
    Verifica che con un pool di 3 route round-robin, un 429 provi tutte le route del pool
    prima di scalare alla route di fallback dedicata (OpenRouter).
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key-g2")
    monkeypatch.setenv("GOOGLE_API_KEY_3", "key-g3")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=5,
        round_robin=True,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash"),
            RouteConfig(route_id="r_google_2", provider="google", credential="google_2", model="gemini-2.0-flash"),
            RouteConfig(route_id="r_google_3", provider="google", credential="google_3", model="gemini-2.0-flash"),
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct")
        )
    )

    routes_called = []

    def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.encoding = "utf-8"
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        
        if "key-g1" in auth_hdr:
            routes_called.append("g1")
            resp.status_code = 429
            resp.content = b'{"error": {"message": "Resource exhausted"}}'
            resp.text = resp.content.decode("utf-8")
        elif "key-g2" in auth_hdr:
            routes_called.append("g2")
            resp.status_code = 429
            resp.content = b'{"error": {"message": "Resource exhausted"}}'
            resp.text = resp.content.decode("utf-8")
        elif "key-g3" in auth_hdr:
            routes_called.append("g3")
            resp.status_code = 429
            resp.content = b'{"error": {"message": "Resource exhausted"}}'
            resp.text = resp.content.decode("utf-8")
        else:
            routes_called.append("openrouter")
            resp.status_code = 200
            valid_json = json.dumps({"title": "Successo Finale", "summary": "Dopo 3 chiavi round-robin"})
            chunks = [
                f'data: {{"id": "req_or", "choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}], "usage": {{"total_tokens": 40}}}}\n\n'.encode("utf-8")
            ]
            resp.iter_lines.return_value = chunks
        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test prompt",
            system_prompt="Test sys",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_pool_exhaust"
        )

    assert res.title == "Successo Finale"
    assert routes_called == ["g1", "g2", "g3", "openrouter"]

    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_pool_exhaust"]
    assert len(records) == 4
    # Tentativo 1 (g1): fallback alla prossima route configurata del pool (g2), non a openrouter
    assert records[0].credential_ref == "google_1"
    assert records[0].fallback_to_credential == "google_2"
    # Tentativo 2 (g2): fallback a g3
    assert records[1].credential_ref == "google_2"
    assert records[1].fallback_to_credential == "google_3"
    # Tentativo 3 (g3): pool esaurito, scala a openrouter
    assert records[2].credential_ref == "google_3"
    assert records[2].fallback_to_provider == "openrouter"
    # Tentativo 4 (openrouter): successo
    assert records[3].provider == "openrouter"
    assert records[3].status == "success"


def test_subsequent_call_returns_to_normal_round_robin(monkeypatch):
    """
    Verifica che dopo che una catena ha usato il fallback con successo, la chiamata successiva
    riparta dal round-robin normale e non resti ancorata al fallback.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "key-g2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        round_robin=True,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash"),
            RouteConfig(route_id="r_google_2", provider="google", credential="google_2", model="gemini-2.0-flash"),
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct")
        )
    )

    # Catena 1 usa fallback perché sia g1 sia g2 danno 429
    call_log = []
    def mock_post_chain1(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        if "key-openrouter" in auth_hdr:
            call_log.append("openrouter")
            resp = MagicMock()
            resp.status_code = 200
            resp.encoding = "utf-8"
            valid_json = json.dumps({"title": "Chain 1 OK", "summary": "Fallback OK"})
            resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
            return resp
        else:
            call_log.append("google")
            resp = MagicMock()
            resp.status_code = 429
            resp.encoding = "utf-8"
            resp.content = b'{"error": {"message": "429"}}'
            resp.text = '{"error": {"message": "429"}}'
            return resp

    with patch("requests.post", side_effect=mock_post_chain1):
        res1 = client.call_structured(
            prompt="Prompt 1",
            system_prompt="Sys 1",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_chain_1"
        )
    assert res1.title == "Chain 1 OK"
    assert call_log == ["google", "google", "openrouter"]

    # Catena 2: round-robin ora funziona normalmente (Google restituisce 200)
    call_log.clear()
    def mock_post_chain2(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        call_log.append("google" if "key-g" in auth_hdr else "other")
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        valid_json = json.dumps({"title": "Chain 2 OK", "summary": "RR OK"})
        resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
        return resp

    with patch("requests.post", side_effect=mock_post_chain2):
        res2 = client.call_structured(
            prompt="Prompt 2",
            system_prompt="Sys 2",
            response_model=DummyItem,
            job_name="outline",
            unit_id="unit_chain_2"
        )
    assert res2.title == "Chain 2 OK"
    # La catena 2 è partita subito da Google (round-robin), non da openrouter!
    assert call_log == ["google"]


def test_consecutive_fallback_cooldown_activation_and_expiry(monkeypatch):
    """
    Verifica che:
    1. Due fallback consecutivi attivino il cooldown.
    2. La terza catena fallisca immediatamente senza usare il fallback durante il cooldown.
    3. Scaduto il cooldown (mock temporale), il fallback torni disponibile.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=2,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct"),
            cooldown_seconds=30
        )
    )

    current_simulated_time = 1000.0

    def mock_time_monotonic():
        return current_simulated_time

    def mock_post(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        if "key-g1" in auth_hdr:
            resp = MagicMock()
            resp.status_code = 429
            resp.encoding = "utf-8"
            resp.content = b'{"error": {"message": "429"}}'
            resp.text = '{"error": {"message": "429"}}'
            return resp
        else:
            resp = MagicMock()
            resp.status_code = 200
            resp.encoding = "utf-8"
            valid_json = json.dumps({"title": "Fallback OK", "summary": "OpenRouter OK"})
            resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
            return resp

    with patch("time.monotonic", side_effect=mock_time_monotonic), patch("requests.post", side_effect=mock_post):
        # Catena 1: 1° fallback consecutivo -> OK
        res1 = client.call_structured(prompt="P1", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u1")
        assert res1.title == "Fallback OK"
        assert client.router._consecutive_fallbacks["outline"] == 1

        # Catena 2: 2° fallback consecutivo -> OK, ma attiva cooldown fino a 1000 + 30 = 1030
        res2 = client.call_structured(prompt="P2", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u2")
        assert res2.title == "Fallback OK"
        assert client.router._consecutive_fallbacks["outline"] == 2
        assert client.router._cooldown_until["outline"] == 1030.0

        # Catena 3: a t=1010s (durante cooldown), Google da 429, fallback rifiutato -> solleva RateLimitFailure
        current_simulated_time = 1010.0
        with pytest.raises(RateLimitFailure):
            client.call_structured(prompt="P3", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u3")

        # Catena 4: a t=1035s (cooldown scaduto), Google da 429, fallback nuovamente disponibile -> OK!
        current_simulated_time = 1035.0
        res4 = client.call_structured(prompt="P4", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u4")
        assert res4.title == "Fallback OK"
        assert client.router._consecutive_fallbacks["outline"] == 1


def test_consecutive_fallback_counter_resets_on_clean_success(monkeypatch):
    """
    Verifica che una catena risolta con successo senza ricorrere al fallback resetti
    il contatore di fallback consecutivi a 0.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=2,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct"),
            cooldown_seconds=30
        )
    )

    should_google_succeed = False

    def mock_post(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        if "key-g1" in auth_hdr:
            if not should_google_succeed:
                resp = MagicMock()
                resp.status_code = 429
                resp.encoding = "utf-8"
                resp.content = b'{"error": {"message": "429"}}'
                resp.text = '{"error": {"message": "429"}}'
                return resp
            else:
                resp = MagicMock()
                resp.status_code = 200
                resp.encoding = "utf-8"
                valid_json = json.dumps({"title": "Google Clean OK", "summary": "Success"})
                resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
                return resp
        else:
            resp = MagicMock()
            resp.status_code = 200
            resp.encoding = "utf-8"
            valid_json = json.dumps({"title": "Fallback OK", "summary": "OpenRouter"})
            resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
            return resp

    with patch("requests.post", side_effect=mock_post):
        # 1. Fallback 1 -> contatore = 1
        res1 = client.call_structured(prompt="P1", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u1")
        assert res1.title == "Fallback OK"
        assert client.router._consecutive_fallbacks["outline"] == 1

        # 2. Successo pulito su Google -> contatore resettato a 0
        should_google_succeed = True
        res2 = client.call_structured(prompt="P2", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u2")
        assert res2.title == "Google Clean OK"
        assert client.router._consecutive_fallbacks["outline"] == 0

        # 3. Altro fallback -> contatore = 1 (NON 2, quindi nessun cooldown!)
        should_google_succeed = False
        res3 = client.call_structured(prompt="P3", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u3")
        assert res3.title == "Fallback OK"
        assert client.router._consecutive_fallbacks["outline"] == 1


def test_consecutive_fallback_cooldown_is_per_job(monkeypatch):
    """
    Verifica che il cooldown sia per-job: il blocco su 'outline' non impedisce
    il fallback su 'rewrite'.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=2,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct"),
            cooldown_seconds=30
        )
    )
    client.config.jobs["rewrite"] = JobRoutingConfig(
        max_attempts=2,
        primary_routes=[
            RouteConfig(route_id="r_google_1", provider="google", credential="google_1", model="gemini-2.0-flash")
        ],
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct"),
            cooldown_seconds=30
        )
    )

    def mock_post(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        if "key-g1" in auth_hdr:
            resp = MagicMock()
            resp.status_code = 429
            resp.encoding = "utf-8"
            resp.content = b'{"error": {"message": "429"}}'
            resp.text = '{"error": {"message": "429"}}'
            return resp
        else:
            resp = MagicMock()
            resp.status_code = 200
            resp.encoding = "utf-8"
            valid_json = json.dumps({"title": "Fallback OK", "summary": "OpenRouter"})
            resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
            return resp

    with patch("requests.post", side_effect=mock_post):
        # Outline: 2 fallback consecutivi -> cooldown su outline
        client.call_structured(prompt="P1", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u1")
        client.call_structured(prompt="P2", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u2")
        assert client.router._cooldown_until["outline"] > 0

        # Outline fallisce per cooldown
        with pytest.raises(RateLimitFailure):
            client.call_structured(prompt="P3", system_prompt="S", response_model=DummyItem, job_name="outline", unit_id="u3")

        # Rewrite è un job diverso: usa tranquillamente il proprio fallback!
        res_rewrite = client.call_structured(prompt="P4", system_prompt="S", response_model=DummyItem, job_name="rewrite", unit_id="u4")
        assert res_rewrite.title == "Fallback OK"


# ======================================================================
# TASK 70: MAX_ATTEMPTS SCALES WITH ROUND-ROBIN POOL SIZE
# ======================================================================

def test_effective_max_attempts_property():
    """Verifica il calcolo di effective_max_attempts su JobRoutingConfig."""
    # Singolo primario senza round-robin -> effective_max_attempts == max_attempts
    single_cfg = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(route_id="r1", provider="google", credential="google_1", model="gemini-2.0-flash")
    )
    assert single_cfg.effective_max_attempts == 3

    # Pool round-robin di 6 chiavi con max_attempts=3 -> effective_max_attempts == 7 (6 + 1)
    routes_6 = [
        RouteConfig(route_id=f"r{i}", provider="google", credential="google_1", model="gemini-2.0-flash")
        for i in range(6)
    ]
    rr_cfg_6 = JobRoutingConfig(
        max_attempts=3,
        round_robin=True,
        primary_routes=routes_6
    )
    assert rr_cfg_6.effective_max_attempts == 7

    # Pool round-robin di 2 chiavi con max_attempts=5 -> effective_max_attempts == 5 (max(5, 3))
    rr_cfg_2 = JobRoutingConfig(
        max_attempts=5,
        round_robin=True,
        primary_routes=routes_6[:2]
    )
    assert rr_cfg_2.effective_max_attempts == 5


def test_round_robin_6_routes_with_max_attempts_3_reaches_fallback(monkeypatch):
    """
    Test scenario reale Task 70:
    Pool round-robin di 6 chiavi con max_attempts: 3 configurato.
    Un errore sistemico (es. 503 ProviderServerFailure o 429) colpisce TUTTE e 6 le chiavi.
    Il router deve esaurire tutte e 6 le chiavi e poi raggiungere con successo il fallback.generic.
    """
    for i in range(1, 7):
        monkeypatch.setenv(f"GOOGLE_API_KEY_{i}", f"key-google-{i}")
        GLOBAL_CREDENTIALS.register(CredentialRef(name=f"google_{i}", provider="google", env_var=f"GOOGLE_API_KEY_{i}"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    routes_6 = [
        RouteConfig(route_id=f"r_google_{i}", provider="google", credential=f"google_{i}", model="gemini-2.5-flash")
        for i in range(1, 7)
    ]
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        round_robin=True,
        primary_routes=routes_6,
        fallback=JobFallbackConfig(
            generic=RouteConfig(route_id="r_fallback_generic", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct")
        )
    )

    call_log = []

    def mock_post(url, **kwargs):
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "") or headers.get("x-goog-api-key", "")
        if "key-openrouter" in auth_hdr:
            call_log.append("openrouter_generic")
            resp = MagicMock()
            resp.status_code = 200
            resp.encoding = "utf-8"
            valid_json = json.dumps({"title": "Review OK", "summary": "Reached Generic Fallback"})
            resp.iter_lines.return_value = [f'data: {{"choices": [{{"delta": {{"content": {json.dumps(valid_json)}}}, "finish_reason": "stop"}}]}}\n\n'.encode("utf-8")]
            return resp
        else:
            # Trova quale chiave google ha fallito
            for i in range(1, 7):
                if f"key-google-{i}" in auth_hdr:
                    call_log.append(f"google_{i}")
                    break
            resp = MagicMock()
            resp.status_code = 503
            resp.encoding = "utf-8"
            resp.content = b'{"error": {"message": "503 High Demand / Systemic"}}'
            resp.text = '{"error": {"message": "503 High Demand / Systemic"}}'
            return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Prompt review",
            system_prompt="System review",
            response_model=DummyItem,
            job_name="review",
            unit_id="unit_rev_1"
        )

    assert res.title == "Review OK"
    # Tutte e 6 le chiavi devono essere state tentate prima del fallback generico (7 tentativi in totale)
    assert len(call_log) == 7
    assert call_log[-1] == "openrouter_generic"
    for i in range(1, 7):
        assert f"google_{i}" in call_log


def test_override_provider_forces_single_attempt_without_boost(monkeypatch):
    """
    Verifica che con override_provider / override_credential, max_global_attempts
    resti esattamente 1, senza applicare il boost di effective_max_attempts.
    """
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key-g1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    routes_6 = [
        RouteConfig(route_id=f"r_google_{i}", provider="google", credential="google_1", model="gemini-2.0-flash")
        for i in range(1, 7)
    ]
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=3,
        round_robin=True,
        primary_routes=routes_6,
        fallback=JobFallbackConfig(
            rate_limit=RouteConfig(route_id="r_openrouter", provider="openrouter", credential="openrouter", model="meta-llama/llama-3.3-70b-instruct")
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 429
        resp.encoding = "utf-8"
        resp.content = b'{"error": {"message": "429"}}'
        resp.text = '{"error": {"message": "429"}}'
        return resp

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(RateLimitFailure):
            client.call_structured(
                prompt="Prompt override",
                system_prompt="System override",
                response_model=DummyItem,
                job_name="outline",
                unit_id="unit_ov_1",
                override_provider="google"
            )

    # Esattamente 1 solo tentativo con override_provider
    assert call_count == 1





