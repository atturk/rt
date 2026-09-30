"""Domande JEV configurabili: validazione, mappatura sulle etichette RT, default e migrazione."""
import hashlib
import itertools
import json

import pytest
from pydantic import ValidationError

from rt.core.config import JevConfig, RTConfig
from rt.core.jev_decision import JevDecisionConfig, validate_for_phase
from rt.llm.jev_client import JevChoiceAnswer, JevNoulAnswer, JevScoreAnswer
from rt.services import jev_mapping as mapping


def _choice_decision(**overrides):
    base = {"question": "Classifica.", "type": "choice",
            "options": [{"label": "a", "description": "A"}, {"label": "b", "description": "B"}],
            "rules": [{"label": "Esclusa", "outcome": "organizational",
                       "conditions": [{"field": "choice", "op": "eq", "value": "b"},
                                      {"field": "confidence", "op": "gte", "value": "0.8"}]}],
            "fallback_label": "Inclusa"}
    base.update(overrides)
    return JevDecisionConfig.model_validate(base)


# ---------------------------------------------------------------- operatori e combinatori

@pytest.mark.parametrize("actual,op,expected,result", [
    (0.5, "eq", 0.5, True), (0.5, "eq", 0.6, False),
    (0.5, "ne", 0.6, True), (0.5, "ne", 0.5, False),
    (0.7, "gt", 0.5, True), (0.5, "gt", 0.5, False),
    (0.5, "gte", 0.5, True), (0.4, "gte", 0.5, False),
    (0.3, "lt", 0.5, True), (0.5, "lt", 0.5, False),
    (0.5, "lte", 0.5, True), (0.6, "lte", 0.5, False),
    (1 - 0.85, "lte", 0.15, True),  # arrotondamenti in virgola mobile
    ("b", "eq", "b", True), ("a", "eq", "b", False),
    ("a", "ne", "b", True), ("b", "ne", "b", False),
    ("b", "gt", "a", False),  # confronto d'ordine su testo: mai vero
    (None, "ne", "b", False), (None, "lt", 0.5, False),  # campo mancante: mai vero
    ("x", "gt", 0.1, False), (float("nan"), "lt", 1.0, False), (True, "eq", 1.0, False),
    ("0.9", "gt", 0.5, True),
])
def test_compare_operators(actual, op, expected, result):
    assert mapping.compare(actual, op, expected) is result


def test_all_and_any_combinators():
    rule_all = _choice_decision().rules[0]
    rule_any = rule_all.model_copy(update={"match": "any"})
    low = {"type": "choice", "choice": "b", "confidence": 0.5}
    high = {"type": "choice", "choice": "b", "confidence": 0.9}
    other = {"type": "choice", "choice": "a", "confidence": 0.1}
    assert not mapping.rule_matches(rule_all, low) and mapping.rule_matches(rule_all, high)
    assert mapping.rule_matches(rule_any, low) and not mapping.rule_matches(rule_any, other)


def test_evaluate_choice_first_rule_wins_and_keeps_all_probabilities():
    decision = _choice_decision(rules=[
        {"label": "Prima", "outcome": "no_content", "conditions": [{"field": "p:b", "op": "gt", "value": 0.5}]},
        {"label": "Seconda", "outcome": "organizational", "conditions": [{"field": "choice", "op": "eq", "value": "b"}]},
    ])
    answer = JevChoiceAnswer(choice="b", confidence=0.7, probabilities={"a": 0.3, "b": 0.7})
    result = mapping.evaluate("relevance", decision, answer)
    assert (result.label, result.outcome, result.rule) == ("Prima", "no_content", 0)
    assert result.answer["probabilities"] == {"a": 0.3, "b": 0.7}
    assert "a 0.30" in mapping.describe(result) and "b 0.70" in mapping.describe(result)


def test_evaluate_noul_and_score_numeric_rules():
    noul = JevDecisionConfig(question="q", type="noul", fallback_label="Da revisionare", rules=[
        {"label": "Ok", "outcome": "skip_review", "conditions": [{"field": "noul", "op": "lt", "value": 0.2}]}])
    assert mapping.evaluate("prefilter", noul, JevNoulAnswer(noul=0.1)).outcome == "skip_review"
    fallback = mapping.evaluate("prefilter", noul, JevNoulAnswer(noul=0.5))
    assert (fallback.outcome, fallback.label, fallback.rule) == ("needs_review", "Da revisionare", None)
    score = JevDecisionConfig(question="q", type="score", levels=["basso", "alto"], rules=[
        {"label": "Alto", "outcome": "no_content", "match": "any",
         "conditions": [{"field": "score", "op": "gte", "value": 1}, {"field": "confidence", "op": "eq", "value": 0.99}]}])
    answer = JevScoreAnswer(score=1, confidence=0.5, probabilities={"0": 0.2, "1": 0.8}, legend={"0": "basso", "1": "alto"})
    result = mapping.evaluate("relevance", score, answer)
    assert result.outcome == "no_content" and result.answer["probabilities"] == {"0": 0.2, "1": 0.8}
    assert mapping.evaluate("relevance", score, JevScoreAnswer(score=0, confidence=0.99)).rule == 0


def test_answer_of_another_type_falls_back_open():
    result = mapping.evaluate("relevance", _choice_decision(), JevNoulAnswer(noul=1.0))
    assert result.outcome == "didactic" and result.rule is None


# ---------------------------------------------------------------- validazione lato server

@pytest.mark.parametrize("overrides,message", [
    ({"options": [{"label": "a", "description": "A"}]}, "almeno due"),
    ({"options": [{"label": "a", "description": "A"}, {"label": "a", "description": "B"}]}, "distinte"),
    ({"options": [{"label": "con spazio", "description": "A"}, {"label": "b", "description": "B"}]}, "lettere"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": [{"field": "noul", "op": "gt", "value": 1}]}]}, "non esiste"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": [{"field": "choice", "op": "gt", "value": "a"}]}]}, "uguale/diverso"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": [{"field": "choice", "op": "eq", "value": "z"}]}]}, "non è un'opzione"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": [{"field": "confidence", "op": "gt", "value": "alta"}]}]}, "numerico"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": [{"field": "p:z", "op": "gt", "value": 0.5}]}]}, "non esiste"),
    ({"rules": [{"label": "x", "outcome": "no_content", "conditions": []}]}, "at least 1"),
    ({"type": "score", "options": []}, "almeno un livello"),
])
def test_invalid_decisions_are_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _choice_decision(**overrides)


def test_values_are_auto_typed_and_outcomes_checked_per_phase():
    decision = _choice_decision()
    assert decision.rules[0].conditions[1].value == 0.8
    assert decision.rules[0].conditions[0].value == "b"
    validate_for_phase("relevance", decision)
    with pytest.raises(ValueError, match="non valido per questa fase"):
        validate_for_phase("prefilter", decision)


# ---------------------------------------------------------------- default e migrazione

def test_missing_decisions_default_to_the_previous_behavior():
    cfg = JevConfig(relevance_threshold=0.9, relevance_prompt="EXTRA", task_a_skip_confidence_threshold=0.7)
    assert cfg.relevance_decision is None and cfg.prefilter_decision is None
    relevance = mapping.effective_decision("relevance", cfg)
    assert relevance.type == "choice" and relevance.question.endswith("\nEXTRA")
    assert [o.label for o in relevance.options] == ["didactic", "organizational", "no_content"]
    assert {r.conditions[1].value for r in relevance.rules} == {0.9}
    prefilter = mapping.effective_decision("prefilter", cfg)
    assert prefilter.type == "choice" and prefilter.rules[0].conditions[1].value == 0.7
    noul = mapping.effective_decision("prefilter", JevConfig(prefilter_type="noul"))
    assert noul.type == "noul" and noul.rules[0].conditions[0].value == 0.15


@pytest.mark.parametrize("choice,confidence", list(itertools.product(
    ("didactic", "organizational", "no_content"), (0.0, 0.5, 0.84, 0.85, 0.86, 1.0))))
def test_default_relevance_mapping_matches_the_old_threshold_rule(choice, confidence):
    cfg = JevConfig()
    answer = JevChoiceAnswer(choice=choice, confidence=confidence)
    old = choice if confidence >= cfg.relevance_threshold else "didactic"
    assert mapping.evaluate("relevance", mapping.effective_decision("relevance", cfg), answer).outcome == old


def test_invalid_decision_in_yaml_falls_back_to_default():
    cfg = RTConfig.model_validate({"jev": {"relevance_decision": {"question": "q", "type": "noul", "rules": [
        {"label": "x", "outcome": "skip_review", "conditions": [{"field": "noul", "op": "gt", "value": 0.5}]}]}}})
    assert cfg.jev.relevance_decision is None


def test_relevance_cache_hash_is_unchanged_for_the_default_decision():
    from rt.services import unit_relevance
    cfg = JevConfig(relevance_model="typesafe/jev-1.13")
    legacy = hashlib.sha256(json.dumps([cfg.relevance_model, cfg.credential, cfg.base_url, cfg.relevance_prompt,
                                        cfg.relevance_threshold, unit_relevance.INSTRUCTIONS, unit_relevance.CRITERIA],
                                       sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert unit_relevance._config_hash(cfg) == legacy
    custom = cfg.model_copy(update={"relevance_decision": mapping.template("relevance", "noul", cfg)})
    assert unit_relevance._config_hash(custom) != legacy
    edited = custom.relevance_decision.model_copy(update={"question": "Altra domanda"})
    assert unit_relevance._config_hash(cfg.model_copy(update={"relevance_decision": edited})) != unit_relevance._config_hash(custom)
