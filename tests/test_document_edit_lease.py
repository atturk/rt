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
    assert lease["lease_id"] and lease["acquired_at"]
    assert api_client.post(endpoint).status_code == 409
    assert api_client.post(endpoint, params={"token": lease["token"]}).status_code == 200
    blocked = api_client.post(f"/api/v1/lessons/{lesson}/jobs", json={"type": "run_phase", "phase": "prepare"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "document_edit_busy"
    assert api_client.delete(endpoint, params={"token": lease["token"]}).status_code == 204
    assert api_client.post(f"/api/v1/lessons/{lesson}/jobs", json={"type": "run_phase", "phase": "prepare"}).status_code == 202


def test_explicit_recovery_identifies_the_replaced_edit_session(api_client, lesson):
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    original = api_client.post(endpoint).json()
    recovered = api_client.post(endpoint, params={"recover": True}).json()
    assert recovered["recovered"] is True
    assert recovered["previous_lease_id"] == original["lease_id"]
    assert recovered["previous_acquired_at"] == original["acquired_at"]
    assert recovered["lease_id"] != original["lease_id"]
    assert api_client.post(endpoint, params={"token": original["token"]}).status_code == 409


def test_lease_requires_valid_token_to_save(api_client, lesson):
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    token = api_client.post(endpoint).json()["token"]
    markdown = "### 1.1 Argomento\n00:00\nTesto"
    target = f"/api/v1/lessons/{lesson}/document/draft"
    assert api_client.put(target, json={"markdown": markdown}).status_code == 409
    assert api_client.put(target, json={"markdown": markdown, "lease_token": "wrong"}).status_code == 409
    assert_editable(lesson, token)


def test_abandoned_lease_expires_and_stops_blocking_jobs(api_client, lesson, monkeypatch):
    """Una scheda chiusa senza rilasciare il lease non blocca i job per sempre."""
    from datetime import datetime, timedelta, timezone
    from rt.services import document_edit_lease
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    lease = api_client.post(endpoint).json()
    assert datetime.fromisoformat(lease["expires"]) > datetime.now(timezone.utc)
    later = datetime.now(timezone.utc) + document_edit_lease.LEASE_TTL + timedelta(seconds=1)
    real_active = document_edit_lease._active
    monkeypatch.setattr(document_edit_lease, "_active", lambda value, now=None: real_active(value, later))
    assert api_client.post(f"/api/v1/lessons/{lesson}/jobs", json={"type": "run_phase", "phase": "prepare"}).status_code == 202


def test_renewal_keeps_the_session_alive(api_client, lesson):
    endpoint = f"/api/v1/lessons/{lesson}/document/lease"
    first = api_client.post(endpoint).json()
    renewed = api_client.post(endpoint, params={"token": first["token"]}).json()
    assert renewed["lease_id"] == first["lease_id"] and renewed["acquired_at"] == first["acquired_at"]
    assert renewed["expires"] >= first["expires"] and renewed["recovered"] is False
