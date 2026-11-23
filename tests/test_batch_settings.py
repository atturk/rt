"""Test della fase 6: impostazioni batch su connessioni, fasi, rotte, API e stima costi."""
from types import SimpleNamespace

import pytest

from rt.llm import pricing
from rt.services import connections_service, settings_service
from tests.api_support import workspace_with_example_config


@pytest.fixture
def settings_ws(tmp_path, monkeypatch, rt_db):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return workspace_with_example_config(tmp_path, monkeypatch)


def _create_openrouter_conn(api_client, name="Studio OR", models=None):
    payload = {
        "name": name,
        "provider": "openrouter",
        "api_keys": ["sk-or-v1-test-batch-key-1234567890"],
    }
    res = api_client.post("/api/v1/settings/connections", json=payload)
    assert res.status_code in (200, 201), res.text
    snap = res.json()
    for m in models or ():
        r_m = api_client.post(f"/api/v1/settings/connections/{name}/models", json={"model": m})
        assert r_m.status_code in (200, 201), r_m.text
        snap = r_m.json()
    return snap


def test_snapshot_exposes_batch_capabilities_and_models(api_client, settings_ws, monkeypatch):
    _create_openrouter_conn(
        api_client,
        models=["google/gemini-2.5-flash", "openai/gpt-4.1", "meta-llama/llama-3.3-70b"],
    )
    res_local = api_client.post(
        "/api/v1/settings/connections",
        json={
            "name": "Locale",
            "provider": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "models": ["llama3"],
            "api_keys": ["dummy-key"],
        },
    )
    assert res_local.status_code in (200, 201), res_local.text

    monkeypatch.setattr(
        pricing,
        "_OPENROUTER_BATCH_MODELS",
        {"google/gemini-2.5-flash", "openai/gpt-4.1"},
    )
    snap = api_client.get("/api/v1/settings").json()
    by_name = {c["name"]: c for c in snap["connections"]}
    assert by_name["Studio OR"]["supports_batch"] is True
    assert by_name["Studio OR"]["batch_models"] == ["google/gemini-2.5-flash", "openai/gpt-4.1"]
    assert by_name["Locale"]["supports_batch"] is False
    assert by_name["Locale"]["batch_models"] == []
    assert all(p["batch"] is False for p in snap["phases"])


def test_assign_phase_batch_sets_only_selected_phase_and_validates(api_client, settings_ws):
    _create_openrouter_conn(api_client)
    res_local = api_client.post(
        "/api/v1/settings/connections",
        json={
            "name": "Locale",
            "provider": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_keys": ["dummy-key"],
        },
    )
    assert res_local.status_code in (200, 201), res_local.text

    # Prima imposta altre fasi in sincrono.
    r_outline = api_client.put(
        "/api/v1/settings/phases/outline",
        json={"connection": "Studio OR", "model": "openai/gpt-4.1", "batch": False},
    )
    assert r_outline.status_code == 200, r_outline.text

    # Assegna rewrite con suffisso :batch -> salva modello base + batch=True.
    r_rw = api_client.put(
        "/api/v1/settings/phases/rewrite",
        json={"connection": "Studio OR", "model": "google/gemini-2.5-flash:batch"},
    )
    assert r_rw.status_code == 200, r_rw.text
    phases = {p["job"]: p for p in r_rw.json()["phases"]}
    assert phases["rewrite"]["model"] == "google/gemini-2.5-flash"
    assert phases["rewrite"]["batch"] is True
    assert phases["outline"]["batch"] is False

    # Rotta esplicita GET/PUT riflette batch=True solo su rewrite.
    route_rw = api_client.get("/api/v1/settings/routes/rewrite/primary").json()
    assert route_rw["batch"] is True
    assert route_rw["model"] == "google/gemini-2.5-flash"
    assert api_client.get("/api/v1/settings/routes/outline/primary").json()["batch"] is False

    # Disabilita batch sulla stessa fase.
    r_rw_sync = api_client.put(
        "/api/v1/settings/phases/rewrite",
        json={"connection": "Studio OR", "model": "google/gemini-2.5-flash", "batch": False},
    )
    assert r_rw_sync.status_code == 200, r_rw_sync.text
    phases_after = {p["job"]: p for p in r_rw_sync.json()["phases"]}
    assert phases_after["rewrite"]["batch"] is False

    # Fasi immagine non possono usare il batch.
    r_img = api_client.put(
        "/api/v1/settings/phases/image_description",
        json={"connection": "Studio OR", "model": "openai/gpt-4.1", "batch": True},
    )
    assert r_img.status_code == 422
    r_enr_img = api_client.put(
        "/api/v1/settings/phases/enrichment_image",
        json={"connection": "Studio OR", "model": "openai/gpt-4.1", "batch": True},
    )
    assert r_enr_img.status_code == 422

    # Provider senza supports_batch rifiuta batch=True.
    r_unsupp = api_client.put(
        "/api/v1/settings/phases/review",
        json={"connection": "Locale", "model": "llama3", "batch": True},
    )
    assert r_unsupp.status_code == 422


def test_put_route_batch_roundtrip_and_unsupported_rejection(api_client, settings_ws):
    conn_snap = _create_openrouter_conn(api_client)
    cred_name = next(c["credentials"][0]["name"] for c in conn_snap["connections"] if c["name"] == "Studio OR")
    res_put = api_client.put(
        "/api/v1/settings/routes/review/primary",
        json={
            "provider": "openrouter",
            "model": "google/gemini-2.5-flash",
            "credential": cred_name,
            "batch": True,
        },
    )
    assert res_put.status_code == 200, res_put.text
    assert res_put.json()["batch"] is True

    res_get = api_client.get("/api/v1/settings/routes/review/primary")
    assert res_get.status_code == 200
    assert res_get.json()["batch"] is True

    res_bad = api_client.put(
        "/api/v1/settings/routes/review/primary",
        json={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "credential": cred_name,
            "batch": True,
        },
    )
    assert res_bad.status_code == 422


def test_estimate_configured_lesson_cost_halves_when_rewrite_uses_batch():
    sync_cfg = SimpleNamespace(
        pricing=None,
        jobs={
            "rewrite": SimpleNamespace(
                primary=SimpleNamespace(
                    is_configured=True,
                    provider="openrouter",
                    model="deepseek/deepseek-chat",
                    batch=False,
                )
            )
        },
    )
    batch_cfg = SimpleNamespace(
        pricing=None,
        jobs={
            "rewrite": SimpleNamespace(
                primary=SimpleNamespace(
                    is_configured=True,
                    provider="openrouter",
                    model="deepseek/deepseek-chat",
                    batch=True,
                )
            )
        },
    )
    sync_cost, _ = pricing.estimate_configured_lesson_cost(config=sync_cfg)
    batch_cost, _ = pricing.estimate_configured_lesson_cost(config=batch_cfg)
    assert sync_cost is not None and batch_cost is not None
    assert batch_cost == pytest.approx(sync_cost * 0.5, rel=1e-6)
