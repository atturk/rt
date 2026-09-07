"""
tests/test_monitor_ux_and_abort.py
Test per:
- LiveTerminalMonitor in modalità compatta (default) e verbosa (box)
- Tag "⚠lento" al superamento del 50% del timeout
- Interruzione intelligente Ctrl+C (KeyboardInterrupt) durante lo streaming -> failover
- File di log dettagliato llm_debug.log in formato JSON Lines
- Riepilogo costi sessione a fine pipeline in cmd_run
"""

import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.llm.monitor import LiveTerminalMonitor
from rt.llm.client import LLMClient
from rt.llm.errors import UserAbortedFailure, LLMFailure
from rt.llm.telemetry import GLOBAL_TELEMETRY, LLMTelemetryRecord
from rt.llm.router import RoutingEngine
from rt.core.config import RTConfig, RouteConfig, JobRoutingConfig


class SimpleItem(BaseModel):
    name: str
    value: int


def test_monitor_compact_rendering_default(capsys):
    """Verifica che con verbose=False (default) il rendering produca una singola riga compatta."""
    monitor = LiveTerminalMonitor(
        job="outline",
        provider="deepseek",
        model="deepseek-v4-flash",
        unit_id="unit_1",
        enabled=True,
        verbose=False,
    )
    monitor.is_tty = False
    monitor.status = "completed"
    monitor.finish(success=True)

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l]
    assert len(lines) == 1
    compact = lines[0]
    assert "✔" in compact
    assert "outline" in compact
    assert "unit_1" in compact
    assert "deepseek/deepseek-v4-flash" in compact
    assert "RT LLM" not in compact
    assert "────────────────────────────────────" not in compact


def test_monitor_verbose_rendering(capsys):
    """Verifica che con verbose=True il rendering produca il box dettagliato multi-riga."""
    monitor = LiveTerminalMonitor(
        job="outline",
        provider="deepseek",
        model="deepseek-v4-flash",
        unit_id="unit_1",
        enabled=True,
        verbose=True,
    )
    monitor.is_tty = False
    monitor.status = "completed"
    monitor.finish(success=True)

    captured = capsys.readouterr()
    assert "RT LLM" in captured.out
    assert "Workflow: [4/4] Completed" in captured.out
    assert "Job:      outline" in captured.out
    assert "────────────────────────────────────" in captured.out


def test_monitor_compact_slow_tag():
    """Verifica che superato il 50% di timeout_seconds compaia il tag '⚠lento' durante lo streaming."""
    output_buffer = []

    monitor = LiveTerminalMonitor(
        job="rewrite",
        provider="deepseek",
        model="deepseek-v4-flash",
        unit_id="unit_2",
        enabled=True,
        verbose=False,
        timeout_seconds=10,
    )
    monitor.is_tty = True
    monitor.step_num = 3
    # Simula 6 secondi trascorsi (> 50% di 10s)
    monitor.start_time = time.time() - 6.0

    with patch("sys.stdout.write", side_effect=output_buffer.append):
        with patch("sys.stdout.flush"):
            monitor.render(final=False)

    rendered_text = "".join(output_buffer)
    assert "⚠lento" in rendered_text


def test_monitor_retry_reason_tag():
    """Verifica che set_retry_reason mostri il tag nella riga compatta."""
    output_buffer = []

    monitor = LiveTerminalMonitor(
        job="review_asr",
        provider="openrouter",
        model="openrouter/free",
        enabled=True,
        verbose=False,
        timeout_seconds=60,
    )
    monitor.is_tty = True
    monitor.step_num = 3
    monitor.set_retry_reason("reasoning_required")

    with patch("sys.stdout.write", side_effect=output_buffer.append):
        with patch("sys.stdout.flush"):
            monitor.render(final=False)

    rendered_text = "".join(output_buffer)
    assert "retry:reasoning_required" in rendered_text


def test_keyboard_interrupt_during_stream_triggers_failover(monkeypatch):
    """
    Verifica che una KeyboardInterrupt sollevata durante lo streaming attivi
    il failover cross-route (se configurato) invece di uccidere il processo.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")

    cfg = RTConfig(
        mock_llm=False,
        streaming=True,
        show_monitor=False,
        jobs={
            "general": JobRoutingConfig(
                primary=RouteConfig(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    timeout_seconds=60
                ),
                fallback={
                    "generic": RouteConfig(
                        provider="openrouter",
                        model="openrouter/free",
                        timeout_seconds=60
                    )
                }
            )
        }
    )

    client = LLMClient(force_mock=False)
    client.config = cfg
    client.router = RoutingEngine(cfg)

    def fake_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.encoding = "utf-8"

        # Se deepseek (primary), solleva KeyboardInterrupt durante iter_lines
        if "deepseek" in url:
            def interrupted_lines(*args, **kwargs):
                yield b'data: {"choices": [{"delta": {"content": "part1"}}]}\n\n'
                raise KeyboardInterrupt()

            mock_resp.iter_lines = interrupted_lines
        else:
            # OpenRouter (fallback), risponde con successo
            payload_json = json.dumps({"name": "test_ok", "value": 42})
            sse_line = f'data: {{"choices": [{{"delta": {{"content": {json.dumps(payload_json)}}}}}]}}\n\n'.encode("utf-8")

            def success_lines(*args, **kwargs):
                yield sse_line
                yield b'data: [DONE]\n\n'

            mock_resp.iter_lines = success_lines

        return mock_resp

    with patch("requests.post", side_effect=fake_post):
        res = client.call_structured(
            prompt="Hello",
            system_prompt="Test",
            response_model=SimpleItem,
            job_name="general"
        )

    assert res.name == "test_ok"
    assert res.value == 42


def test_keyboard_interrupt_without_fallback_raises_user_aborted(monkeypatch):
    """Verifica che senza route di fallback residua, KeyboardInterrupt sollevi UserAbortedFailure."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")

    cfg = RTConfig(
        mock_llm=False,
        streaming=True,
        show_monitor=False,
        jobs={
            "general": JobRoutingConfig(
                primary=RouteConfig(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    timeout_seconds=60
                )
            )
        }
    )

    client = LLMClient(force_mock=False)
    client.config = cfg
    client.router = RoutingEngine(cfg)

    def fake_post(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.encoding = "utf-8"

        def interrupted_lines(*args, **kwargs):
            raise KeyboardInterrupt()

        mock_resp.iter_lines = interrupted_lines
        return mock_resp

    with patch("requests.post", side_effect=fake_post):
        with pytest.raises(UserAbortedFailure) as exc_info:
            client.call_structured(
                prompt="Hello",
                system_prompt="Test",
                response_model=SimpleItem,
                job_name="general"
            )

    assert exc_info.value.failure_class == "user_aborted"


def test_append_debug_log_on_success_and_failure(tmp_path, monkeypatch):
    """
    Verifica che il parametro lesson_dir produca il file llm_debug.log con righe JSON Lines
    strutturate sia per i tentativi riusciti che per quelli falliti.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")

    lesson_dir = str(tmp_path)

    cfg = RTConfig(
        mock_llm=False,
        streaming=True,
        show_monitor=False,
        jobs={
            "general": JobRoutingConfig(
                primary=RouteConfig(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    timeout_seconds=60
                ),
                fallback={
                    "generic": RouteConfig(
                        provider="openrouter",
                        model="openrouter/free",
                        timeout_seconds=60
                    )
                }
            )
        }
    )

    client = LLMClient(force_mock=False)
    client.config = cfg
    client.router = RoutingEngine(cfg)

    call_count = [0]

    def fake_post(*args, **kwargs):
        call_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.encoding = "utf-8"

        if call_count[0] == 1:
            # Primo tentativo (deepseek): fallimento schema
            def bad_lines(*args, **kwargs):
                yield b'data: {"choices": [{"delta": {"content": "not json"}}]}\\n\\n'
                yield b'data: [DONE]\\n\\n'
            mock_resp.iter_lines = bad_lines
        else:
            # Secondo tentativo (openrouter): successo
            payload_str = json.dumps({"name": "success_item", "value": 100})
            sse_line = f'data: {{"choices": [{{"delta": {{"content": {json.dumps(payload_str)}}}}}]}}\n\n'.encode("utf-8")
            def good_lines(*args, **kwargs):
                yield sse_line
                yield b'data: [DONE]\n\n'
            mock_resp.iter_lines = good_lines

        return mock_resp

    with patch("requests.post", side_effect=fake_post):
        client.call_structured(
            prompt="Hello debug",
            system_prompt="Test debug",
            response_model=SimpleItem,
            job_name="general",
            lesson_dir=lesson_dir,
            max_retries=0  # salta repair turn per andare subito a fallback
        )

    log_file = os.path.join(lesson_dir, "llm_debug.log")
    assert os.path.isfile(log_file)

    with open(log_file, "r", encoding="utf-8") as f:
        log_lines = [json.loads(line) for line in f if line.strip()]

    assert len(log_lines) >= 2

    # Verifica riga fallimento
    err_entry = log_lines[0]
    assert err_entry["status"] in ("error", "schema_error")
    assert err_entry["job"] == "general"
    assert "timestamp" in err_entry
    assert "execution_id" in err_entry
    assert "provider" in err_entry
    assert "error_message" in err_entry

    # Verifica riga successo
    success_entry = log_lines[-1]
    assert success_entry["status"] == "success"
    assert success_entry["job"] == "general"
    assert "content_text" in success_entry
    assert "success_item" in success_entry["content_text"]


def test_cmd_run_cost_summary(capsys, monkeypatch, tmp_path):
    """Verifica che il riepilogo costi di sessione venga stampato a fine cmd_run."""
    from rt.cli import cmd_run
    import argparse

    # Registra telemetria fittizia
    GLOBAL_TELEMETRY.clear()
    GLOBAL_TELEMETRY.add(LLMTelemetryRecord(
        request_id="req_1",
        execution_id="exec_1",
        job="outline",
        provider="deepseek",
        model="deepseek-v4-flash",
        attempt=1,
        started_at="2026-09-07T12:00:00",
        ended_at="2026-09-07T12:00:02",
        elapsed_seconds=2.0,
        status="success",
        estimated_cost=0.001234
    ))
    GLOBAL_TELEMETRY.add(LLMTelemetryRecord(
        request_id="req_2",
        execution_id="exec_2",
        job="rewrite",
        provider="google",
        model="gemini-3.5-flash-lite",
        attempt=1,
        started_at="2026-09-07T12:00:05",
        ended_at="2026-09-07T12:00:08",
        elapsed_seconds=3.0,
        status="success",
        estimated_cost=0.000567
    ))

    # Mock delle fasi della pipeline per arrivare direttamente al summary
    lesson_dir = str(tmp_path)
    args = argparse.Namespace(
        input=lesson_dir,
        force=False,
        mock=True,
        rename=False,
        auto_accept=True
    )

    with patch("rt.cli.run_prepare", return_value={"skipped": True, "segment_count": 10, "duration_seconds": 60.0}):
        with patch("rt.cli.run_outline", return_value={"skipped": True, "validation_report": {"units_count": 2, "coverage_percentage": 100}}):
            with patch("rt.cli.run_rewrite", return_value={"skipped": True, "total_units": 2, "processed_units": 2}):
                with patch("rt.cli.run_review_asr", return_value={"skipped": True, "total_issues": 0, "green_auto_applied": 0, "yellow_review_queue": 0, "red_human_required": 0}):
                    with patch("rt.cli.run_review_science", return_value={"skipped": True, "total_science_issues": 0, "docente_issues": 0, "reconstruction_issues": 0, "science_checks": 0}):
                        with patch("rt.cli.load_ledger", return_value=MagicMock(decisions=[])):
                            with patch("rt.cli.load_asr_issues", return_value=[]):
                                with patch("rt.cli.load_science_issues", return_value=[]):
                                    with patch("rt.cli.run_build", return_value={
                                        "skipped": False,
                                        "rielaborato": "rielaborato.md",
                                        "pre_elaborato": "pre_elaborato.md",
                                        "revisioni_asr": "revisioni_asr.md",
                                        "errori_concettuali": "errori_concettuali.md",
                                        "problemi_scientifici": "problemi_scientifici.md"
                                    }):
                                        cmd_run(args)

    captured = capsys.readouterr()
    assert "💰 RIEPILOGO COSTI SESSIONE" in captured.out
    assert "outline" in captured.out
    assert "rewrite" in captured.out
    assert "TOTALE" in captured.out
    assert "$0.001801" in captured.out
