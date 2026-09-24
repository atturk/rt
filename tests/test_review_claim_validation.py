"""La review non deve salvare correzioni concettuali non applicabili al draft."""
from unittest.mock import MagicMock

import pytest

from rt.core.models import DraftUnit, ScienceIssue, ScienceSeverity, ScienceType
from rt.llm.prompts import ScienceIssueList
from rt.pipeline.review import _validated_review_issues


def _unit():
    return DraftUnit(
        unit_id="1.1", title="Prova", start_segment_id="seg_000001",
        end_segment_id="seg_000001", source_segment_ids=["seg_000001"],
        content="La frase errata è qui. Un'altra frase segue.",
    )


def _issue(claim: str, issue_type=ScienceType.ERR_CONCETTUALE):
    return ScienceIssue(
        id="sci_000001", type=issue_type, severity=ScienceSeverity.MEDIUM,
        unit_id="1.1", claim=claim, reason="Motivo", suggested_fix="La frase corretta è qui.",
    )


def test_repairs_only_orphan_claim_and_keeps_review_content(tmp_path):
    client = MagicMock()
    client.call_structured.side_effect = [
        ScienceIssueList(issues=[_issue("La frase sbagliata è qui.")]),
        ScienceIssueList(issues=[_issue("La frase errata è qui.")]),
    ]
    issues = _validated_review_issues(client, _unit(), "prompt", str(tmp_path), "unità 1.1")
    assert issues[0].claim == "La frase errata è qui."
    assert issues[0].suggested_fix == "La frase corretta è qui."
    assert client.call_structured.call_count == 2
    assert "La frase sbagliata è qui." in client.call_structured.call_args.kwargs["prompt"]


def test_exhausted_repair_keeps_orphan_for_audit_but_not_application(tmp_path):
    client = MagicMock()
    client.call_structured.return_value = ScienceIssueList(issues=[_issue("Frase inesistente")])
    issues = _validated_review_issues(client, _unit(), "prompt", str(tmp_path), "unità 1.1")
    assert issues[0].claim == "Frase inesistente"
    assert client.call_structured.call_count == 3
    assert not (tmp_path / "science_issues.json").exists()


def test_asr_warning_does_not_require_raw_claim_in_rewritten_text(tmp_path):
    client = MagicMock()
    client.call_structured.return_value = ScienceIssueList(
        issues=[_issue("Segmento ASR grezzo", ScienceType.ERR_ASR_LLM)]
    )
    issues = _validated_review_issues(client, _unit(), "prompt", str(tmp_path), "unità 1.1")
    assert len(issues) == 1
    assert client.call_structured.call_count == 1
