"""
tests/test_services_events.py
RT4-A1: eventi tipizzati, RunContext (telemetria per run, annullamento) e CliReporter.
"""
import os

import pytest

from rt.cli_reporter import CliReporter, format_phase_action, format_cost_summary
from rt.llm.telemetry import GLOBAL_TELEMETRY, TelemetryStore, current_telemetry
from rt.pipeline.build import run_build
from rt.pipeline.outline import run_outline
from rt.pipeline.prepare import run_prepare
from rt.pipeline.review import run_review
from rt.pipeline.rewrite import run_rewrite, load_draft
from rt.services.context import RunCancelled, RunContext
from rt.services.events import (
    CallbackReporter, CostUpdated, ListReporter, PhaseCompleted, PhaseFailed,
    PhaseProgress, PhaseStarted,
)
from tests.test_checkpointing import multi_unit_lesson  # noqa: F401  (fixture)
from tests.test_integration import temp_lesson_dir  # noqa: F401  (fixture)


def test_phases_emit_events_and_use_run_telemetry(temp_lesson_dir):
    GLOBAL_TELEMETRY.clear()
    rep = ListReporter()
    ctx = RunContext(lesson_dir=temp_lesson_dir, force_mock=True, reporter=rep)

    run_prepare(temp_lesson_dir, ctx=ctx)
    run_outline(temp_lesson_dir, force_mock=True, ctx=ctx)
    run_rewrite(temp_lesson_dir, force_mock=True, ctx=ctx)
    run_review(temp_lesson_dir, force_mock=True, ctx=ctx)
    run_build(temp_lesson_dir, rename_folder=False, ctx=ctx)

    started = [e.phase for e in rep.of_type(PhaseStarted)]
    completed = [e.phase for e in rep.of_type(PhaseCompleted)]
    assert started == completed == ["prepare", "outline", "rewrite", "review", "build"]
    assert [e.phase for e in rep.of_type(PhaseProgress)] == ["rewrite", "review"]
    assert rep.of_type(PhaseCompleted)[0].result["segment_count"] == 6

    costs = rep.of_type(CostUpdated)
    assert costs and costs[-1].total_requests == 3
    # La telemetria resta nel contesto: il singleton globale non viene toccato.
    assert ctx.telemetry.get_summary()["total_requests"] == 3
    assert GLOBAL_TELEMETRY.get_summary()["total_requests"] == 0
    assert current_telemetry() is GLOBAL_TELEMETRY


def test_phases_without_context_keep_global_telemetry(temp_lesson_dir):
    GLOBAL_TELEMETRY.clear()
    run_prepare(temp_lesson_dir)
    run_outline(temp_lesson_dir, force_mock=True)
    assert GLOBAL_TELEMETRY.get_summary()["total_requests"] == 1


def test_rewrite_cancel_between_units_keeps_checkpoint(multi_unit_lesson):
    ctx = RunContext(lesson_dir=multi_unit_lesson, force_mock=True, telemetry=TelemetryStore())
    rep = ListReporter()

    def on_event(event):
        rep.emit(event)
        # Annulla appena parte la seconda unità: la prima è già nel checkpoint.
        if isinstance(event, PhaseProgress) and event.current == 2:
            ctx.cancel_token.cancel()

    ctx.reporter = CallbackReporter(on_event)
    with pytest.raises(RunCancelled):
        run_rewrite(multi_unit_lesson, force_mock=True, ctx=ctx)

    assert [u.unit_id for u in load_draft(multi_unit_lesson).units] == ["1.1", "1.2"]
    failed = rep.of_type(PhaseFailed)
    assert failed and failed[0].phase == "rewrite" and failed[0].error_class == "RunCancelled"

    # Una nuova run riprende dalle unità mancanti.
    res = run_rewrite(multi_unit_lesson, force_mock=True, ctx=RunContext(force_mock=True))
    assert res["processed_units"] == 1
    assert [u.unit_id for u in load_draft(multi_unit_lesson).units] == ["1.1", "1.2", "1.3"]


def test_rewrite_cancelled_before_start_processes_nothing(multi_unit_lesson):
    ctx = RunContext(force_mock=True)
    ctx.cancel_token.cancel()
    with pytest.raises(RunCancelled):
        run_rewrite(multi_unit_lesson, force_mock=True, ctx=ctx)
    assert ctx.telemetry.get_summary()["total_requests"] == 0


def test_failed_phase_message_is_sanitized(tmp_path, monkeypatch):
    from rt.llm import credentials
    monkeypatch.setattr(credentials.GLOBAL_CREDENTIALS, "sanitize_secrets", lambda t: t.replace("sk-SECRET", "***"))
    rep = ListReporter()
    with pytest.raises(FileNotFoundError):
        run_prepare(str(tmp_path / "manca sk-SECRET"), ctx=RunContext(reporter=rep))
    (failed,) = rep.of_type(PhaseFailed)
    assert "sk-SECRET" not in failed.message and "***" in failed.message


def test_cli_reporter_matches_legacy_run_output():
    lines = []
    rep = CliReporter(steps={"prepare": (3, "Parsing deterministico segmenti")}, total_steps=7, out=lines.append)
    rep.emit(PhaseCompleted(phase="prepare", result={"segment_count": 4, "duration_seconds": 62.0}))
    rep.emit(PhaseCompleted(phase="prepare", result={"action": "SKIP", "skipped": True, "segment_count": 4, "duration_seconds": 62.0}))
    rep.emit(PhaseStarted(phase="prepare"))  # nessun output: l'intestazione esce a fine fase
    assert lines == [
        "\n[3/7] PREPARE (Parsing deterministico segmenti)...\n✔ Segmenti estratti: 4 (62.0s)",
        "\n[3/7] PREPARE (Parsing deterministico segmenti)...\n⏩ [SKIP] Segmenti già validi (4 segmenti, 62.0s)",
    ]


def test_cli_reporter_single_command_format():
    assert format_phase_action("build", {"action": "SKIP", "reason": "ok"}) == "\n[SKIP] build\nReason: ok\n"
    assert format_phase_action("build", {"action": "FORCE", "reason": "r"}).startswith("\n[FORCE] build\nReason: r\n✔")
    assert format_cost_summary({"total_requests": 0}) is None
    text = format_cost_summary({"total_requests": 1, "total_estimated_cost_usd": 0.5,
                                "by_job": {"outline": {"requests": 1, "estimated_cost_usd": 0.5}}})
    assert "💰 RIEPILOGO COSTI SESSIONE" in text and "$0.500000" in text
