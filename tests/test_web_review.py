"""Integrazione della review web con il ledger esistente di RT."""
import json
from pathlib import Path

import pytest

from rt.core.models import ScienceIssue, ScienceSeverity, ScienceType
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review import save_science_issues
from rt.pipeline.review_actions import submit_review_decision, undo_web_decision
from rt.web.data import _word_diff


def _science_issue() -> ScienceIssue:
    return ScienceIssue(
        id="sci_000001", type=ScienceType.ERR_CONCETTUALE, severity=ScienceSeverity.MEDIUM,
        unit_id="1.1", claim="Il testo originale.", reason="Richiede una correzione.",
        suggested_fix="Il testo corretto.",
    )


def test_web_review_saves_once_and_can_reopen_with_audit(tmp_path):
    lesson = str(tmp_path / "lesson")
    Path(lesson).mkdir()
    save_science_issues([_science_issue()], lesson)

    decision = submit_review_decision(lesson, "sci_000001", "accepted")
    assert decision.resolved_text == "Il testo corretto."
    assert decision.resolved_by == "web"
    assert load_ledger(lesson).decisions[-1].decision == "accepted"

    with pytest.raises(ValueError, match="già una decisione"):
        submit_review_decision(lesson, "sci_000001", "rejected")
    assert len(load_ledger(lesson).decisions) == 1

    undo_web_decision(lesson, "sci_000001")
    assert load_ledger(lesson).decisions == []
    events = [json.loads(line) for line in (Path(lesson) / "_state" / "web_review_events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["recorded", "reverted"]
    assert all(event["issue_id"] == "sci_000001" for event in events)


def test_web_review_rejects_invalid_edit_and_preserves_corrupt_ledger(tmp_path):
    lesson = str(tmp_path / "lesson")
    Path(lesson).mkdir()
    save_science_issues([_science_issue()], lesson)

    with pytest.raises(ValueError, match="Scrivi un testo"):
        submit_review_decision(lesson, "sci_000001", "edited", "  ")
    with pytest.raises(ValueError, match="non esiste"):
        submit_review_decision(lesson, "sci_missing", "accepted")

    ledger_path = Path(lesson) / "_state" / "review_decisions.json"
    ledger_path.write_text("{incomplete", encoding="utf-8")
    with pytest.raises(ValueError):
        submit_review_decision(lesson, "sci_000001", "accepted")
    assert ledger_path.read_text(encoding="utf-8") == "{incomplete"


def test_web_review_manual_edit_persists_exact_text(tmp_path):
    lesson = str(tmp_path / "lesson")
    Path(lesson).mkdir()
    save_science_issues([_science_issue()], lesson)

    submit_review_decision(lesson, "sci_000001", "edited", "  Testo scritto da me.  ")
    saved = load_ledger(lesson).decisions[-1]
    assert saved.decision == "edited"
    assert saved.resolved_text == "Testo scritto da me."
    with pytest.raises(ValueError, match="solo una decisione presa nella GUI"):
        undo_web_decision(lesson, "un'altra")


def test_word_diff_escapes_issue_text():
    diff = _word_diff("<script>alert(1)</script> errato", "testo corretto")
    assert "<script>" not in diff
    assert "&lt;script&gt;" in diff
    assert "<del>" in diff and "<ins>" in diff
