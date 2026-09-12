"""
tests/test_task41.py
Unit & integration tests for Task 41: Deterministic statistical ASR risk detection.
"""

import os
import json
import pytest
from typing import List
from rt.core.models import (
    ScienceType,
    ScienceSeverity,
    ScienceIssue,
    Draft,
    DraftUnit,
    ReviewDecision,
    DecisionLedger,
)
from rt.core.asr_risk import (
    _calculate_p10,
    _calculate_median,
    _calculate_mad,
    detect_statistical_asr_risks,
)
from rt.pipeline.ledger import apply_decisions_to_draft
from rt.pipeline.issue_review import _build_science_panel


def test_p10_calculation():
    # Less than 3 items: returns min
    assert _calculate_p10([0.8, 0.2]) == 0.2
    assert _calculate_p10([0.9]) == 0.9
    assert _calculate_p10([]) == 0.0

    # 10 sorted items: 0.1, 0.2, 0.3, ..., 1.0
    vals = [0.1 * i for i in range(1, 11)]
    # p10 should be low value near 0.1
    p10 = _calculate_p10(vals)
    assert 0.1 <= p10 <= 0.2


def test_median_and_mad():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    med = _calculate_median(vals)
    assert med == 3.0
    mad = _calculate_mad(vals, med)
    # dev: [2, 1, 0, 1, 2], sorted: [0, 1, 1, 2, 2], median: 1.0
    assert mad == 1.0


def test_detect_statistical_asr_risks_outlier(tmp_path):
    lesson_dir = str(tmp_path)

    # Mock raw transcript with 12 segments
    word_timestamps = []
    raw_segments = []

    # 11 high confidence segments, 1 outlier segment
    for i in range(12):
        s_idx = i * 5
        e_idx = (i + 1) * 5
        # Set low confidence for segment 5
        conf = 0.1 if i == 5 else 0.95
        for _ in range(5):
            word_timestamps.append({"confidence": conf})
        raw_segments.append({
            "text": f"Testo segmento {i+1}",
            "wordRange": {"startIndex": s_idx, "endIndexExclusive": e_idx}
        })

    raw_data = {
        "wordTimestamps": word_timestamps,
        "transcriptSegments": raw_segments
    }

    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump(raw_data, f)

    # Mock draft
    draft_data = {
        "schema_version": "1.0",
        "units": [
            {
                "unit_id": f"1.{i+1}",
                "title": f"Unità {i+1}",
                "start_segment_id": f"seg_{i+1:06d}",
                "end_segment_id": f"seg_{i+1:06d}",
                "source_segment_ids": [f"seg_{i+1:06d}"],
                "content": f"Contenuto rielaborato unità {i+1}."
            }
            for i in range(12)
        ]
    }
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    issues = detect_statistical_asr_risks(lesson_dir, k=3.0, floor=0.35)
    assert len(issues) == 1
    assert issues[0].unit_id == "1.6"
    assert issues[0].type == ScienceType.ERR_ASR_ST
    assert issues[0].claim == "Testo segmento 6"


def test_detect_statistical_asr_risks_small_sample(tmp_path):
    lesson_dir = str(tmp_path)

    # Only 5 segments (< 10), relative stat test should be disabled, only floor (0.35) active
    word_timestamps = []
    raw_segments = []

    for i in range(5):
        s_idx = i * 5
        e_idx = (i + 1) * 5
        conf = 0.30 if i == 2 else 0.50  # 0.50 is low but > floor 0.35, 0.30 < floor
        for _ in range(5):
            word_timestamps.append({"confidence": conf})
        raw_segments.append({
            "text": f"Segmento {i+1}",
            "wordRange": {"startIndex": s_idx, "endIndexExclusive": e_idx}
        })

    raw_data = {
        "wordTimestamps": word_timestamps,
        "transcriptSegments": raw_segments
    }
    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump(raw_data, f)

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
            for i in range(5)
        ]
    }
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    issues = detect_statistical_asr_risks(lesson_dir, k=3.0, floor=0.35)
    # Only segment 3 is < 0.35 floor
    assert len(issues) == 1
    assert issues[0].unit_id == "1.3"


def test_unit_grouping_multiple_segments(tmp_path):
    lesson_dir = str(tmp_path)

    # 12 segments, 3 in unit 1.1 are degraded
    word_timestamps = []
    raw_segments = []

    for i in range(12):
        s_idx = i * 5
        e_idx = (i + 1) * 5
        # Segments 0, 1, 2 in unit 1.1 have low conf (0.1, 0.2, 0.15)
        if i in (0, 1, 2):
            conf = 0.1 + i * 0.05
        else:
            conf = 0.95
        for _ in range(5):
            word_timestamps.append({"confidence": conf})
        raw_segments.append({
            "text": f"Seg {i+1}",
            "wordRange": {"startIndex": s_idx, "endIndexExclusive": e_idx}
        })

    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump({"wordTimestamps": word_timestamps, "transcriptSegments": raw_segments}, f)

    draft_data = {
        "schema_version": "1.0",
        "units": [
            {
                "unit_id": "1.1",
                "title": "Unità Multi-segmento",
                "start_segment_id": "seg_000001",
                "end_segment_id": "seg_000003",
                "source_segment_ids": ["seg_000001", "seg_000002", "seg_000003"],
                "content": "Contenuto unità 1."
            }
        ] + [
            {
                "unit_id": f"1.{i+1}",
                "title": f"Unità {i+1}",
                "start_segment_id": f"seg_{i+1:06d}",
                "end_segment_id": f"seg_{i+1:06d}",
                "source_segment_ids": [f"seg_{i+1:06d}"],
                "content": f"Contenuto unità {i+1}."
            }
            for i in range(3, 12)
        ]
    }
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    issues = detect_statistical_asr_risks(lesson_dir, k=3.0, floor=0.35)
    # Unit 1.1 should produce only 1 issue representing the most degraded segment
    assert len(issues) == 1
    assert issues[0].unit_id == "1.1"
    assert issues[0].segment_id == "seg_000001"
    assert "3 segmenti in questa unità risultano degradati" in issues[0].reason


def test_apply_decisions_to_draft_err_asr_st():
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
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        segment_id="seg_000001",
        claim="trascrizione raw completamente diversa",
        reason="ASR degradato",
        status="pending",
    )

    # 1. Test "accepted" decision (must leave content completely untouched)
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

    # 2. Test "edited" decision (must replace ENTIRE unit content with resolved_text)
    new_content = "Questo è il testo NUOVO e corretto dell'intera unità sostituito per intero."
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


def test_tui_science_panel_err_asr_st():
    issue = ScienceIssue(
        id="sci_st_1.1",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        segment_id="seg_000001",
        claim="trascrizione raw sospetta",
        reason="Confidenza ASR degradata",
        status="pending",
    )

    panel = _build_science_panel(
        idx=0,
        total_count=1,
        iss=issue,
        tc="01:30",
        sci_unit_info="1.1 - Titolo",
        sci_unit=DraftUnit(
            unit_id="1.1",
            title="Titolo",
            start_segment_id="seg_000001",
            end_segment_id="seg_000001",
            source_segment_ids=["seg_000001"],
            content="Contenuto intero dell'unità.",
        ),
        decisions_map={},
    )

    panel_text = str(panel.renderable)
    assert "🎙️ RISCHIO ASR (statistico)" in panel_text
    assert "🎙️ Segmento raw sospetto:" in panel_text
    assert "A=Applica correzione" not in panel_text
    assert "M=Accetta" in panel_text
