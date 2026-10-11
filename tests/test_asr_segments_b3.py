"""Qualità ASR: tutti i tratti e presa d'atto senza sostituzione del testo."""
import json
import pytest

from rt.core.asr_risk import detect_statistical_asr_risks
from rt.core.models import Draft, DraftUnit, ScienceIssue, SegmentsData, Segment
from rt.pipeline.rewrite import save_draft
from rt.pipeline.review import save_science_issues, load_science_issues
from rt.pipeline.ledger import load_resolved_draft
from rt.services.review_service import issue_context, record_review_decision, undo_last_decision


def unit():
    return DraftUnit(unit_id="1.1", title="Unità", start_segment_id="seg_000001",
        end_segment_id="seg_000002", source_segment_ids=["seg_000002", "seg_000001"], content="Testo nell'editor.")


def test_all_degraded_segments_words_times_and_roundtrip(tmp_path):
    raw = {"transcriptSegments": [
        {"startMs": 5000, "endMs": 7000, "text": "nota nota", "wordRange": {"startIndex": 0, "endIndexExclusive": 2}},
        {"startMs": 10000, "endMs": 13000, "text": "frequenza errata", "wordRange": {"startIndex": 2, "endIndexExclusive": 4}},
    ], "wordTimestamps": [
        {"word": "nota", "confidence": .9, "startMs": 5000, "endMs": 6000},
        {"word": "nota", "confidence": .2, "startMs": 6000, "endMs": 7000},
        {"word": "frequenza", "confidence": .1}, {"word": "errata", "confidence": .9},
    ]}
    (tmp_path / "trascritto grezzo.json").write_text(json.dumps(raw))
    save_draft(Draft(units=[unit()]), str(tmp_path))
    issue, = detect_statistical_asr_risks(str(tmp_path))
    first, second = issue.asr_segments
    assert [s.segment_id for s in issue.asr_segments] == ["seg_000001", "seg_000002"]
    assert (first.start_s, first.end_s, first.threshold, first.text_raw) == (5, 7, .35, "nota nota")
    word, = first.uncertain_words
    assert (word.start_char, word.end_char, word.start_s, word.end_s, word.confidence) == (5, 9, 6, 7, .2)
    assert second.uncertain_words[0].end_char == len("frequenza")
    save_science_issues([issue], str(tmp_path))
    assert load_science_issues(str(tmp_path))[0].asr_segments == issue.asr_segments


def test_old_asr_issue_has_only_its_original_segment():
    seg = Segment(id="seg_000001", index=1, start_seconds=5, end_seconds=7,
        start_formatted="00:05", end_formatted="00:07", text_raw="grezzo", confidence=.2)
    issue = ScienceIssue(id="a", type="ERR_ASR_ST", severity="high", segment_id=seg.id,
        unit_id="1.1", claim="grezzo", reason="ASR")
    context = issue_context("unused", issue, segments=SegmentsData(segments=[seg]), draft=Draft(units=[unit()]), loaded=True)
    part, = context["asr_segments"]
    assert (part["start_s"], part["end_s"], part["text_raw"]) == (5, 7, "grezzo")
    assert part["uncertain_words"] == []


@pytest.mark.parametrize("kind", ["ERR_ASR_ST", "ERR_REWRITE_DRIFT"])
def test_checked_is_accepted_without_text_and_undo_preserves_draft(tmp_path, kind):
    save_draft(Draft(units=[unit()]), str(tmp_path))
    issue = ScienceIssue(id="a", type=kind, severity="high", unit_id="1.1", claim="grezzo", reason="Controlla")
    save_science_issues([issue], str(tmp_path))
    result = record_review_decision(str(tmp_path), "a", "accepted", "testo da ignorare", channel="api", validate=True)
    assert result.resolved_text is None
    assert load_resolved_draft(str(tmp_path)).units[0].content == unit().content
    undo_last_decision(str(tmp_path), "a")
    assert load_resolved_draft(str(tmp_path)).units[0].content == unit().content


def test_old_edited_statistical_asr_keeps_replacing_the_unit(tmp_path):
    save_draft(Draft(units=[unit()]), str(tmp_path))
    save_science_issues([ScienceIssue(id="a", type="ERR_ASR_ST", severity="high", unit_id="1.1", claim="grezzo", reason="Controlla")], str(tmp_path))
    record_review_decision(str(tmp_path), "a", "edited", "Vecchia modifica.", channel="web")
    assert load_resolved_draft(str(tmp_path)).units[0].content == "Vecchia modifica."
