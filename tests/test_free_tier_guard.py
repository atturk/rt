"""
tests/test_free_tier_guard.py
Test suite per:
1. Feature 1: Modello risolto globale (visibilità provider, telemetry, monitor);
2. Feature 2: Guardia anti-risposta-lazy su free tier (min_elapsed_seconds);
3. Feature 2b: Retry same-route per OutputLimitFailure (senza escalation thinking) e contatori indipendenti;
4. Feature 3: Arresto controllato per qualunque LLMFailure non gestita da CLI main().
"""

import io
import json
import sys
import time
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RouteConfig, JobRoutingConfig
from rt.llm.client import LLMClient, _is_openrouter_free_tier
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.errors import (
    LLMFailure,
    OutputLimitFailure,
    ReasoningRequiredFailure,
    SuspiciousFastResponseFailure,
)
from rt.llm.monitor import LiveTerminalMonitor
from rt.llm.providers import get_provider
from rt.llm.telemetry import GLOBAL_TELEMETRY, LLMTelemetryRecord


class DummyResponseModel(BaseModel):
    summary: str
    items: int


# ==============================================================================
# FEATURE 1: MODELLO RISOLTO GLOBALE
# ==============================================================================

def test_feature1_resolved_model_in_providers():
    """Verifica l'estrazione di resolved_model nei provider adapter."""
    or_p = get_provider("openrouter")
    ds_p = get_provider("deepseek")
    goog_p = get_provider("google")

    # OpenRouter stream line
    chunk_line = 'data: {"id": "chunk_1", "model": "meta-llama/llama-3.3-70b-instruct:free", "choices": [{"delta": {"content": "ok"}}]}'
    chunk = or_p.parse_stream_line(chunk_line)
    assert chunk is not None
    assert chunk.resolved_model == "meta-llama/llama-3.3-70b-instruct:free"

    # OpenRouter normalize_response
    raw_or = {
        "id": "gen_1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "choices": [{"message": {"content": '{"summary": "test", "items": 1}'}}]
    }
    norm_or = or_p.normalize_response(raw_or, model_name="openrouter/free")
    assert norm_or.resolved_model == "meta-llama/llama-3.3-70b-instruct:free"

    # DeepSeek stream line & normalize
    chunk_ds = ds_p.parse_stream_line('data: {"id": "ds_1", "model": "deepseek-chat", "choices": [{"delta": {"content": "a"}}]}')
    assert chunk_ds is not None
    assert chunk_ds.resolved_model == "deepseek-chat"

    norm_ds = ds_p.normalize_response({"id": "ds_1", "model": "deepseek-chat", "choices": [{"message": {"content": "{}"}}]}, model_name="deepseek-chat")
    assert norm_ds.resolved_model == "deepseek-chat"

    # Google stream line & normalize
    chunk_goog = goog_p.parse_stream_line('data: {"id": "g_1", "model": "gemini-2.5-flash", "choices": [{"delta": {"content": "g"}}]}')
    assert chunk_goog is not None
    assert chunk_goog.resolved_model == "gemini-2.5-flash"


def test_feature1_resolved_model_propagated_to_telemetry(monkeypatch):
    """Verifica che resolved_model sia propagato a LLMTelemetryRecord quando differisce dal modello richiesto."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=1,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            timeout_seconds=30
        )
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.encoding = "utf-8"
    ok_json = {
        "id": "gen_or_resolved",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "choices": [{"message": {"content": '{"summary": "Test ASR", "items": 2}'}}]
    }
    mock_resp.json.return_value = ok_json
    mock_resp.iter_lines.return_value = [
        f'data: {json.dumps({"id": "chk_1", "model": "meta-llama/llama-3.3-70b-instruct:free", "choices": [{"delta": {"content": json.dumps({"summary": "Test ASR", "items": 2})}, "finish_reason": "stop"}]})}\n\n'.encode("utf-8")
    ]

    with patch("requests.post", return_value=mock_resp):
        res = client.call_structured(
            prompt="Prompt",
            system_prompt="System",
            response_model=DummyResponseModel,
            job_name="review",
            show_monitor=False,
            unit_id="unit_resolved_check"
        )

    assert res.summary == "Test ASR"
    records = [r for r in GLOBAL_TELEMETRY.get_all() if r.unit_id == "unit_resolved_check"]
    assert len(records) == 1
    assert records[0].model == "openrouter/free"
    assert records[0].resolved_model == "meta-llama/llama-3.3-70b-instruct:free"


def test_feature1_monitor_display_resolved_model(monkeypatch):
    """Verifica che il monitor mostri 'Resolved: ...' solo quando differisce da 'Model: ...'."""
    monitor = LiveTerminalMonitor(
        job="review",
        provider="openrouter",
        model="openrouter/free",
        unit_id="unit_mon_test",
        enabled=True,
        verbose=True
    )
    monitor.set_resolved_model("meta-llama/llama-3.3-70b-instruct:free")
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monitor.render(final=True)
    rendered = buf.getvalue()
    assert "Model:    openrouter/free" in rendered
    assert "Resolved: meta-llama/llama-3.3-70b-instruct:free" in rendered

    # Se invece coincide col modello richiesto, non deve apparire la riga Resolved:
    monitor_same = LiveTerminalMonitor(
        job="rewrite",
        provider="deepseek",
        model="deepseek-chat",
        unit_id="unit_mon_same",
        enabled=True,
        verbose=True
    )
    monitor_same.set_resolved_model("deepseek-chat")
    buf_same = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf_same)
    monitor_same.render(final=True)
    rendered_same = buf_same.getvalue()
    assert "Model:    deepseek-chat" in rendered_same
    assert "Resolved:" not in rendered_same


# ==============================================================================
# FEATURE 2: GUARDIA ANTI-RISPOSTA-LAZY SU FREE TIER
# ==============================================================================

def test_is_openrouter_free_tier_helper():
    assert _is_openrouter_free_tier("openrouter", "openrouter/free") is True
    assert _is_openrouter_free_tier("OpenRouter", "openrouter/free") is True
    assert _is_openrouter_free_tier("openrouter", "meta-llama/llama-3.3-70b-instruct:free") is True
    assert _is_openrouter_free_tier("openrouter", "google/gemini-2.0-flash-exp:free") is True
    assert _is_openrouter_free_tier("openrouter", "deepseek/deepseek-chat") is False
    assert _is_openrouter_free_tier("deepseek", "deepseek-chat") is False
    assert _is_openrouter_free_tier("google", "gemini-2.5-flash") is False


def test_suspicious_fast_response_discarded_and_retried_on_openrouter_free(monkeypatch):
    """
    Risposta valida ma in 2.0s (< 5.0s) da openrouter/free con min_elapsed_seconds=5.0:
    viene scartata precauzionalmente con same-route retry. Tentativo 2 impiega 6.0s e ha successo.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 0

    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            timeout_seconds=30
        )
    )

    call_count = 0
    simulated_now = 1000.0

    def mock_time():
        return simulated_now

    def mock_post(url, **kwargs):
        nonlocal call_count, simulated_now
        call_count += 1
        simulated_now += 2.0 if call_count == 1 else 6.0
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        content_json = '{"summary": "Analisi completata", "items": 3}'
        resp.json.return_value = {"choices": [{"message": {"content": content_json}}]}
        resp.iter_lines.return_value = [
            f'data: {json.dumps({"choices": [{"delta": {"content": content_json}, "finish_reason": "stop"}]})}\n\n'.encode("utf-8")
        ]
        return resp

    with patch("time.time", side_effect=mock_time):
        with patch("requests.post", side_effect=mock_post):
            res = client.call_structured(
                prompt="Prompt",
                system_prompt="System",
                response_model=DummyResponseModel,
                job_name="review",
                show_monitor=False,
                min_elapsed_seconds=5.0
            )

    assert call_count == 2
    assert res.summary == "Analisi completata"
    assert res.items == 3


def test_suspicious_fast_response_escalates_thinking_after_two_consecutive_failures(monkeypatch):
    """
    2 risposte veloci consecutive (< 5.0s) da openrouter/free:
    il 3° tentativo scala forzatamente a thinking=True.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.retry.max_timeout_retries = 0

    client.config.jobs["review"] = JobRoutingConfig(
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
    simulated_now = 1000.0

    def mock_time():
        return simulated_now

    def mock_post(url, **kwargs):
        nonlocal call_count, simulated_now
        call_count += 1
        simulated_now += 1.5 if call_count in (1, 2) else 7.0
        json_body = kwargs.get("json")
        captured_payloads.append(dict(json_body) if json_body else {})
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        content_json = '{"summary": "Scienza ok", "items": 1}'
        resp.json.return_value = {"choices": [{"message": {"content": content_json}}]}
        resp.iter_lines.return_value = [
            f'data: {json.dumps({"choices": [{"delta": {"content": content_json}, "finish_reason": "stop"}]})}\n\n'.encode("utf-8")
        ]
        return resp

    with patch("time.time", side_effect=mock_time):
        with patch("requests.post", side_effect=mock_post):
            res = client.call_structured(
                prompt="Prompt",
                system_prompt="System",
                response_model=DummyResponseModel,
                job_name="review",
                show_monitor=False,
                min_elapsed_seconds=5.0
            )

    assert call_count == 3
    assert len(captured_payloads) == 3
    # Payload 1 e 2 senza thinking (chiave reasoning omessa su OpenRouter)
    assert "reasoning" not in captured_payloads[0]
    assert "reasoning" not in captured_payloads[1]
    # Payload 3 con thinking forzato a True via escalation locale
    assert captured_payloads[2]["reasoning"] == {"enabled": True, "effort": "low"}
    assert res.summary == "Scienza ok"


def test_fast_response_accepted_for_non_free_tier(monkeypatch):
    """Una risposta veloce in 2s da un modello NON free-tier (deepseek-chat) con min_elapsed_seconds=5.0 viene accettata."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-12345")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        primary=RouteConfig(
            route_id="r_ds",
            provider="deepseek",
            credential="deepseek",
            model="deepseek-chat",
            thinking=False,
            timeout_seconds=30
        )
    )

    call_count = 0
    simulated_now = 1000.0

    def mock_time():
        return simulated_now

    def mock_post(url, **kwargs):
        nonlocal call_count, simulated_now
        call_count += 1
        simulated_now += 1.2
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        content_json = '{"summary": "Non-free ok", "items": 4}'
        resp.json.return_value = {"choices": [{"message": {"content": content_json}}]}
        resp.iter_lines.return_value = [
            f'data: {json.dumps({"choices": [{"delta": {"content": content_json}, "finish_reason": "stop"}]})}\n\n'.encode("utf-8")
        ]
        return resp

    with patch("time.time", side_effect=mock_time):
        with patch("requests.post", side_effect=mock_post):
            res = client.call_structured(
                prompt="Prompt",
                system_prompt="System",
                response_model=DummyResponseModel,
                job_name="review",
                show_monitor=False,
                min_elapsed_seconds=5.0
            )

    assert call_count == 1
    assert res.summary == "Non-free ok"


def test_default_min_elapsed_seconds_is_none(monkeypatch):
    """Verifica che senza min_elapsed_seconds (None), risposte veloci siano accettate normalmente."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["outline"] = JobRoutingConfig(
        max_attempts=1,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            timeout_seconds=30
        )
    )

    call_count = 0
    simulated_now = 1000.0

    def mock_time():
        return simulated_now

    def mock_post(url, **kwargs):
        nonlocal call_count, simulated_now
        call_count += 1
        simulated_now += 0.5
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        content_json = '{"summary": "Outline ok", "items": 9}'
        resp.json.return_value = {"choices": [{"message": {"content": content_json}}]}
        resp.iter_lines.return_value = [
            f'data: {json.dumps({"choices": [{"delta": {"content": content_json}, "finish_reason": "stop"}]})}\n\n'.encode("utf-8")
        ]
        return resp

    with patch("time.time", side_effect=mock_time):
        with patch("requests.post", side_effect=mock_post):
            res = client.call_structured(
                prompt="Prompt",
                system_prompt="System",
                response_model=DummyResponseModel,
                job_name="outline",
                show_monitor=False
            )

    assert call_count == 1
    assert res.summary == "Outline ok"


# ==============================================================================
# FEATURE 2b: RETRY SAME-ROUTE PER OUTPUTLIMITFAILURE (SENZA ESCALATION)
# ==============================================================================

def test_feature2b_output_limit_same_route_retry_recovers(monkeypatch):
    """
    2 OutputLimitFailure consecutive seguite da una 3ª risposta valida sotto soglia:
    successo al 3° tentativo, e tutti e 3 i payload IDENTICI (nessuna escalation thinking).
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        max_output_chars=200,
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

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        json_body = kwargs.get("json")
        captured_payloads.append(dict(json_body) if json_body else {})
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"

        if call_count in (1, 2):
            # Runaway stream > 200 caratteri
            chunk_a = json.dumps({"choices": [{"delta": {"content": "A" * 150}}]})
            chunk_b = json.dumps({"choices": [{"delta": {"content": "B" * 150}}]})
            lines = [
                f"data: {chunk_a}\n\n".encode("utf-8"),
                f"data: {chunk_b}\n\n".encode("utf-8")
            ]
            resp.iter_lines.return_value = lines
        else:
            # 3° tentativo: stream pulito e breve
            valid_dict = {"summary": "Science recovered", "items": 7}
            valid_json = json.dumps(valid_dict)
            chunk_ok = json.dumps({"choices": [{"delta": {"content": valid_json}, "finish_reason": "stop"}]})
            lines = [
                f"data: {chunk_ok}\n\n".encode("utf-8")
            ]
            resp.iter_lines.return_value = lines
            resp.json.return_value = {"choices": [{"message": {"content": valid_json}}]}

        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Prompt",
            system_prompt="System",
            response_model=DummyResponseModel,
            job_name="review",
            show_monitor=False
        )

    assert call_count == 3
    assert len(captured_payloads) == 3
    # INVARIANTE: tutti e 3 i payload devono essere rigorosamente identici su thinking/reasoning_effort
    for p in captured_payloads:
        assert "reasoning" not in p
    assert res.summary == "Science recovered"


def test_feature2b_output_limit_exhausts_to_exception(monkeypatch):
    """3 OutputLimitFailure consecutive su job senza fallback -> solleva OutputLimitFailure finale."""
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        max_output_chars=100,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            timeout_seconds=30
        )
    )

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.encoding = "utf-8"
        runaway_chunk = json.dumps({"choices": [{"delta": {"content": "X" * 200}}]})
        resp.iter_lines.return_value = [f"data: {runaway_chunk}\n\n".encode("utf-8")]
        return resp

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(OutputLimitFailure) as exc_info:
            client.call_structured(
                prompt="Prompt",
                system_prompt="System",
                response_model=DummyResponseModel,
                job_name="review",
                show_monitor=False
            )

    assert call_count == 3
    assert "Output explosion guard attivata" in str(exc_info.value)
    assert exc_info.value.failure_class == "output_limit"


def test_feature2b_independent_counters_output_limit_and_reasoning_required(monkeypatch):
    """
    Verifica contatori indipendenti:
    Tentativo 1: OutputLimitFailure
    Tentativo 2: ReasoningRequiredFailure
    Tentativo 3: Successo
    Nessun budget viene esaurito per colpa dell'altro.
    """
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    GLOBAL_CREDENTIALS.reload_from_env()

    client = LLMClient(force_mock=False)
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=3,
        max_output_chars=100,
        primary=RouteConfig(
            route_id="r_or_free",
            provider="openrouter",
            credential="openrouter",
            model="openrouter/free",
            thinking=False,
            timeout_seconds=30
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
            # 1: OutputLimitFailure
            resp.status_code = 200
            runaway_a = json.dumps({"choices": [{"delta": {"content": "A" * 250}}]})
            resp.iter_lines.return_value = [f"data: {runaway_a}\n\n".encode("utf-8")]
        elif call_count == 2:
            # 2: ReasoningRequiredFailure
            resp.status_code = 400
            err_msg = '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400}}'
            resp.content = err_msg.encode("utf-8")
            resp.text = err_msg
        else:
            # 3: Successo
            resp.status_code = 200
            ok_json = {"choices": [{"message": {"content": '{"summary": "Independent ok", "items": 12}'}}]}
            resp.json.return_value = ok_json
            resp.iter_lines.return_value = []

        return resp

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Prompt",
            system_prompt="System",
            response_model=DummyResponseModel,
            job_name="review",
            show_monitor=False
        )

    assert call_count == 3
    assert res.summary == "Independent ok"
    assert res.items == 12


# ==============================================================================
# FEATURE 3: ARRESTO CONTROLLATO PER LLMFAILURE NON GESTITA (CLI MAIN)
# ==============================================================================

def test_feature3_cli_main_controlled_stop_on_llm_failure(monkeypatch):
    """
    Verifica che quando un comando CLI solleva LLMFailure fino a main():
    1. L'uscita è SystemExit(1);
    2. Nessun traceback compare su stdout o stderr;
    3. Il messaggio d'errore formattato è stampato su stderr con i dettagli.
    """
    from rt.cli import main

    monkeypatch.setattr(sys, "argv", ["rt", "review-asr", "/fake/lesson/dir", "--mock"])

    def mock_func(args):
        raise OutputLimitFailure(
            "Output explosion guard attivata: ricevuti 98000 caratteri",
            provider="openrouter",
            model="openrouter/free"
        )

    stderr_capture = io.StringIO()
    stdout_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)
    monkeypatch.setattr(sys, "stdout", stdout_capture)

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_args = MagicMock()
        mock_args.func = mock_func
        mock_parse.return_value = mock_args

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    err_output = stderr_capture.getvalue()
    out_output = stdout_capture.getvalue()

    # Nessun traceback deve essere stampato
    assert "Traceback (most recent call last)" not in err_output
    assert "Traceback (most recent call last)" not in out_output

    # Intestazione e dettagli attesi
    assert "❌ ESECUZIONE INTERROTTA: errore LLM non recuperabile" in err_output
    assert "Output explosion guard attivata" in err_output
    assert "Classe di errore: output_limit" in err_output
    assert "Provider/modello: openrouter / openrouter/free" in err_output
    assert "La pipeline non ha trovato (o non ha configurato) una route alternativa" in err_output


def test_feature3_cli_main_does_not_catch_generic_exceptions(monkeypatch):
    """Verifica che un'eccezione non-LLM (es. bug di programmazione) NON sia mascherata."""
    from rt.cli import main

    monkeypatch.setattr(sys, "argv", ["rt", "run", "/fake/audio.m4a"])

    def mock_bug(args):
        raise KeyError("unhandled_key_error_bug")

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_args = MagicMock()
        mock_args.func = mock_bug
        mock_parse.return_value = mock_args

        with pytest.raises(KeyError) as exc_info:
            main()

        assert "unhandled_key_error_bug" in str(exc_info.value)
