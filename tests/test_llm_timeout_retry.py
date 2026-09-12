"""
tests/test_llm_timeout_retry.py
Test di regressione obbligatori per RT 2.0 Hardening LLM:
- Test A: Timeout wall-clock reale con streaming continuo (misurazione tempo effettivo)
- Test B: Timeout + retry bounded + successo sullo stesso provider
- Test C: Timeout + retry bounded + timeout finale (terminazione e no loop infiniti)
- Test D: Semantica deadline indipendente per ciascuna attempt
- Test E: Timeout disabilitato / configurabile
- Test F: Telemetria strutturata ricca con metriche streaming
- Test G: No secret leakage (API key e Bearer token sempre redatti)
- Test H: Compatibilità con l'idempotenza di pipeline
- Test I: Idle read timeout SSE scatta prima del deadline totale e attiva il retry
- Test J: Verifica diretta del valore di stream_req_timeout passato a requests.post
- Test K: Non-regressione sul ramo non-streaming (timeout pieno su rem_sec)
- Test L: Non-regressione quando rem_sec è minore di idle_read_timeout_seconds
"""

import time
import json
import pytest
import requests
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.llm.client import LLMClient, LLMError, LLMTimeoutError
from rt.llm.telemetry import GLOBAL_TELEMETRY, LLMTelemetryRecord
from rt.core.config import LLMModelConfig, LLMRetryConfig


class MockItem(BaseModel):
    title: str
    count: int


# ======================================================================
# TEST A: TIMEOUT WALL-CLOCK CON STREAMING CONTINUO & MISURAZIONE TEMPO REALE
# ======================================================================

def test_a_wall_clock_timeout_with_continuous_streaming(monkeypatch):
    """
    Test A: Verifica che una risposta in streaming che continua a inviare chunk
    venga interrotta allo scadere della deadline wall-clock e NON continui indefinitamente.
    Misura il tempo effettivo per dimostrare che non si tratta di un semplice read timeout.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-stream-continuous-12345")
    client = LLMClient(force_mock=False)

    # Configura timeout a 1.0s e nessun retry per isolare la singola attempt
    client.config.llm["outline"].timeout_seconds = 1
    client.config.llm["outline"].provider = "deepseek"
    client.config.llm["outline"].max_attempts = 1
    client.config.retry.max_timeout_retries = 0

    # Generatore che produce chunk infiniti ogni 50ms per simulare il bug di OpenRouter 5.2
    def infinite_chunk_generator():
        # Invia chunk continui per un tempo potenziale di 10 secondi
        start_gen = time.monotonic()
        chunk_idx = 0
        while time.monotonic() - start_gen < 10.0:
            time.sleep(0.05)  # 50ms tra i chunk: un read timeout di 1s non scatterebbe mai!
            chunk_idx += 1
            yield f'data: {{"id": "gen_inf", "choices": [{{"delta": {{"content": " word{chunk_idx}"}}}}]}}'.encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.side_effect = lambda decode_unicode=False: infinite_chunk_generator()

    t_start = time.monotonic()

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(LLMTimeoutError) as exc_info:
            client.call_structured(
                prompt="Genera outline",
                system_prompt="Sei un assistente",
                response_model=MockItem,
                job_name="outline",
                show_monitor=False
            )

    elapsed = time.monotonic() - t_start

    # Verifiche fondamentali:
    # 1. Deve sollevare LLMTimeoutError
    assert "Deadline wall-clock superata" in str(exc_info.value)

    # 2. Il test deve terminare attorno a 1.0s (con tolleranza ragionevole per lo scheduler),
    #    e MAI arrivare ai 10s del generatore!
    assert 0.9 <= elapsed <= 2.2, f"Tempo effettivo trascorso anomalo: {elapsed:.2f}s (atteso ~1.0s)"

    # 3. La risposta parziale non deve essere considerata valida
    last_rec = GLOBAL_TELEMETRY.get_last()
    assert last_rec is not None
    assert last_rec.status == "timeout"
    assert last_rec.error_class == "timeout"


# ======================================================================
# TEST B: TIMEOUT + RETRY + SUCCESSO SULLO STESSO PROVIDER
# ======================================================================

def test_b_timeout_retry_success(monkeypatch):
    """
    Test B: Attempt 1 va in timeout, Attempt 2 riesce.
    Assert:
    - 2 attempt registrate;
    - Attempt 1 classificata 'timeout';
    - Attempt 2 classificata 'success';
    - Risultato finale valido;
    - Nessun output parziale persistito dalla prima attempt.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-retry-success-55555")
    client = LLMClient(force_mock=False)
    client.config.llm["rewrite"].timeout_seconds = 1
    client.config.llm["rewrite"].provider = "openrouter"
    client.config.retry.max_timeout_retries = 1
    client.config.retry.timeout_backoff_seconds = 0.1  # Breve per il test

    call_index = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None):
        nonlocal call_index
        call_index += 1

        if call_index == 1:
            # Primo tentativo: simula timeout dopo invio chunk parziali
            def slow_chunks():
                start_gen = time.monotonic()
                while time.monotonic() - start_gen < 5.0:
                    time.sleep(0.05)
                    yield b'data: {"id": "req_1", "choices": [{"delta": {"content": " parziale..."}}]}'

            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.iter_lines.side_effect = lambda decode_unicode=False: slow_chunks()
            return resp1
        else:
            # Secondo tentativo (retry sullo stesso provider): restituisce JSON valido rapidamente
            valid_lines = [
                b'data: {"id": "req_2", "choices": [{"delta": {"content": "{\\"title\\": \\"Titolo Valido\\", \\"count\\": 42}"}, "finish_reason": "stop"}]}',
                b'data: {"id": "req_2", "choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}',
                b'data: [DONE]'
            ]
            resp2 = MagicMock()
            resp2.status_code = 200
            resp2.iter_lines.return_value = valid_lines
            return resp2

    GLOBAL_TELEMETRY.clear()

    with patch("requests.post", side_effect=mock_post):
        result = client.call_structured(
            prompt="Rielabora unità",
            system_prompt="Sistema",
            response_model=MockItem,
            job_name="rewrite",
            show_monitor=False
        )

    # 1. Risultato finale valido
    assert result.title == "Titolo Valido"
    assert result.count == 42
    assert call_index == 2

    # 2. Verifica dei record telemetria
    records = GLOBAL_TELEMETRY.get_all(job="rewrite")
    assert len(records) == 2, f"Attesi 2 record di telemetria, trovati {len(records)}"

    rec1 = records[0]
    assert rec1.attempt == 1
    assert rec1.status == "timeout"
    assert rec1.error_class == "timeout"
    assert rec1.retry_count == 0

    rec2 = records[1]
    assert rec2.attempt == 2
    assert rec2.status == "success"
    assert rec2.error_class == "success"
    assert rec2.retry_count == 1
    assert rec2.total_tokens == 120


# ======================================================================
# TEST C: TIMEOUT + RETRY + TIMEOUT FINALE
# ======================================================================

def test_c_timeout_retry_final_timeout(monkeypatch):
    """
    Test C: Entrambi i tentativi vanno in timeout.
    Assert:
    - Esattamente 2 tentativi;
    - Errore finale LLMTimeoutError;
    - Nessun loop infinito;
    - 2 record di telemetria 'timeout'.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-timeout-fail-77777")
    client = LLMClient(force_mock=False)
    client.config.llm["outline"].timeout_seconds = 1
    client.config.llm["outline"].max_attempts = 1
    client.config.retry.max_timeout_retries = 1
    client.config.retry.timeout_backoff_seconds = 0.05

    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None):
        nonlocal call_count
        call_count += 1

        def hanging_stream():
            start_gen = time.monotonic()
            while time.monotonic() - start_gen < 5.0:
                time.sleep(0.05)
                yield b'data: {"choices": [{"delta": {"content": " loop..."}}]}'

        resp = MagicMock()
        resp.status_code = 200
        resp.iter_lines.side_effect = lambda decode_unicode=False: hanging_stream()
        return resp

    GLOBAL_TELEMETRY.clear()

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(LLMTimeoutError) as exc_info:
            client.call_structured(
                prompt="Genera outline",
                system_prompt="Sistema",
                response_model=MockItem,
                job_name="outline",
                show_monitor=False
            )

    assert "terminata per timeout dopo 2 tentativi" in str(exc_info.value)
    assert call_count == 2

    records = GLOBAL_TELEMETRY.get_all(job="outline")
    assert len(records) == 2
    assert records[0].status == "timeout"
    assert records[1].status == "timeout"
    assert records[0].attempt == 1
    assert records[1].attempt == 2


# ======================================================================
# TEST D: SEMANTICA DELLA DEADLINE INDIPENDENTE PER ATTEMPT
# ======================================================================

def test_d_independent_deadline_per_attempt(monkeypatch):
    """
    Test D: Dimostra che la deadline di Attempt 2 è calcolata a partire dall'inizio
    di Attempt 2 (t_start_2 + timeout_seconds) e non dalla partenza globale di Attempt 1.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-indep-deadline")
    client = LLMClient(force_mock=False)
    client.config.llm["rewrite"].timeout_seconds = 1
    client.config.retry.max_timeout_retries = 1
    client.config.retry.timeout_backoff_seconds = 0.1

    attempt_start_times = []

    def mock_post(url, headers=None, json=None, timeout=None, stream=None):
        attempt_start_times.append(time.monotonic())
        if len(attempt_start_times) == 1:
            # Attempt 1: va in timeout a 1.0s
            def stream_1():
                s = time.monotonic()
                while time.monotonic() - s < 3.0:
                    time.sleep(0.05)
                    yield b'data: {"choices": [{"delta": {"content": " a1"}}]}'
            r1 = MagicMock()
            r1.status_code = 200
            r1.iter_lines.side_effect = lambda decode_unicode=False: stream_1()
            return r1
        else:
            # Attempt 2: impiega 0.8s (che se la deadline fosse globale sarebbe scaduta a 1.0s!)
            # Invece con deadline indipendente ha a disposizione un intero nuovo secondo (1.0s)
            def stream_2():
                time.sleep(0.5)  # 500ms
                yield b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"OK\\", \\"count\\": 1}"}, "finish_reason": "stop"}]}'
                yield b'data: [DONE]'
            r2 = MagicMock()
            r2.status_code = 200
            r2.iter_lines.side_effect = lambda decode_unicode=False: stream_2()
            return r2

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="rewrite",
            show_monitor=False
        )

    assert res.title == "OK"
    assert len(attempt_start_times) == 2
    # Il secondo tentativo è partito dopo la fine del primo + backoff
    assert attempt_start_times[1] > attempt_start_times[0] + 0.9


# ======================================================================
# TEST E: TIMEOUT DISABILITATO / VALORE CONFIGURABILE
# ======================================================================

def test_e_timeout_disabled_or_configurable(monkeypatch):
    """Verifica che con timeout_seconds=0 o None la richiesta proceda normalmente."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-no-timeout")
    client = LLMClient(force_mock=False)
    client.config.llm["outline"].timeout_seconds = 0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"NoTimeout\\", \\"count\\": 99}"}, "finish_reason": "stop"}]}',
        b'data: [DONE]'
    ]

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="outline",
            show_monitor=False
        )

    assert res.title == "NoTimeout"
    assert res.count == 99
    # Verifica che il parametro timeout passato a requests.post sia None
    _, kwargs = mock_post.call_args
    assert kwargs.get("timeout") is None


# ======================================================================
# TEST F: TELEMETRIA STRUTTURATA COMPLETA
# ======================================================================

def test_f_rich_telemetry_metrics(monkeypatch):
    """Verifica che tutti i campi richiesti per l'analisi siano popolati nella telemetria."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-telemetry-full")
    client = LLMClient(force_mock=False)
    client.config.llm["rewrite"].timeout_seconds = 180

    GLOBAL_TELEMETRY.clear()

    lines = [
        b'data: {"id": "gen_rich_01", "choices": [{"delta": {"reasoning_content": "Pensiero..."}}]}',
        b'data: {"id": "gen_rich_01", "choices": [{"delta": {"content": "{\\"title\\": \\"Full\\", \\"count\\": 7}"}, "finish_reason": "stop"}]}',
        b'data: {"id": "gen_rich_01", "choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 15, "total_tokens": 65}}',
        b'data: [DONE]'
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = lines

    with patch("requests.post", return_value=mock_resp):
        res = client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="rewrite",
            unit_id="unit 5.2",
            show_monitor=False
        )

    assert res.title == "Full"
    rec = GLOBAL_TELEMETRY.get_last()
    assert rec is not None
    assert rec.job == "rewrite"
    assert rec.unit_id == "unit 5.2"
    assert rec.attempt == 1
    assert rec.started_at is not None
    assert rec.ended_at is not None
    assert rec.elapsed_seconds >= 0.0
    assert rec.status == "success"
    assert rec.error_class == "success"
    assert rec.http_status == 200
    assert rec.input_tokens == 50
    assert rec.output_tokens == 15
    assert rec.total_tokens == 65
    assert rec.output_chars > 0
    assert rec.time_to_first_token is not None
    assert rec.stream_duration is not None
    assert rec.timeout_seconds_configured == 180


# ======================================================================
# TEST G: NO SECRET LEAKAGE
# ======================================================================

def test_g_no_secret_leakage(monkeypatch):
    """Verifica che API key o header Authorization non compaiano nei record di telemetria o messaggi."""
    test_secret = "sk-ultra-secret-key-do-not-leak-9988776655"
    monkeypatch.setenv("DEEPSEEK_API_KEY", test_secret)
    client = LLMClient(force_mock=False)

    GLOBAL_TELEMETRY.clear()

    # Simula un errore in cui il server restituisce una stringa contenente accidentalmente il secret
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.content = f'Authorization failed for Bearer {test_secret}'.encode("utf-8")
    mock_resp.text = f'Authorization failed for Bearer {test_secret}'

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(LLMError) as exc_info:
            client.call_structured(
                prompt="test",
                system_prompt="test",
                response_model=MockItem,
                job_name="outline",
                max_retries=0,
                max_timeout_retries=0,
                show_monitor=False
            )

    rec = GLOBAL_TELEMETRY.get_last()
    assert rec is not None
    # Verifica che il secret sia stato oscurato
    rec_json = rec.model_dump_json()
    assert test_secret not in rec_json
    assert "[REDACTED]" in rec_json or "[REDACTED_KEY]" in rec_json


# ======================================================================
# TEST H: COMPATIBILITA IDEMPOTENZA
# ======================================================================

def test_h_idempotency_skip_preserves_zero_llm_calls(tmp_path, monkeypatch):
    """
    Test H: Dimostra che il meccanismo di idempotenza esistente
    non viene alterato e su SKIP continua a non generare chiamate LLM.
    """
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.outline import run_outline

    lesson_dir = str(tmp_path / "[2026-09-06] TEST - Idempotenza LLM")
    import os
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-06'
materia: BIOCHIMICA
argomenti: Test Idempotenza
cartella: '[2026-09-06] TEST - Idempotenza LLM'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    transcript_content = """---
data: '2026-09-06'
materia: BIOCHIMICA
---

*00:02*
Introduzione generale ai lipidi e sintesi dei corpi chetonici.

*00:30*
La via metabolica prosegue con l'idrolisi enzimatica.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)

    run_prepare(lesson_dir)

    GLOBAL_TELEMETRY.clear()

    # Run 1 con mock: esegue la chiamata
    res1 = run_outline(lesson_dir, force=False, force_mock=True)
    assert res1["action"] == "RUN"
    assert res1["skipped"] is False
    assert len(GLOBAL_TELEMETRY.get_all(job="outline")) == 1

    # Run 2 senza force: deve fare SKIP immediato a zero chiamate LLM
    res2 = run_outline(lesson_dir, force=False, force_mock=True)
    assert res2["action"] == "SKIP"
    assert res2["skipped"] is True
    # Nessun nuovo record di telemetria aggiunto (ancora esattamente 1)
    assert len(GLOBAL_TELEMETRY.get_all(job="outline")) == 1


# ======================================================================
# TEST I: IDLE READ TIMEOUT SSE E RETRY SULLO STESSO PROVIDER
# ======================================================================

def test_i_idle_read_timeout_triggers_read_timeout_and_retries(monkeypatch):
    """
    Test I: Simula un modello che risponde con un chunk parziale e poi va in stallo silenzioso
    sul socket, sollevando requests.exceptions.ReadTimeout durante iter_lines.
    Verifica che l'errore venga classificato come TimeoutFailure, che attivi il retry
    same-route esistente e che requests.post usi il timeout ridotto (<= 45.0s) anziché 300s.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-idle-timeout-test")
    client = LLMClient(force_mock=False)
    client.config.llm["review"].timeout_seconds = 300
    client.config.llm["review"].provider = "deepseek"
    client.config.retry.max_timeout_retries = 1
    client.config.retry.timeout_backoff_seconds = 0.01

    captured_timeouts = []
    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None, stream=None):
        nonlocal call_count
        call_count += 1
        captured_timeouts.append(timeout)

        if call_count == 1:
            # Primo tentativo: produce chunk parziale non JSON e poi stalla sollevando ReadTimeout
            def idle_disconnect_generator():
                yield b'data: {"choices": [{"delta": {"content": "User Safety: safe"}}]}'
                raise requests.exceptions.ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=45.0)")

            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.iter_lines.side_effect = lambda decode_unicode=False: idle_disconnect_generator()
            return resp1
        else:
            # Secondo tentativo: retry same-route completato con successo
            resp2 = MagicMock()
            resp2.status_code = 200
            resp2.iter_lines.return_value = [
                b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"Recovered\\", \\"count\\": 1}"}, "finish_reason": "stop"}]}',
                b'data: [DONE]'
            ]
            return resp2

    GLOBAL_TELEMETRY.clear()

    with patch("requests.post", side_effect=mock_post):
        res = client.call_structured(
            prompt="Test prompt",
            system_prompt="Test system",
            response_model=MockItem,
            job_name="review",
            show_monitor=False
        )

    assert res.title == "Recovered"
    assert call_count == 2
    assert len(captured_timeouts) == 2
    for t in captured_timeouts:
        assert t is not None
        assert t <= 45.0
        assert t >= 44.0

    records = GLOBAL_TELEMETRY.get_all(job="review")
    assert len(records) == 2
    assert records[0].status == "timeout"
    assert records[0].error_class == "timeout"
    assert records[1].status == "success"


# ======================================================================
# TEST J: VERIFICA DIRETTA DEL VALORE DI stream_req_timeout A requests.post
# ======================================================================

def test_j_direct_stream_req_timeout_value_passed_to_requests(monkeypatch):
    """
    Test J: Con timeout_seconds=300 sul job e streaming attivo:
    - Default (45.0s): timeout passato <= 45.0s e non vicino a 300s;
    - Override via parametro call_structured(idle_read_timeout_seconds=12.0): timeout <= 12.0s;
    - Override via config YAML/oggetto client.config.retry.idle_read_timeout_seconds=25.0: timeout <= 25.0s.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-stream-timeout-val")
    client = LLMClient(force_mock=False)
    client.config.llm["outline"].timeout_seconds = 300
    client.config.llm["outline"].provider = "deepseek"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"OK\\", \\"count\\": 1}"}, "finish_reason": "stop"}]}',
        b'data: [DONE]'
    ]

    # 1. Valore di default (45.0s)
    with patch("requests.post", return_value=mock_resp) as mock_post:
        client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="outline",
            show_monitor=False
        )
        _, kwargs1 = mock_post.call_args
        t1 = kwargs1.get("timeout")
        assert t1 is not None
        assert 44.0 <= t1 <= 45.0, f"Atteso timeout ~45.0s, ottenuto: {t1}"

    # 2. Override esplicito tramite argomento call_structured (12.0s)
    with patch("requests.post", return_value=mock_resp) as mock_post:
        client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="outline",
            idle_read_timeout_seconds=12.0,
            show_monitor=False
        )
        _, kwargs2 = mock_post.call_args
        t2 = kwargs2.get("timeout")
        assert t2 is not None
        assert 11.0 <= t2 <= 12.0, f"Atteso timeout ~12.0s, ottenuto: {t2}"

    # 3. Override da configurazione retry (25.0s)
    client.config.retry.idle_read_timeout_seconds = 25.0
    with patch("requests.post", return_value=mock_resp) as mock_post:
        client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="outline",
            show_monitor=False
        )
        _, kwargs3 = mock_post.call_args
        t3 = kwargs3.get("timeout")
        assert t3 is not None
        assert 24.0 <= t3 <= 25.0, f"Atteso timeout ~25.0s, ottenuto: {t3}"


# ======================================================================
# TEST K: NON-REGRESSIONE RAMO NON-STREAMING (TIMEOUT PIENO SU rem_sec)
# ======================================================================

def test_k_non_streaming_branch_preserves_full_rem_sec_timeout(monkeypatch):
    """
    Test K: Verifica che con stream=False il timeout passato a requests.post NON sia
    ridotto a idle_read_timeout_seconds (45.0s), ma rifletta ancora il pieno budget rem_sec (~300s).
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-non-stream-timeout")
    client = LLMClient(force_mock=False)
    client.config.llm["rewrite"].timeout_seconds = 300
    client.config.llm["rewrite"].provider = "deepseek"
    client.config.retry.idle_read_timeout_seconds = 45.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"choices": [{"message": {"content": "{\\"title\\": \\"NonStream\\", \\"count\\": 99}"}}]}'
    mock_resp.text = '{"choices": [{"message": {"content": "{\\"title\\": \\"NonStream\\", \\"count\\": 99}"}}]}'
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"title": "NonStream", "count": 99}'}}]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="rewrite",
            stream=False,
            show_monitor=False
        )

    assert res.title == "NonStream"
    _, kwargs = mock_post.call_args
    assert "stream" not in kwargs or not kwargs["stream"]
    t = kwargs.get("timeout")
    assert t is not None
    assert t > 290.0, f"Il ramo non-streaming ha ricevuto timeout={t}, atteso > 290.0s (non ridotto a 45s)"


# ======================================================================
# TEST L: NON-REGRESSIONE QUANDO rem_sec E MINORE DI idle_read_timeout
# ======================================================================

def test_l_stream_req_timeout_clamped_to_small_rem_sec_when_near_deadline(monkeypatch):
    """
    Test L: Verifica che quando rem_sec e già inferiore a idle_read_timeout_seconds (es. fine budget
    o job con timeout breve), min(rem_sec, idle_read_timeout) restituisca rem_sec e non 45.0s.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-small-rem-sec")
    client = LLMClient(force_mock=False)
    # Job configurato con timeout_seconds=5 e idle_read_timeout=45.0
    client.config.llm["review"].timeout_seconds = 5
    client.config.llm["review"].provider = "deepseek"
    client.config.retry.idle_read_timeout_seconds = 45.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"NearEnd\\", \\"count\\": 5}"}, "finish_reason": "stop"}]}',
        b'data: [DONE]'
    ]

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.call_structured(
            prompt="test",
            system_prompt="test",
            response_model=MockItem,
            job_name="review",
            show_monitor=False
        )

    assert res.title == "NearEnd"
    _, kwargs = mock_post.call_args
    t = kwargs.get("timeout")
    assert t is not None
    assert 4.0 <= t <= 5.0, f"Atteso timeout compreso tra 4.0s e 5.0s, ottenuto: {t}"


# ======================================================================
# TEST M: KEEP-ALIVE SILENZIOSI ATTIVANO IL TIMEOUT REALE DI INATTIVITÀ
# ======================================================================

def test_m_silent_keepalive_triggers_real_inactivity_timeout(monkeypatch):
    """
    Test M: Verifica che uno stream che riceve un chunk di contenuto iniziale e poi solo
    righe SSE di keep-alive/commento (non 'data:', scartate da parse_stream_line)
    venga interrotto per inattività (TimeoutFailure con messaggio specifico)
    ben prima che la deadline totale del job (300s) venga raggiunta.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-idle-inactivity")
    client = LLMClient(force_mock=False)
    client.config.llm["outline"].timeout_seconds = 300
    client.config.llm["outline"].provider = "openrouter"
    client.config.llm["outline"].max_attempts = 1
    client.config.retry.max_timeout_retries = 0
    client.config.retry.idle_read_timeout_seconds = 45.0

    # Simulazione stream: 1 chunk iniziale, poi keep-alive a intervalli che superano 45s
    # avanziamo il clock simulato
    sim_time = [1000.0]

    def advancing_time():
        t = sim_time[0]
        sim_time[0] += 1.0
        return t

    def keepalive_stream_generator():
        # Riga 1: contenuto reale
        yield b'data: {"choices": [{"delta": {"content": "Inizio..."}}]}'
        # Avanziamo il tempo simulato di 50s durante i keep-alive
        sim_time[0] += 50.0
        yield b': keep-alive'
        yield b': OPENROUTER PROCESSING'
        yield b': ping'

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.side_effect = lambda decode_unicode=False: keepalive_stream_generator()

    with patch("time.monotonic", side_effect=advancing_time):
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(LLMTimeoutError) as exc_info:
                client.call_structured(
                    prompt="Test prompt",
                    system_prompt="Test system",
                    response_model=MockItem,
                    job_name="outline",
                    show_monitor=False
                )

    err_msg = str(exc_info.value)
    assert "Nessun contenuto o reasoning reale ricevuto da oltre 45s" in err_msg
    assert "Streaming interrotto precauzionalmente" in err_msg


# ======================================================================
# TEST N: PROGRESSO REGOLARE (CONTENT + REASONING) NON SCATTA IL TIMEOUT
# ======================================================================

def test_n_regular_content_and_reasoning_does_not_trigger_inactivity_timeout(monkeypatch):
    """
    Test N: Verifica che uno stream che emette sia reasoning delta che content delta
    con keep-alive intermedi (ciascuno sotto la soglia di idle di 45s)
    completi regolarmente con successo senza attivare l'inactivity timeout.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-regular-progress")
    client = LLMClient(force_mock=False)
    client.config.llm["outline"].timeout_seconds = 300
    client.config.llm["outline"].provider = "openrouter"
    client.config.retry.idle_read_timeout_seconds = 45.0

    sim_time = [2000.0]

    def advancing_time():
        t = sim_time[0]
        sim_time[0] += 1.0
        return t

    def active_stream_generator():
        # 1. Reasoning chunk
        yield b'data: {"choices": [{"delta": {"reasoning": "Sto ragionando sulla struttura..."}}]}'
        sim_time[0] += 10.0
        # 2. Keepalive
        yield b': keepalive'
        sim_time[0] += 10.0
        # 3. Altro reasoning chunk (reset timer)
        yield b'data: {"choices": [{"delta": {"reasoning": "Elaborazione completata."}}]}'
        sim_time[0] += 10.0
        # 4. Content chunk (JSON valido)
        yield b'data: {"choices": [{"delta": {"content": "{\\"title\\": \\"Success\\", \\"count\\": 100}"}, "finish_reason": "stop"}]}'
        yield b'data: [DONE]'

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.side_effect = lambda decode_unicode=False: active_stream_generator()

    with patch("time.monotonic", side_effect=advancing_time):
        with patch("requests.post", return_value=mock_resp):
            res = client.call_structured(
                prompt="Test prompt",
                system_prompt="Test system",
                response_model=MockItem,
                job_name="outline",
                show_monitor=False
            )

    assert res.title == "Success"
    assert res.count == 100



