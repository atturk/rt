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




