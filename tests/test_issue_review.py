import os
import json
import sys
import pytest
from unittest.mock import patch, MagicMock
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    ReviewDecision, DecisionLedger, SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.state import WorkflowState

from rt.pipeline.ledger import (
    get_pending_issues, record_decision, revert_last_decision, save_ledger, load_ledger,
    find_science_issue_by_id,
    resolve_science_accept_text, resolve_science_reject_text
)


def _create_sample_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    # segments.json
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=2,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="Ciao mondo"),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Seconda parte"),
        ]
    )

    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    # draft.json
    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="U1",
                title="Introduzione",
                content="Questo è il testo con una affermazione scientifica.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                key_concepts=[]
            )
        ]
    )

    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    # info.yaml
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\n")


def test_get_pending_issues(tmp_path):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_CONCETTUALE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="reason 1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.ERR_CONCETTUALE, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="reason 2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    pending_asr, pending_sci = get_pending_issues(lesson_dir)
    assert pending_asr == []
    assert [x.id for x in pending_sci] == ["sci_1", "sci_2"]

    # Registra una decisione per sci_1
    record_decision(lesson_dir, "sci_1", "rejected", resolved_text="claim 1")

    pending_asr2, pending_sci2 = get_pending_issues(lesson_dir)
    assert pending_asr2 == []
    assert [x.id for x in pending_sci2] == ["sci_2"]


def test_ledger_append_only_and_revert(tmp_path):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    # Registra prima decisione
    d1 = record_decision(lesson_dir, "iss_1", "accepted", resolved_text="val1")
    ledger1 = load_ledger(lesson_dir)
    assert len(ledger1.decisions) == 1
    assert ledger1.decisions[0].resolved_text == "val1"

    # Registra seconda decisione per la stessa issue -> append-only, len diventa 2
    d2 = record_decision(lesson_dir, "iss_1", "edited", resolved_text="val2")
    ledger2 = load_ledger(lesson_dir)
    assert len(ledger2.decisions) == 2
    assert ledger2.decisions[0].resolved_text == "val1"
    assert ledger2.decisions[1].resolved_text == "val2"

    # Revert: rimuove l'ultima (val2)
    assert revert_last_decision(lesson_dir, "iss_1") is True
    ledger3 = load_ledger(lesson_dir)
    assert len(ledger3.decisions) == 1
    assert ledger3.decisions[0].resolved_text == "val1"

    # Revert ancora: rimuove la prima (val1)
    assert revert_last_decision(lesson_dir, "iss_1") is True
    ledger4 = load_ledger(lesson_dir)
    assert len(ledger4.decisions) == 0

    # Revert su issue inesistente -> False
    assert revert_last_decision(lesson_dir, "iss_1") is False


def test_cmd_run_with_review_does_not_build_when_issues_are_pending(tmp_path, capsys):
    """Con issue ancora da decidere 'rt run' si ferma prima del build e rimanda alla web."""
    import argparse
    from rt.cli import cmd_run

    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    build_called = []

    args = argparse.Namespace(
        input=lesson_dir, force=False, mock=True, with_review=True,
        date=None, materia=None, argomenti=None, dest_dir=None, model=None,
        skip_transcribe=False, auto_accept=False, rename=False,
    )

    with patch("rt.pipeline.prepare.run_prepare", return_value={"skipped": True, "segment_count": 1, "duration_seconds": 1.0}), \
         patch("rt.pipeline.outline.run_outline", return_value={"skipped": True, "validation_report": {"units_count": 1, "coverage_percentage": 100}}), \
         patch("rt.services.pipeline_service.outline_needs_approval", return_value=False), \
         patch("rt.pipeline.rewrite.run_rewrite", return_value={"skipped": True, "total_units": 1, "processed_units": 1}), \
         patch("rt.pipeline.review.run_review", return_value={"skipped": True, "total_science_issues": 1, "concettuale_issues": 1}), \
         patch("rt.services.pipeline_service._pending", return_value=[__import__("types").SimpleNamespace(id="sci_1")]), \
         patch("rt.pipeline.build.run_build", side_effect=lambda *a, **kw: build_called.append(a)):
        cmd_run(args)

    assert build_called == []
    assert "issue da decidere" in capsys.readouterr().out
