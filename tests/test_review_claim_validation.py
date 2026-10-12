"""V4: schema obbligatorio, ancore locali e nessuna riparazione della citazione."""
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from rt.core.models import Draft, DraftUnit, Segment, ScienceType
from rt.llm.prompts import ReviewFinding, ReviewFindingList
from rt.pipeline.review import _validated_review_issues, finding_to_issue, save_science_issues


def _unit():
    return DraftUnit(
        unit_id="1.1", title="Prova", start_segment_id="seg_000001",
        end_segment_id="seg_000001", source_segment_ids=["seg_000001"],
        content="La frase errata è qui. Un'altra frase segue.",
    )


def _finding(quote, tipo="concettuale"):
    return ReviewFinding(tipo=tipo, gravita="media", citazione=quote,
                         motivazione="Motivo", sostituzione="La frase corretta è qui.")


def test_missing_quote_keeps_unanchored_issue_without_repair(tmp_path):
    client = MagicMock()
    client.call_structured.return_value = ReviewFindingList(issues=[_finding("Frase inesistente")])
    issues = _validated_review_issues(client, _unit(), "prompt", str(tmp_path), "unità 1.1")
    assert issues[0].claim == "Frase inesistente"
    assert issues[0].anchor is None
    assert issues[0].segment_id is None
    client.call_structured.assert_called_once()
    assert client.call_structured.call_args.kwargs["response_model"] is ReviewFindingList
    assert not (tmp_path / "science_issues.json").exists()


@pytest.mark.parametrize("tipo", ["concettuale", "asr_llm"])
def test_normalized_quote_gets_exact_local_anchor_and_segment(tipo):
    segment = Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=1,
                      start_formatted="00:00", end_formatted="00:01", text_raw="grezzo")
    issue = finding_to_issue(_finding("La frase  errata è qui.", tipo), _unit(), {segment.id: segment})
    assert issue.anchor.quote == issue.claim == "La frase errata è qui."
    assert issue.segment_id == segment.id
    assert issue.suggested_fix == "La frase corretta è qui."
    assert issue.type == (ScienceType.ERR_CONCETTUALE if tipo == "concettuale" else ScienceType.ERR_ASR_LLM)


@pytest.mark.parametrize("field", ["tipo", "gravita", "citazione", "motivazione", "sostituzione"])
def test_every_finding_field_is_required(field):
    data = _finding("citazione").model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate(data)


def test_schema_forbids_pipeline_fields_and_requires_issue_list():
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate({**_finding("citazione").model_dump(), "id": "sci_000001"})
    with pytest.raises(ValidationError):
        ReviewFindingList.model_validate({})


@pytest.mark.parametrize("tipo", ["concettuale", "asr_llm"])
@pytest.mark.parametrize("validate", [False, True])
def test_unanchored_finding_can_only_be_rejected(tmp_path, tipo, validate):
    from rt.pipeline.rewrite import save_draft
    from rt.services.review_service import ReviewDecisionError, record_review_decision
    unit = _unit()
    save_draft(Draft(units=[unit]), str(tmp_path))
    issue = finding_to_issue(_finding("Frase assente", tipo), unit, {})
    save_science_issues([issue], str(tmp_path))
    for decision in ("accepted", "edited"):
        with pytest.raises(ReviewDecisionError):
            record_review_decision(str(tmp_path), issue.id, decision, "nuovo testo", channel="api", validate=validate)
    result = record_review_decision(str(tmp_path), issue.id, "rejected", channel="api", validate=True)
    assert result.decision == "rejected"


def test_asr_finding_replaces_only_its_quote(tmp_path):
    from rt.pipeline.rewrite import save_draft
    from rt.pipeline.ledger import load_resolved_draft
    from rt.services.review_service import record_review_decision
    unit = _unit()
    save_draft(Draft(units=[unit]), str(tmp_path))
    issue = finding_to_issue(_finding("La frase errata è qui.", "asr_llm"), unit, {})
    save_science_issues([issue], str(tmp_path))
    record_review_decision(str(tmp_path), issue.id, "accepted", channel="api", validate=True)
    assert load_resolved_draft(str(tmp_path)).units[0].content == "La frase corretta è qui. Un'altra frase segue."
