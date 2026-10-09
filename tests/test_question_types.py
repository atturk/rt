"""Consigli Jev, cache, vincoli del recaller e quote della generazione consigliata."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rt.core.config import RTConfig, JevConfig
from rt.llm.jev_client import JevChoiceAnswer, JevResponse
from rt.pipeline.rewrite import load_draft, save_draft
from rt.services import question_types, section_labels
from rt.services.context import RunContext
from tests.test_recall_special import lesson

ACTIVE = RTConfig(jev=JevConfig(relevance_mode="shadow", relevance_model="typesafe/jev-1.13"))


def answer(kind="mirata"):
    return JevResponse(model="typesafe/jev-1.13", answers={"tipo_consigliato": JevChoiceAnswer(
        choice=kind, confidence=.9, probabilities={"quiz": .1, "mirata": .2, "caso": .6, "esercizio": .1})})


@pytest.fixture
def path(tmp_path, monkeypatch):
    monkeypatch.setattr(question_types, "load_config", lambda: ACTIVE)
    monkeypatch.setattr(section_labels, "load_config", lambda: ACTIVE)
    path = lesson(tmp_path)
    section_labels.refresh(path, force_mock=True)
    monkeypatch.setattr(section_labels, "refresh", lambda *args, **kwargs: {})
    return path


def test_choice_instructions_endpoint_and_cache(path):
    with patch("rt.llm.jev_client.call_jev", return_value=answer()) as call:
        rows = question_types.refresh(path)
        assert call.call_count == 5
        args = call.call_args.kwargs
        assert args["model"] == ACTIVE.jev.relevance_model
        assert args["credential"] == ACTIVE.jev.credential and args["base_url"] == ACTIVE.jev.base_url
        question = args["questions"]["tipo_consigliato"]
        assert question.type == "choice" and question.criteria == question_types.CRITERIA
        assert question.instructions == question_types.INSTRUCTIONS
        assert all({"type", "confidence", "probabilities", "text_hash", "config_hash", "at"} <= set(r) for r in rows.values())
        question_types.refresh(path)
        assert call.call_count == 5
        draft = load_draft(path)
        draft.units[0].content += " Testo nuovo."
        save_draft(draft, path)
        question_types.refresh(path)
        assert call.call_count == 6
        with patch.object(question_types, "load_config", return_value=ACTIVE.model_copy(update={"classifier": ACTIVE.classifier.model_copy(update={"model": "nuovo"})})):
            question_types.refresh(path)
        assert call.call_count == 11


def test_special_type_must_have_positive_section_and_override_is_current(path):
    with patch("rt.llm.jev_client.call_jev", return_value=answer("caso")):
        rows = question_types.refresh(path)
    assert rows["1.2"]["type"] == "caso"
    assert rows["2.1"]["type"] == "mirata"  # più probabile del quiz
    section_labels.set_override(path, "1", "caso", "nessuno")
    assert question_types.suggestions(path)["1.2"] == "mirata"


def test_fail_open_without_suggestion_warns_and_retries(path):
    events = []
    ctx = RunContext(reporter=SimpleNamespace(emit=events.append))
    with patch("rt.llm.jev_client.call_jev", side_effect=RuntimeError("Jev non disponibile")) as call:
        rows = question_types.refresh(path, ctx=ctx)
        assert all(row["type"] is None for row in rows.values())
        assert len(events) == 5 and all("Avviso" in e.message for e in events)
        question_types.refresh(path)
        assert call.call_count == 10


def test_disabled_has_no_suggestions_or_calls(path):
    for cfg in (RTConfig(), RTConfig(jev=JevConfig(relevance_model="jev", relevance_mode="disabled"))):
        with patch.object(question_types, "load_config", return_value=cfg), patch("rt.llm.jev_client.call_jev") as call:
            assert not question_types.enabled()
            assert question_types.refresh(path) == question_types.suggestions(path) == {}
            call.assert_not_called()


def test_mock_is_deterministic_and_obeys_section_labels(path):
    first = question_types.refresh(path, force_mock=True)
    assert first == question_types.refresh(path, force_mock=True)
    assert first["1.2"]["type"] == "caso"
    assert first["2.1"]["type"] == "esercizio"


def test_quotas_are_proportional_and_never_exceed_count():
    groups = {"quiz": ["1", "2", "3"], "mirata": ["4", "5"]}
    assert question_types.allocate(groups, 5) == {"quiz": 3, "mirata": 2}
    assert question_types.allocate(groups, 1) == {"quiz": 1}
    assert question_types.allocate(groups, 0) == {}


def test_recommended_job_groups_units_and_reports_generated_types(path):
    from rt.services.job_handlers import recall_generate_job
    units = load_draft(path).units[:2]
    events, calls = [], []
    records = {units[0].unit_id: {"type": "mirata"}, units[1].unit_id: {"type": "quiz"}}
    def generate(_path, qtype, count, examples, **kwargs):
        calls.append((qtype.value, count, kwargs["unit_ids"]))
        return [None] * count
    ctx = RunContext(reporter=SimpleNamespace(emit=events.append))
    job = SimpleNamespace(lesson_path=path, payload={"qtypes": ["consigliato"], "count": 5,
                          "unit_ids": [u.unit_id for u in units], "regenerate": True, "force_mock": True})
    with patch.object(question_types, "refresh", return_value=records), patch("rt.pipeline.recall.generate_recall_batch", side_effect=generate):
        result = recall_generate_job(job, ctx)
    assert result.state.value == "succeeded"
    assert calls == [("mirata", 3, [units[0].unit_id]), ("quiz", 2, [units[1].unit_id])]
    assert any("3 mirate, 2 quiz" in e.message for e in events if e.type == "notice")


def test_unit_without_advice_uses_quiz(path):
    from rt.services.recall_service import generate_pool
    with patch.object(question_types, "refresh", return_value={}), patch("rt.pipeline.recall.generate_recall_batch", return_value=[None]) as call:
        assert generate_pool(path, qtypes=["consigliato"], unit_ids=["1.1"], count=1) == {"quiz": 1}
    assert call.call_args.args[1].value == "quiz"


def test_special_generation_only_uses_requested_unit(path):
    from rt.core.models import RecallQuestionType
    from rt.pipeline.recall_special import generate_special_batch
    questions = generate_special_batch(path, RecallQuestionType.CASO, 2, force_mock=True, regenerate=True, unit_ids=["1.2"])
    assert questions and all(q.unit_ids == ["1.2"] for q in questions)
