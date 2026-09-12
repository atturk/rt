"""
tests/test_task42.py
Unit & integration tests for Task 42: rt review --asr-llm flag and LLM refinement of ASR risk candidates.
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch

from rt.core.models import (
    ScienceType,
    ScienceSeverity,
    ScienceIssue,
    Draft,
    DraftUnit,
    ReviewDecision,
    DecisionLedger,
)
from rt.llm.prompts import ScienceIssueList, build_science_review_user_prompt
from rt.pipeline.review import run_review
from rt.pipeline.ledger import apply_decisions_to_draft
from rt.cli import main


def test_build_science_review_user_prompt_with_asr_context():
    prompt_std = build_science_review_user_prompt(unit_id="1.1", rewritten_content="Prosa 1.1")
    assert "SEGMENTO A RISCHIO ASR" not in prompt_std

    prompt_asr = build_science_review_user_prompt(
        unit_id="1.1",
        rewritten_content="Prosa 1.1",
        asr_risk_context="SEGMENTO A RISCHIO ASR RILEVATO STATISTICAMENTE: raw 'test'"
    )
    assert "SEGMENTO A RISCHIO ASR RILEVATO STATISTICAMENTE: raw 'test'" in prompt_asr


from rt.core.timestamp import format_timestamp


def setup_mock_lesson(tmp_path):
    lesson_dir = str(tmp_path)

    # 12 segments: segment 1 (index 0) degraded
    word_timestamps = []
    raw_segments = []
    for i in range(12):
        s_idx = i * 5
        e_idx = (i + 1) * 5
        conf = 0.1 if i == 0 else 0.95
        for _ in range(5):
            word_timestamps.append({"confidence": conf})
        raw_segments.append({
            "text": f"Raw seg {i+1}",
            "wordRange": {"startIndex": s_idx, "endIndexExclusive": e_idx}
        })

    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump({"wordTimestamps": word_timestamps, "transcriptSegments": raw_segments}, f)

    segments_data = {
        "schema_version": "1.0",
        "segments": [
            {
                "id": f"seg_{i+1:06d}",
                "index": i + 1,
                "start_seconds": float(i * 10),
                "end_seconds": float((i + 1) * 10),
                "start_formatted": format_timestamp(float(i * 10)),
                "end_formatted": format_timestamp(float((i + 1) * 10)),
                "text_raw": f"Raw seg {i+1}"
            }
            for i in range(12)
        ]
    }
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(segments_data, f)

    draft_data = {
        "schema_version": "1.0",
        "units": [
            {
                "unit_id": f"1.{i+1}",
                "title": f"Unità {i+1}",
                "start_segment_id": f"seg_{i+1:06d}",
                "end_segment_id": f"seg_{i+1:06d}",
                "source_segment_ids": [f"seg_{i+1:06d}"],
                "content": f"Contenuto unità {i+1}."
            }
            for i in range(12)
        ]
    }
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    with open(os.path.join(lesson_dir, "_state", "info.yaml"), "w", encoding="utf-8") as f:
        f.write("current_state: REWRITE_COMPLETED\n")

    return lesson_dir


def test_run_review_default_vs_asr_llm(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path)

    # 1. Default (asr_llm=False): generates ERR_ASR_ST
    res_default = run_review(lesson_dir, force=True, force_mock=True, asr_llm=False)
    assert res_default["asr_statistical_issues"] == 1
    assert res_default["asr_llm_issues"] == 0

    # 2. asr_llm=True: prompt for unit 1.1 should have asr context
    prompts_received = []

    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        prompts_received.append((unit_id, prompt))
        # For unit 1.1, return an ERR_ASR_LLM issue
        if "(1.1:" in unit_id:
            iss = ScienceIssue(
                id="sci_temp",
                type=ScienceType.ERR_ASR_LLM,
                severity=ScienceSeverity.HIGH,
                unit_id="1.1",
                claim="Raw seg 1",
                reason="Confermato fabbricato dall'LLM",
                status="pending"
            )
            return ScienceIssueList(issues=[iss])
        return ScienceIssueList(issues=[])

    with patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        res_llm = run_review(lesson_dir, force=True, force_mock=False, asr_llm=True)

    assert res_llm["asr_statistical_issues"] == 0
    assert res_llm["asr_llm_issues"] == 1

    # Check prompt contents: unit 1.1 prompt received ASR risk context, unit 1.2 prompt did not
    u1_prompts = [p for uid, p in prompts_received if "(1.1:" in uid]
    u2_prompts = [p for uid, p in prompts_received if "(1.2:" in uid]
    assert len(u1_prompts) == 1
    assert "SEGMENTO A RISCHIO ASR RILEVATO STATISTICAMENTE IN QUESTA UNITÀ" in u1_prompts[0]
    assert len(u2_prompts) == 1
    assert "SEGMENTO A RISCHIO ASR" not in u2_prompts[0]


def test_run_review_asr_llm_discarded_candidate(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path)

    # Mock LLM returns NO issues for unit 1.1 (candidate is discarded by LLM)
    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        return ScienceIssueList(issues=[])

    with patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        res = run_review(lesson_dir, force=True, force_mock=False, asr_llm=True)

    # Neither ERR_ASR_ST nor ERR_ASR_LLM should be generated
    assert res["asr_statistical_issues"] == 0
    assert res["asr_llm_issues"] == 0
    assert res["total_science_issues"] == 0


def test_apply_decisions_to_draft_err_asr_llm():
    draft = Draft(
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Titolo Unità",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                content="Questo è il testo riscritto originale dell'unità.",
            )
        ]
    )

    issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_ASR_LLM,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        segment_id="seg_000001",
        claim="raw text non presente nel draft",
        reason="ASR LLM confirmed",
        status="pending",
    )

    # 1. Test "accepted" decision (no-op)
    ledger_accepted = DecisionLedger(
        decisions=[
            ReviewDecision(
                issue_id="sci_000001",
                decision="accepted",
                resolved_text="Questo è il testo riscritto originale dell'unità.",
            )
        ]
    )
    draft_res_accepted = apply_decisions_to_draft(draft, ledger_accepted, [issue])
    assert draft_res_accepted.units[0].content == "Questo è il testo riscritto originale dell'unità."

    # 2. Test "edited" decision (replaces entire unit content)
    new_content = "Testo interamente sostituito dopo revisione ASR LLM."
    ledger_edited = DecisionLedger(
        decisions=[
            ReviewDecision(
                issue_id="sci_000001",
                decision="edited",
                resolved_text=new_content,
            )
        ]
    )
    draft_res_edited = apply_decisions_to_draft(draft, ledger_edited, [issue])
    assert draft_res_edited.units[0].content == new_content


def test_cli_review_asr_llm_flag():
    with patch("rt.cli.run_review") as mock_run_review, patch("rt.cli.run_interactive_review"), patch("sys.argv", ["rt", "review", "/path/to/lesson", "--asr-llm", "--mock"]):
        mock_run_review.return_value = {"status": "ok", "skipped": True}
        try:
            main()
        except SystemExit:
            pass
        mock_run_review.assert_called_once()
        _, kwargs = mock_run_review.call_args
        assert kwargs.get("asr_llm") is True
