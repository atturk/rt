"""Il gate di rilevanza non deve omettere unità in ombra o dopo errori JEV."""
from unittest.mock import patch

from rt.core.config import RTConfig, JevConfig
from rt.llm.jev_client import JevChoiceAnswer, JevResponse
from rt.pipeline.rewrite import load_draft
from rt.services import unit_relevance as gate
from tests.test_jev_prefilter import setup_mock_lesson


def _config(mode="shadow"):
    return RTConfig(jev=JevConfig(relevance_model="typesafe/jev-1.13", relevance_mode=mode))


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
