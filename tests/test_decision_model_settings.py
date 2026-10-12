import json
import os
from unittest.mock import patch

import yaml

from rt.llm.jev_client import JevChoiceAnswer, JevError, JevNoulAnswer, JevResponse
from tests.api_support import isolated_workspace, make_lesson

PATH = "/api/v1/settings/decision-model"


def test_decision_model_requires_structured_protocol_probe(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    body = {"model": "decision/example", "credential": "openrouter", "enabled": True,
            "shadow": True, "threshold": 0.9}
    path = PATH
    assert api_client.put(path, json=body).status_code == 200
    answer = JevResponse(model=body["model"], answers={"categoria": JevChoiceAnswer(
        choice="banana", confidence=.95, probabilities={"banana": .95, "altro": .05})})
    with patch("rt.llm.jev_client.call_jev", return_value=answer):
        assert api_client.post(path + "/probe", json=body).json()["ok"] is True
    assert api_client.put(path, json=body).status_code == 200
    saved = api_client.get(path).json()
    assert saved["threshold"] == 0.9
    assert "model" not in _general()["jev"]
    assert "classifier" in _general()
    assert api_client.put(path, json={**body, "threshold": 1.5}).status_code == 422


def _general():
    with open(os.path.join("config", "general.yaml"), encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _noul_decision(outcome="no_content"):
    return {"question": "L'unità è priva di nozioni?", "type": "noul", "fallback_label": "Didattica",
            "rules": [{"label": "Vuota", "outcome": outcome, "match": "all",
                       "conditions": [{"field": "noul", "op": "gte", "value": "0.7"}]}]}


def test_get_returns_effective_defaults_and_templates(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    data = api_client.get(PATH).json()
    assert data["relevance_customized"] is False and data["prefilter_customized"] is False
    assert data["relevance_decision"]["type"] == "score"
    assert data["relevance_decision"]["recall_richness"] is True and len(data["relevance_decision"]["levels"]) == 3
    assert data["prefilter_decision"]["rules"][0]["outcome"] == "skip_review"
    assert set(data["templates"]) == {"relevance", "prefilter"}
    assert set(data["templates"]["prefilter"]) == {"choice", "noul", "score"}


def test_saving_the_default_stores_nothing_and_custom_decisions_are_persisted(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    current = api_client.get(PATH).json()
    body = {k: current[k] for k in ("enabled", "shadow", "model", "relevance_model", "credential", "threshold",
                                    "relevance_mode", "relevance_prompt", "relevance_threshold",
                                    "prefilter_type", "prefilter_prompt", "relevance_decision", "prefilter_decision")}
    assert api_client.put(PATH, json=body).status_code == 200
    assert "relevance_decision" not in _general()["jev"] and "prefilter_decision" not in _general()["jev"]

    invalid = api_client.put(PATH, json={**body, "relevance_decision": _noul_decision("skip_review")})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_decision"

    saved = api_client.put(PATH, json={**body, "relevance_decision": _noul_decision()})
    assert saved.status_code == 200 and saved.json()["relevance_customized"] is True
    stored = _general()["jev"]["relevance_decision"]
    assert stored["type"] == "noul" and stored["rules"][0]["conditions"][0]["value"] == 0.7
    assert api_client.get(PATH).json()["relevance_decision"]["question"] == "L'unità è priva di nozioni?"

    # Tornare alla domanda predefinita rimuove la personalizzazione.
    reset = api_client.put(PATH, json={**body, "relevance_decision": current["templates"]["relevance"]["score"]})
    assert reset.json()["relevance_customized"] is False and "relevance_decision" not in _general()["jev"]

    # Il prefiltro con il modello noul predefinito resta "predefinito" e segue il tipo storico.
    template = current["templates"]["prefilter"]["noul"]
    assert api_client.put(PATH, json={**body, "prefilter_decision": template}).status_code == 200
    assert _general()["jev"]["prefilter_type"] == "noul" and "prefilter_decision" not in _general()["jev"]


def test_saving_an_active_noul_relevance_requires_a_noul_probe(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    body = {"relevance_model": "decision/example", "relevance_mode": "active", "relevance_decision": _noul_decision()}
    refused = api_client.put(PATH, json=body)
    assert refused.status_code == 200
    assert "relevance_model" not in _general()["jev"]
    answer = JevResponse(model="m", answers={"rilevanza": JevNoulAnswer(noul=0.9)})
    with patch("rt.llm.jev_client.call_jev", return_value=answer):
        tested = api_client.post(PATH + "/test", json={"phase": "relevance", "decision": _noul_decision(),
                                                       "model": "decision/example"})
    assert tested.status_code == 200
    assert api_client.put(PATH, json=body).status_code == 200


def test_playground_runs_a_draft_on_the_sample_without_saving(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    answer = JevResponse(model="m", answers={"rilevanza": JevNoulAnswer(noul=0.9)},
                         raw={"model": "m", "answers": {"rilevanza": {"type": "noul", "noul": 0.9}}})
    with patch("rt.llm.jev_client.call_jev", return_value=answer) as called:
        response = api_client.post(PATH + "/test", json={"phase": "relevance", "decision": _noul_decision(),
                                                         "model": "decision/example"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["label"], data["outcome"], data["rule"]) == ("Vuota", "no_content", 0)
    assert data["response"] == {"model": "m", "answers": {"rilevanza": {"type": "noul", "noul": 0.9}}}
    assert data["unit_id"] is None and "Titolo: Esempio" in data["state"] and "Anatomia" in data["state"]
    assert called.call_args.args[1]["rilevanza"].instructions == "L'unità è priva di nozioni?"
    assert "jev" not in _general() or "relevance_decision" not in _general()["jev"]


def test_playground_runs_on_a_chosen_lesson_unit(api_client, rt_db, tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    draft = {"schema_version": "1.0", "units": [
        {"unit_id": f"1.{i}", "title": f"Titolo {i}", "start_segment_id": "seg_000001",
         "end_segment_id": "seg_000001", "source_segment_ids": ["seg_000001"], "content": f"Testo {i}."}
        for i in (1, 2)]}
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as stream:
        json.dump(draft, stream)
    from rt.services.lesson_service import lesson_id_for_dir
    lesson_id = lesson_id_for_dir(lesson_dir)
    decision = api_client.get(PATH).json()["prefilter_decision"]
    answer = JevResponse(model="m", answers={"correttezza": JevChoiceAnswer(
        choice="corretta", confidence=0.9, probabilities={"corretta": 0.9, "imprecisione": 0.05, "errore_grave": 0.05})})
    with patch("rt.llm.jev_client.call_jev", return_value=answer) as called:
        response = api_client.post(PATH + "/test", json={"phase": "prefilter", "decision": decision, "model": "m",
                                                         "lesson_id": lesson_id, "unit_id": "1.2"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["unit_id"] == "1.2" and data["state"] == "Testo 2."  # il prefiltro vede solo il testo
    assert data["outcome"] == "skip_review" and data["answer"]["probabilities"]["errore_grave"] == 0.05
    assert called.call_args.args[0] == "Testo 2."
    missing = api_client.post(PATH + "/test", json={"phase": "prefilter", "decision": decision, "model": "m",
                                                    "lesson_id": lesson_id, "unit_id": "9.9"})
    assert missing.status_code == 404


def test_playground_reports_jev_errors_and_invalid_mappings(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    with patch("rt.llm.jev_client.call_jev", side_effect=JevError("offline")):
        failed = api_client.post(PATH + "/test", json={"phase": "relevance", "decision": _noul_decision(), "model": "m"})
    assert failed.status_code == 422 and failed.json()["error"]["code"] == "decision_protocol_failed"
    wrong_outcome = api_client.post(PATH + "/test", json={"phase": "prefilter", "decision": _noul_decision(), "model": "m"})
    assert wrong_outcome.status_code == 422
    bad_field = _noul_decision()
    bad_field["rules"][0]["conditions"][0]["field"] = "choice"
    assert api_client.post(PATH + "/test", json={"phase": "relevance", "decision": bad_field, "model": "m"}).status_code == 422
    assert api_client.post(PATH + "/test", json={"phase": "relevance", "decision": _noul_decision(), "model": " "}).status_code == 422


def test_active_default_relevance_requires_score_probe(api_client, rt_db, tmp_path, monkeypatch):
    from rt.llm.jev_client import JevScoreAnswer
    isolated_workspace(tmp_path, monkeypatch)
    body = {'relevance_model': 'decision/richness-score', 'relevance_mode': 'active'}
    refused = api_client.put(PATH, json=body)
    assert refused.status_code == 200
    assert 'relevance_model' not in _general()['jev']
    answer = JevResponse(model=body['relevance_model'], answers={'rilevanza': JevScoreAnswer(score=0, confidence=.99)})
    decision = api_client.get(PATH).json()['relevance_decision']
    with patch('rt.llm.jev_client.call_jev', return_value=answer):
        assert api_client.post(PATH + '/test', json={'phase': 'relevance', 'decision': decision, 'model': body['relevance_model']}).status_code == 200
    assert api_client.put(PATH, json=body).status_code == 200
