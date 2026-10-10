"""Le sostituzioni ASR nuove non cambiano il significato dei registri storici."""
import pytest

from rt.core.models import DecisionLedger, Draft, DraftUnit, ReviewDecision, ScienceIssue
from rt.pipeline.ledger import apply_decisions_to_draft
from rt.pipeline.review_migration import legacy_apply_decisions


@pytest.mark.parametrize("decision", ["accepted", "edited"])
def test_legacy_asr_with_proposal_preserves_resolved_text(decision):
    raw = "Il valore è errato. Nota originale."
    draft = Draft(units=[DraftUnit(unit_id="1.1", title="Valore", content=raw,
        start_segment_id="seg_1", end_segment_id="seg_1", source_segment_ids=["seg_1"])])
    issues = [ScienceIssue(id="sci_000001", unit_id="1.1", type="ERR_CONCETTUALE",
        severity="high", claim="errato", reason="Valore", suggested_fix="corretto"),
        ScienceIssue(id="sci_000002", unit_id="1.1", type="ERR_ASR_LLM", severity="low",
        claim="Nota originale", reason="Rischio ASR", suggested_fix="proposta storica")]
    ledger = DecisionLedger(decisions=[
        ReviewDecision(issue_id="sci_000001", decision="accepted", resolved_text="corretto", timestamp="2026-10-09T10:00:00"),
        ReviewDecision(issue_id="sci_000002", decision=decision,
            resolved_text=raw if decision == "accepted" else "Il valore è errato. Nota modificata.", timestamp="2026-10-09T10:01:00"),
    ])
    expected = legacy_apply_decisions(draft, ledger, issues)
    assert [u.content for u in apply_decisions_to_draft(draft, ledger, issues).units] == [u.content for u in expected.units]
