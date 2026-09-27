import pytest

from rt.services.document_edit_lease import assert_editable
from tests.api_support import isolated_workspace, make_lesson


@pytest.fixture
def lesson(api_client, rt_db, tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    return api_client.get("/api/v1/lessons").json()[0]["id"]


def test_lease_blocks_second_editor_and_jobs_until_released(api_client, lesson):
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    lease = api_client.post(endpoint).json()
    assert len(lease["token"]) > 20
    assert api_client.post(endpoint).status_code == 409
    assert api_client.post(endpoint, params={"token": lease["token"]}).status_code == 200
    blocked = api_client.post(f"/api/v1/lessons/{lesson}/jobs", json={"type": "run_phase", "phase": "prepare"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "document_edit_busy"
    assert api_client.delete(endpoint, params={"token": lease["token"]}).status_code == 204
    assert api_client.post(f"/api/v1/lessons/{lesson}/jobs", json={"type": "run_phase", "phase": "prepare"}).status_code == 202


def test_lease_requires_valid_token_to_save(api_client, lesson):
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    token = api_client.post(endpoint).json()["token"]
    markdown = "### 1.1 Argomento\n00:00\nTesto"
    target = f"/api/v1/lessons/{lesson}/document/draft"
    assert api_client.put(target, json={"markdown": markdown}).status_code == 409
    assert api_client.put(target, json={"markdown": markdown, "lease_token": "wrong"}).status_code == 409
    assert_editable(lesson, token)
