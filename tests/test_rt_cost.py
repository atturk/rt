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

    # Calcolo atteso:
    # outline: 0.002 + 0.0025 = 0.0045
    # rewrite: 0.0005 (fallita) + 0.010 + 0 (timeout None) + 0.008 = 0.0185
    # recall_mirata: 0.0012
    # Totale: 0.0045 + 0.0185 + 0.0012 = 0.0242
    assert pytest.approx(cost_data["total_estimated_cost_usd"], 1e-6) == 0.0242
    assert pytest.approx(cost_data["by_job"]["outline"]["total_cost"], 1e-6) == 0.0045
    assert cost_data["by_job"]["outline"]["total_calls"] == 2

    assert pytest.approx(cost_data["by_job"]["rewrite"]["total_cost"], 1e-6) == 0.0185
    assert cost_data["by_job"]["rewrite"]["total_calls"] == 4
    assert cost_data["by_job"]["rewrite"]["error_calls"] == 2
    assert cost_data["by_job"]["rewrite"]["success_calls"] == 2

    assert pytest.approx(cost_data["by_job"]["recall_mirata"]["total_cost"], 1e-6) == 0.0012


def test_render_cost_report_overview(lesson_with_llm_debug_log):
    cost_data = compute_lesson_cost(lesson_with_llm_debug_log)
    report = render_cost_report(cost_data, split=False)

    assert "COSTO CUMULATIVO LLM" in report
    assert "outline" in report
    assert "rewrite" in report
    assert "recall_mirata" in report
    assert "$0.024200" in report
    assert "TOTALE" in report


def test_render_cost_report_split(lesson_with_llm_debug_log):
    cost_data = compute_lesson_cost(lesson_with_llm_debug_log)
    report = render_cost_report(cost_data, split=True)

    assert "FASE/JOB: rewrite" in report
    assert "Unità unit_1" in report
    assert "Unità unit_2" in report
    assert "ProviderServerFailure" in report
    assert "TimeoutFailure" in report
    assert "N/D" in report  # Per il timeout con estimated_cost None
    assert "TOTALE GENERALE" in report
    assert "$0.024200" in report


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
    assert pytest.approx(data["total_estimated_cost_usd"], 1e-6) == 0.0242
