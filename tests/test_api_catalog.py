"""Test per il catalogo modelli per connessione (successo, fallback su errore, cache) e verifica chiave."""
from types import SimpleNamespace

import pytest
import requests

from rt.services import connections_service as cs
from tests.api_support import workspace_with_example_config

KEY = "sk-or-v1-catalog-secret-9876543210"


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    cs.clear_catalog_cache()
    yield workspace_with_example_config(tmp_path, monkeypatch)
    cs.clear_catalog_cache()


def _create_conn(client, name="OpenRouter", provider="openrouter", base_url=""):
    res = client.post(
        "/api/v1/settings/connections",
        json={"name": name, "provider": provider, "base_url": base_url, "api_keys": [KEY]},
    )
    assert res.status_code == 201, res.text


def test_catalog_success_pricing_and_recommended(api_client, ws, monkeypatch):
    _create_conn(api_client)
    monkeypatch.setitem(cs.RECOMMENDED_MODELS, "openrouter", "deepseek/deepseek-v4-flash")
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append((url, headers, timeout))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "id": "openrouter/auto",
                        "name": "Auto Router",
                        "pricing": {"prompt": "-1", "completion": "-1"},
                    },
                    {
                        "id": "deepseek/deepseek-v4-flash",
                        "name": "DeepSeek V4 Flash",
                        "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
                    },
                ]
            },
        )

    monkeypatch.setattr(cs.requests, "get", fake_get)
    res = api_client.get("/api/v1/settings/connections/OpenRouter/catalog")
    assert res.status_code == 200, res.text
    assert "X-Catalog-Fallback" not in res.headers
    assert KEY not in res.text
    assert len(seen) == 1
    assert seen[0][0] == "https://openrouter.ai/api/v1/models"
    assert seen[0][1]["Authorization"] == f"Bearer {KEY}"
    assert seen[0][2] == cs.CATALOG_TIMEOUT_SECONDS

    items = res.json()
    assert [item["id"] for item in items] == ["deepseek/deepseek-v4-flash", "openrouter/auto"]
    assert items[0] == {
        "id": "deepseek/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash",
        "prompt_price": 0.14,
        "completion_price": 0.28,
        "recommended": True,
    }
    assert items[1]["prompt_price"] is None and items[1]["completion_price"] is None
    assert items[1]["recommended"] is False


def test_catalog_error_falls_back_to_known_models(api_client, ws, monkeypatch):
    _create_conn(api_client)
    assert api_client.post(
        "/api/v1/settings/connections/OpenRouter/models",
        json={"model": "deepseek/deepseek-v4-flash"},
    ).status_code == 200

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(cs.requests, "get", fake_get)
    res = api_client.get("/api/v1/settings/connections/OpenRouter/catalog")
    assert res.status_code == 200
    assert res.headers.get("X-Catalog-Fallback") == "1"
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == "deepseek/deepseek-v4-flash"
    assert items[0]["prompt_price"] == 0.14


def test_catalog_cache_ttl_10_minutes(api_client, ws, monkeypatch):
    _create_conn(api_client)
    calls = 0
    clock = [1000.0]
    monkeypatch.setattr(cs.time, "monotonic", lambda: clock[0])

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": f"m-{calls}", "name": f"Model {calls}"}]},
        )

    monkeypatch.setattr(cs.requests, "get", fake_get)
    first = api_client.get("/api/v1/settings/connections/OpenRouter/catalog").json()
    clock[0] += 300.0
    second = api_client.get("/api/v1/settings/connections/OpenRouter/catalog").json()
    assert calls == 1
    assert first == second

    clock[0] += 301.0
    third = api_client.get("/api/v1/settings/connections/OpenRouter/catalog").json()
    assert calls == 2
    assert third[0]["id"] == "m-2"


def test_catalog_unknown_connection_returns_404(api_client, ws):
    res = api_client.get("/api/v1/settings/connections/Inesistente/catalog")
    assert res.status_code == 404


def test_verify_connection_key_without_saving(api_client, ws, monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        if headers.get("Authorization") == f"Bearer {KEY}":
            return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "m1"}]})
        return SimpleNamespace(status_code=401, reason="Unauthorized", text="bad", json=lambda: {"error": {"message": "bad"}})

    monkeypatch.setattr(cs.requests, "get", fake_get)
    ok_res = api_client.post(
        "/api/v1/settings/connections/verify",
        json={"provider": "openrouter", "base_url": "", "api_key": KEY},
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["ok"] is True
    assert "Chiave valida" in ok_res.json()["message"]
    assert KEY not in ok_res.text
    # Non salva nessuna connessione
    assert api_client.get("/api/v1/settings").json()["connections"] == []

    bad_res = api_client.post(
        "/api/v1/settings/connections/verify",
        json={"provider": "openrouter", "base_url": "", "api_key": "sk-bad-secret"},
    )
    assert bad_res.status_code == 200
    assert bad_res.json()["ok"] is False
    assert "sk-bad-secret" not in bad_res.text
