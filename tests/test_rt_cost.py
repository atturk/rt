"""
tests/test_rt_cost.py
Test per il Task 71: comando diagnostico 'rt cost <cartella> [--split]'.
"""

import os
import json
import pytest
from rt.cli import main
from rt.pipeline.cost import compute_lesson_cost, render_cost_report


@pytest.fixture
def lesson_with_llm_debug_log(tmp_path):
    lesson_dir = str(tmp_path / "test_lesson")
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)
    log_file = os.path.join(state_dir, "llm_debug.log")

    entries = [
        # Job outline: 2 chiamate, entrambe successo
        {
            "timestamp": "2026-09-13T10:00:00",
            "job": "outline",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_1",
            "attempt": 1,
            "status": "success",
            "estimated_cost": 0.002000
        },
        {
            "timestamp": "2026-09-13T10:05:00",
            "job": "outline",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_2",
            "attempt": 2,
            "status": "success",
            "estimated_cost": 0.002500
        },
        # Job rewrite: unit_1 con 1 fallimento (con costo parziale) + 1 successo
        {
            "timestamp": "2026-09-13T10:10:00",
            "job": "rewrite",
            "unit_id": "unit_1",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_1",
            "attempt": 1,
            "status": "error",
            "failure_class": "ProviderServerFailure",
            "estimated_cost": 0.000500
        },
        {
            "timestamp": "2026-09-13T10:11:00",
            "job": "rewrite",
            "unit_id": "unit_1",
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct",
            "credential_ref": "openrouter",
            "attempt": 2,
            "status": "success",
            "estimated_cost": 0.010000
        },
        # Job rewrite: unit_2 con 1 fallimento senza costo (cost: null) + 1 successo
        {
            "timestamp": "2026-09-13T10:15:00",
            "job": "rewrite",
            "unit_id": "unit_2",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_1",
            "attempt": 1,
            "status": "timeout",
            "failure_class": "TimeoutFailure",
            "estimated_cost": None
        },
        {
            "timestamp": "2026-09-13T10:16:00",
            "job": "rewrite",
            "unit_id": "unit_2",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_2",
            "attempt": 2,
            "status": "success",
            "estimated_cost": 0.008000
        },
        # Job recall_mirata: 1 chiamata successo
        {
            "timestamp": "2026-09-13T11:00:00",
            "job": "recall_mirata",
            "unit_id": "unit_1",
            "provider": "google",
            "model": "gemini-2.5-flash",
            "credential_ref": "google_1",
            "attempt": 1,
            "status": "success",
            "estimated_cost": 0.001200
        }
    ]

    with open(log_file, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return lesson_dir


def test_compute_lesson_cost_overview(lesson_with_llm_debug_log):
    cost_data = compute_lesson_cost(lesson_with_llm_debug_log)
    assert cost_data is not None
    assert cost_data["total_calls"] == 7
    assert cost_data["unknown_cost_calls"] == 1
    assert cost_data["has_unknown_cost"] is True

    # Calcolo atteso:
    # outline: 0.002 + 0.0025 = 0.0045
    # rewrite: 0.0005 (fallita) + 0.010 + 0 (timeout None) + 0.008 = 0.0185
    # recall_mirata: 0.0012
    # Totale: 0.0045 + 0.0185 + 0.0012 = 0.0242
    assert pytest.approx(cost_data["total_estimated_cost_usd"], 1e-6) == 0.0242
    assert pytest.approx(cost_data["by_job"]["outline"]["total_cost"], 1e-6) == 0.0045
    assert cost_data["by_job"]["outline"]["total_calls"] == 2
    assert cost_data["by_job"]["outline"]["unknown_cost_calls"] == 0
    assert cost_data["by_job"]["outline"]["has_unknown_cost"] is False

    assert pytest.approx(cost_data["by_job"]["rewrite"]["total_cost"], 1e-6) == 0.0185
    assert cost_data["by_job"]["rewrite"]["total_calls"] == 4
    assert cost_data["by_job"]["rewrite"]["error_calls"] == 2
    assert cost_data["by_job"]["rewrite"]["success_calls"] == 2
    assert cost_data["by_job"]["rewrite"]["unknown_cost_calls"] == 1
    assert cost_data["by_job"]["rewrite"]["has_unknown_cost"] is True
    assert cost_data["by_job"]["rewrite"]["units"]["unit_2"]["unknown_cost_calls"] == 1
    assert cost_data["by_job"]["rewrite"]["units"]["unit_2"]["has_unknown_cost"] is True
    assert cost_data["by_job"]["rewrite"]["units"]["unit_1"]["unknown_cost_calls"] == 0
    assert cost_data["by_job"]["rewrite"]["units"]["unit_1"]["has_unknown_cost"] is False

    assert pytest.approx(cost_data["by_job"]["recall_mirata"]["total_cost"], 1e-6) == 0.0012
    assert cost_data["by_job"]["recall_mirata"]["unknown_cost_calls"] == 0


def test_render_cost_report_overview(lesson_with_llm_debug_log):
    cost_data = compute_lesson_cost(lesson_with_llm_debug_log)
    report = render_cost_report(cost_data, split=False)

    assert "COSTO CUMULATIVO LLM" in report
    assert "outline" in report
    assert "rewrite" in report
    assert "recall_mirata" in report
    assert "$0.024200 (+1 chiamata a costo sconosciuto)" in report
    assert "$0.018500 (+1 chiamata a costo sconosciuto)" in report
    assert "$0.004500" in report
    assert "TOTALE" in report


def test_render_cost_report_split(lesson_with_llm_debug_log):
    cost_data = compute_lesson_cost(lesson_with_llm_debug_log)
    report = render_cost_report(cost_data, split=True)

    assert "FASE/JOB: rewrite" in report
    assert "$0.018500 (+1 chiamata a costo sconosciuto)" in report
    assert "Unità unit_1" in report
    assert "Unità unit_2 (2 tentativi, $0.008000 (+1 chiamata a costo sconosciuto))" in report
    assert "ProviderServerFailure" in report
    assert "TimeoutFailure" in report
    assert "N/D" in report  # Per il timeout con estimated_cost None
    assert "TOTALE GENERALE" in report
    assert "$0.024200 (+1 chiamata a costo sconosciuto)" in report


def test_cost_clean_calls_no_unknown_annotation(tmp_path):
    lesson_dir = str(tmp_path / "clean_lesson")
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)
    log_file = os.path.join(state_dir, "llm_debug.log")

    entries = [
        {"job": "outline", "status": "success", "estimated_cost": 0.001000},
        {"job": "rewrite", "unit_id": "1.1", "status": "success", "estimated_cost": 0.002000},
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    cost_data = compute_lesson_cost(lesson_dir)
    assert cost_data is not None
    assert cost_data["unknown_cost_calls"] == 0
    assert cost_data["has_unknown_cost"] is False

    report_nosplit = render_cost_report(cost_data, split=False)
    assert "sconosciuto" not in report_nosplit
    assert "(+" not in report_nosplit

    report_split = render_cost_report(cost_data, split=True)
    assert "sconosciuto" not in report_split
    assert "(+" not in report_split


def test_cost_all_unknown_calls(tmp_path):
    lesson_dir = str(tmp_path / "unknown_lesson")
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)
    log_file = os.path.join(state_dir, "llm_debug.log")

    entries = [
        {"job": "recall_eval_mirata", "status": "success", "estimated_cost": None},
        {"job": "recall_eval_mirata", "status": "success", "estimated_cost": None},
        {"job": "recall_eval_mirata", "status": "success", "estimated_cost": None},
        {"job": "recall_eval_mirata", "status": "success", "estimated_cost": None},
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    cost_data = compute_lesson_cost(lesson_dir)
    assert cost_data is not None
    assert cost_data["total_calls"] == 4
    assert cost_data["unknown_cost_calls"] == 4
    assert cost_data["has_unknown_cost"] is True
    assert cost_data["total_estimated_cost_usd"] == 0.0

    report = render_cost_report(cost_data, split=False)
    assert "$0.000000 (+4 chiamate a costo sconosciuto)" in report


def test_cost_missing_file(tmp_path, capsys):
    empty_lesson = str(tmp_path / "empty_lesson")
    os.makedirs(empty_lesson, exist_ok=True)

    cost_data = compute_lesson_cost(empty_lesson)
    assert cost_data is None

    report = render_cost_report(cost_data)
    assert "Nessun dato di costo disponibile" in report
    assert "$0.00" not in report

    main(["cost", empty_lesson])
    out = capsys.readouterr().out
    assert "Nessun dato di costo disponibile" in out
    assert "$0.00" not in out


def test_cost_malformed_lines_tolerance(tmp_path):
    lesson_dir = str(tmp_path / "corrupted_lesson")
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)
    log_file = os.path.join(state_dir, "llm_debug.log")

    with open(log_file, "w", encoding="utf-8") as f:
        f.write('{"job": "outline", "status": "success", "estimated_cost": 0.001000}\n')
        f.write('CORRUPTED LINE NOT JSON {{{{ }}}\n')
        f.write('\n')
        f.write('{"job": "rewrite", "status": "success", "estimated_cost": 0.002000}\n')

    cost_data = compute_lesson_cost(lesson_dir)
    assert cost_data is not None
    assert cost_data["total_calls"] == 2
    assert pytest.approx(cost_data["total_estimated_cost_usd"], 1e-6) == 0.003000


def test_cli_cost_subcommand(lesson_with_llm_debug_log, capsys):
    main(["cost", lesson_with_llm_debug_log])
    out = capsys.readouterr().out
    assert "COSTO CUMULATIVO LLM" in out
    assert "$0.024200" in out


def test_cli_cost_subcommand_split(lesson_with_llm_debug_log, capsys):
    main(["cost", lesson_with_llm_debug_log, "--split"])
    out = capsys.readouterr().out
    assert "FASE/JOB: rewrite" in out
    assert "ProviderServerFailure" in out
    assert "$0.024200" in out


def test_cli_cost_subcommand_json(lesson_with_llm_debug_log, capsys):
    main(["cost", lesson_with_llm_debug_log, "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["total_calls"] == 7
    assert data["unknown_cost_calls"] == 1
    assert data["has_unknown_cost"] is True
    assert pytest.approx(data["total_estimated_cost_usd"], 1e-6) == 0.0242


def test_llm_client_google_pricing_calculation(tmp_path, monkeypatch):
    """Verifica (Bug 2) che una chiamata reale a LLMClient con Google gemini-3.5-flash-lite
    scriva un estimated_cost non-zero e corretto nel debug log."""
    from pydantic import BaseModel
    from unittest.mock import patch, MagicMock
    from rt.llm.client import LLMClient
    from rt.llm.router import RoutingEngine
    from rt.core.config import RTConfig, JobRoutingConfig, RouteConfig
    from rt.llm.pricing import calculate_cost

    class DummyResponse(BaseModel):
        summary: str

    monkeypatch.setenv("GOOGLE_API_KEY_1", "test-key-fake")

    cfg = RTConfig(
        jobs={
            "outline": JobRoutingConfig(
                primary=RouteConfig(
                    provider="google",
                    credential="google_1",
                    model="gemini-3.5-flash-lite",
                    thinking=False,
                    timeout_seconds=30
                )
            )
        }
    )

    lesson_dir = str(tmp_path / "test_lesson_live")
    os.makedirs(lesson_dir, exist_ok=True)

    client = LLMClient(force_mock=False)
    client.config = cfg
    client.router = RoutingEngine(cfg)

    mock_resp_json = {
        "id": "chatcmpl-123",
        "model": "gemini-3.5-flash-lite",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"summary": "Lezione di prova"}),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 4288,
            "completion_tokens": 1287,
            "total_tokens": 5575,
        },
    }

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = mock_resp_json
    mock_post_resp.text = json.dumps(mock_resp_json)

    with patch("requests.post", return_value=mock_post_resp):
        res = client.call_structured(
            job_name="outline",
            system_prompt="Sei un assistente.",
            prompt="Genera summary.",
            response_model=DummyResponse,
            lesson_dir=lesson_dir,
            stream=False,
        )

    assert isinstance(res, DummyResponse)
    assert res.summary == "Lezione di prova"

    # Verifica debug log
    cost_data = compute_lesson_cost(lesson_dir)
    assert cost_data is not None
    assert cost_data["total_calls"] == 1
    assert cost_data["unknown_cost_calls"] == 0
    assert cost_data["has_unknown_cost"] is False

    expected_cost = calculate_cost("google", "gemini-3.5-flash-lite", 4288, 1287)
    assert expected_cost is not None
    assert expected_cost > 0.0
    assert pytest.approx(cost_data["total_estimated_cost_usd"], 1e-6) == expected_cost

