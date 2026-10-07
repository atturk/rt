"""Il gate di rilevanza non deve omettere unità in ombra o dopo errori JEV."""
from unittest.mock import patch

from rt.core.config import RTConfig, JevConfig
from rt.llm.jev_client import JevChoiceAnswer, JevResponse
from rt.pipeline.rewrite import load_draft
from rt.services import unit_relevance as gate
from tests.test_jev_prefilter import setup_mock_lesson


def _config(mode="shadow"):
    from rt.services.jev_mapping import template
    cfg = JevConfig(relevance_model="typesafe/jev-1.13", relevance_mode=mode)
    return RTConfig(jev=cfg.model_copy(update={"relevance_decision": template("relevance", "choice", cfg)}))


def test_shadow_active_override_and_stale_text(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=2)
    answer = JevChoiceAnswer(choice="organizational", confidence=0.99,
                             probabilities={"didactic": 0.01, "organizational": 0.99, "no_content": 0.0})
    response = JevResponse(model="typesafe/jev-1.13", answers={"rilevanza": answer}, usage={})
    with patch.object(gate, "load_config", return_value=_config()), patch("rt.llm.jev_client.call_jev", return_value=response) as called:
        gate.refresh(path)
        gate.refresh(path)
        assert called.call_count == 2  # una sola chiamata per unità, poi cache
        unit = load_draft(path).units[0]
        assert gate.included(path, unit)  # ombra: mai filtrare
    with patch.object(gate, "load_config", return_value=_config("active")):
        unit = load_draft(path).units[0]
        assert not gate.included(path, unit)
        gate.set_override(path, unit.unit_id, "didactic", actor="test")
        row = gate.list_units(path)["units"][0]
        assert row["prediction"] == "organizational" and row["effective"] == "didactic"
        assert row["corrected_by"] == "test" and gate.included(path, unit)
        from rt.services.lesson_service import document_sections
        assert document_sections(path)[1]["relevance"] == "organizational"
        assert document_sections(path)[0]["relevance"] is None
        unit.content += " Una definizione disciplinare aggiunta."
        assert gate.included(path, unit)  # testo cambiato: fail-open


def test_error_is_visible_and_fails_open(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    with patch.object(gate, "load_config", return_value=_config("active")), patch("rt.llm.jev_client.call_jev", side_effect=RuntimeError("provider offline")):
        gate.refresh(path)
        row = gate.list_units(path)["units"][0]
        assert row["error"] == "provider offline"
        assert row["effective"] == "didactic"
        assert gate.included(path, load_draft(path).units[0])


def test_disabled_does_not_call_model(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=1)
    with patch.object(gate, "load_config", return_value=_config("disabled")), patch("rt.llm.jev_client.call_jev") as called:
        gate.refresh(path)
        called.assert_not_called()
        assert gate.included(path, load_draft(path).units[0])


class _Events:
    def __init__(self):
        self.messages = []

    def emit(self, event):
        self.messages.append(getattr(event, "message", ""))


def test_custom_noul_decision_stores_full_answer_and_label(tmp_path):
    from rt.core.jev_decision import JevDecisionConfig
    from rt.llm.jev_client import JevNoulAnswer
    path = setup_mock_lesson(tmp_path, num_units=2)
    decision = JevDecisionConfig(question="Priva di nozioni?", type="noul", fallback_label="Didattica", rules=[
        {"label": "Vuota", "outcome": "no_content", "conditions": [{"field": "noul", "op": "gte", "value": 0.7}]}])
    cfg = RTConfig(jev=JevConfig(relevance_model="typesafe/jev-1.13", relevance_mode="active",
                                 relevance_decision=decision))
    answers = iter([JevNoulAnswer(noul=0.9), JevNoulAnswer(noul=0.2)])
    events = _Events()
    with patch.object(gate, "load_config", return_value=cfg), \
            patch("rt.llm.jev_client.call_jev", side_effect=lambda **kw: JevResponse(
                model="m", answers={"rilevanza": next(answers)})) as called:
        gate.refresh(path, ctx=events)
        question = called.call_args.kwargs["questions"]["rilevanza"]
        assert question.type == "noul" and question.instructions == "Priva di nozioni?"
        rows = gate.list_units(path)["units"]
        assert (rows[0]["effective"], rows[0]["label"], rows[0]["answer"]["noul"]) == ("no_content", "Vuota", 0.9)
        assert (rows[1]["effective"], rows[1]["label"]) == ("didactic", "Didattica")
        units = load_draft(path).units
        assert not gate.included(path, units[0]) and gate.included(path, units[1])
    assert any(message.startswith("Classificatore rilevanza 1.1: Vuota") for message in events.messages)
    # Una domanda diversa invalida la cache delle classificazioni.
    edited = decision.model_copy(update={"question": "Altro"})
    cfg_edited = RTConfig(jev=cfg.jev.model_copy(update={"relevance_decision": edited}))
    with patch.object(gate, "load_config", return_value=cfg_edited):
        assert all(row["stale"] for row in gate.list_units(path)["units"])


def test_rows_saved_before_the_playground_keep_their_threshold_rule(tmp_path):
    import json
    path = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _config("active")
    unit = load_draft(path).units[0]
    legacy_row = {"text_hash": gate._unit_hash(unit, path), "config_hash": gate._config_hash(cfg.jev),
                  "prediction": "organizational", "confidence": 0.6, "override": None, "error": None}

    def write(row):
        with open(gate._path(path), "w", encoding="utf-8") as stream:
            json.dump({unit.unit_id: row}, stream)

    write(legacy_row)
    with patch.object(gate, "load_config", return_value=cfg), patch("rt.llm.jev_client.call_jev") as called:
        gate.refresh(path)
        called.assert_not_called()  # impronta invariata: nessuna nuova chiamata dopo l'aggiornamento
        assert gate.included(path, unit)  # 0.6 < 0.85: passa, come prima
        write({**legacy_row, "confidence": 0.9})
        assert not gate.included(path, unit)


def test_force_reclassifies_every_unit_and_keeps_corrections(tmp_path):
    """'Riclassifica tutte' (rt relevance --all): nuove chiamate anche con la cache valida,
    e le correzioni dell'utente sul testo invariato restano."""
    path = setup_mock_lesson(tmp_path, num_units=2)
    answer = JevChoiceAnswer(choice="organizational", confidence=0.99,
                             probabilities={"didactic": 0.01, "organizational": 0.99, "no_content": 0.0})
    response = JevResponse(model="typesafe/jev-1.13", answers={"rilevanza": answer}, usage={})
    with patch.object(gate, "load_config", return_value=_config("active")), \
            patch("rt.llm.jev_client.call_jev", return_value=response) as called:
        gate.refresh(path)
        unit = load_draft(path).units[0]
        gate.set_override(path, unit.unit_id, "didactic", actor="test")
        gate.refresh(path)
        assert called.call_count == 2  # cache valida: nessuna nuova chiamata
        gate.refresh(path, force=True)
        assert called.call_count == 4
        assert gate.list_units(path)["units"][0]["override"] == "didactic"
        assert gate.included(path, unit)


def test_run_is_refused_when_relevance_is_disabled():
    import pytest
    from rt.services.errors import Conflict
    with patch.object(gate, "load_config", return_value=_config("disabled")):
        with pytest.raises(Conflict) as error:
            gate.ensure_can_run()
    assert error.value.code == "relevance_disabled"


def test_summary_says_whether_and_how_the_classifier_ran(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=2)
    with patch.object(gate, "load_config", return_value=_config("active")):
        summary = gate.list_units(path)["summary"]
        assert summary["classified"] == 0 and summary["missing"] == 2 and summary["last_run_at"] is None
    answer = JevChoiceAnswer(choice="organizational", confidence=0.99,
                             probabilities={"didactic": 0.01, "organizational": 0.99, "no_content": 0.0})
    response = JevResponse(model="typesafe/jev-1.13", answers={"rilevanza": answer}, usage={})
    with patch.object(gate, "load_config", return_value=_config("active")), \
            patch("rt.llm.jev_client.call_jev", side_effect=[response, RuntimeError("provider offline")]):
        gate.refresh(path)
        summary = gate.list_units(path)["summary"]
    assert summary["total"] == 2 and summary["classified"] == 1 and summary["errors"] == 1 and summary["missing"] == 0
    assert summary["by_outcome"] == {"didactic": 0, "organizational": 1, "no_content": 0}
    assert summary["by_label"] == {"Organizzativa": 1}
    assert summary["excluded"] == 1 and summary["model"] == "typesafe/jev-1.13"
    assert summary["last_run_at"] and summary["last_run_mode"] == "active"


def test_review_included_uses_shared_rule_for_disabled_active_and_stale(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=2)
    for mode in ("disabled", "active"):
        with patch.object(gate, "load_config", return_value=_config(mode)):
            units = load_draft(path).units
            if mode == "active":
                gate.refresh(path, force_mock=True)
                gate.set_override(path, units[0].unit_id, "organizational", actor="test")
            rows = gate.list_units(path)["units"]
            assert [row["review_included"] for row in rows] == [gate.included(path, unit) for unit in units]
            if mode == "active":
                assert rows[0]["review_included"] is False
                records = gate._load(path)
                records[units[0].unit_id]["text_hash"] = "vecchio"
                gate._save(path, records)
                stale = gate.list_units(path)["units"][0]
                assert stale["stale"] and stale["review_included"]
                assert stale["review_included"] == gate.included(path, units[0])
            else:
                assert all(row["review_included"] for row in rows)
