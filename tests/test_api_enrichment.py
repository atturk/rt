import io
import zipfile

import pytest

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker


@pytest.fixture
def ready(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = make_lesson(root)
    result = run_mock_pipeline(path)
    assert not result.error
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    return path, lid, Worker(DbJobQueue(rt_db), worker_id="enrichment-test", mock=True)


def test_analyze_dedup_generate_export_edit_delete(api_client, ready):
    path, lid, worker = ready
    base = f"/api/v1/lessons/{lid}/enrichment"
    # Per default la pipeline non analizza: le idee arrivano dalla pagina Arricchimento.
    assert api_client.get(base).json()["elements"] == []
    a = api_client.post(base + "/analyze", json={})
    b = api_client.post(base + "/analyze", json={})
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] == b.json()["job_id"]
    worker.run_once()
    ideas = api_client.get(base).json()["elements"]
    assert ideas and not any(e["asset_image"] for e in ideas)
    idea = ideas[0]
    generated = api_client.post(base + "/generate", json={"element_id": idea["id"]})
    assert generated.status_code == 202
    again = api_client.post(base + "/generate", json={"element_id": idea["id"]})
    assert generated.json()["job_id"] == again.json()["job_id"]
    assert api_client.get(base).json()["elements"][0]["status"] == "queued"
    worker.run_once()
    job = api_client.get(f"/api/v1/jobs/{generated.json()['job_id']}").json()
    assert job["state"] == "succeeded", job
    result = api_client.get(base).json()["elements"][0]
    assert result["status"] == "ready"
    image = api_client.get(f"/api/v1/lessons/{lid}/{result['asset_image']}")
    html = api_client.get(f"/api/v1/lessons/{lid}/{result['asset_html']}")
    assert image.content.startswith(b"\x89PNG")
    assert "sandbox allow-scripts" in html.headers["Content-Security-Policy"]
    assert "connect-src 'none'" in html.text
    document = api_client.get(f"/api/v1/lessons/{lid}/document").json()
    assert result["asset_image"] in document["markdown"]
    assert result["asset_image"] not in document["html"]  # rendered by the structured UI
    export = api_client.get(f"/api/v1/lessons/{lid}/export", params={"format": "zip"})
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert any(n.endswith("/" + result["asset_image"]) for n in archive.namelist())
        assert any(n.endswith("/" + result["asset_html"]) for n in archive.namelist())
    edited = api_client.put(base + "/" + result["id"], json={"kind": "infographic", "title": "Nuovo titolo",
        "description": "Idea modificata", "prompt": "Rappresenta la struttura", "mode": "static"})
    assert edited.status_code == 200
    assert edited.json()["elements"][0]["asset_image"] == result["asset_image"]
    deleted = api_client.post(base + "/" + result["id"] + "/action", json={"action": "delete"})
    assert deleted.status_code == 200
    assert result["asset_image"] not in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]


def test_batch_skips_unready_and_manual_generation_is_not_capped(api_client, ready, rt_db):
    path, lid, worker = ready
    response = api_client.post("/api/v1/enrichment/analyze", json={"lesson_ids": [lid, lid, 999999]})
    assert response.status_code == 202
    assert response.json()["queued"] == 1 and response.json()["skipped"] == [999999]
    duplicate = api_client.post("/api/v1/enrichment/analyze", json={"lesson_ids": [lid]})
    assert duplicate.json()["existing"] == 1
    worker.run_once()
    base = f"/api/v1/lessons/{lid}/enrichment"
    ideas = api_client.get(base).json()
    api_client.put(base + "/cap", json={"mode": "fixed", "number": 1})
    result = api_client.post(base + "/generate", json={"unit_id": ideas["units"][0]["id"], "prompt": "Schema manuale", "kind": "infographic"})
    assert result.status_code == 202
    worker.run_once()
    elements = api_client.get(base).json()["elements"]
    assert any(e["manual"] and e["status"] == "ready" for e in elements)


def test_cancelled_generation_is_recoverable_and_asset_paths_are_protected(api_client, ready):
    _, lid, worker = ready
    base = f"/api/v1/lessons/{lid}/enrichment"
    api_client.post(base + "/analyze", json={})
    worker.run_once()
    idea = api_client.get(base).json()["elements"][0]
    queued = api_client.post(base + "/generate", json={"element_id": idea["id"]}).json()
    api_client.post(f"/api/v1/jobs/{queued['job_id']}/cancel")
    state = api_client.get(base).json()["elements"][0]
    assert state["status"] == "error"
    assert api_client.post(base + "/" + idea["id"] + "/action", json={"action": "dismiss"}).status_code == 200
    retry = api_client.post(base + "/generate", json={"element_id": idea["id"]})
    assert retry.status_code == 202
    worker.run_once()
    assert api_client.get(base).json()["elements"][0]["status"] == "ready"
    assert api_client.get(f"/api/v1/lessons/{lid}/assets/enrichment/manifest.json").status_code == 404
    assert api_client.post(base + "/generate", json={"unit_id": "99.99", "prompt": "Test"}).status_code == 422
