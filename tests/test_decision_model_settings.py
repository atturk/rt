from unittest.mock import patch

import pytest

from rt.llm.jev_client import JevChoiceAnswer, JevResponse
from tests.api_support import isolated_workspace


def test_decision_model_requires_structured_protocol_probe(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    body = {"model": "decision/example", "credential": "openrouter", "enabled": True,
            "shadow": True, "threshold": 0.9}
    path = "/api/v1/settings/decision-model"
    assert api_client.put(path, json=body).status_code == 422
    answer = JevResponse(model=body["model"], answers={"categoria": JevChoiceAnswer(
        choice="banana", confidence=.95, probabilities={"banana": .95, "altro": .05})})
    with patch("rt.llm.jev_client.call_jev", return_value=answer):
        assert api_client.post(path + "/probe", json=body).json()["ok"] is True
    assert api_client.put(path, json=body).status_code == 200
    saved = api_client.get(path).json()
    assert saved["enabled"] is True and saved["shadow"] is True and saved["threshold"] == 0.9
    assert api_client.put(path, json={**body, "threshold": 1.5}).status_code == 422
