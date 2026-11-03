"""
tests/test_api_cloud.py
Modalità facilitata (RT Cloud): accesso con codice, chiave installata come connessione
OpenRouter "RT Cloud", fasi assegnate, saldo letto da OpenRouter. Il backend è finto:
nessuna risposta dell'API locale deve contenere la chiave o il token.
"""
import os

import pytest

from tests.api_support import workspace_with_example_config

OR_KEY = "sk-or-v1-chiave-rt-cloud-0123456789abcdef"
TOKEN = "sessione-rt-cloud-segreta-abcdefghijklmnop"
MODELS = ["deepseek/deepseek-v4-flash", "google/gemini-3.5-flash-lite"]


def _or_model(mid, name, prompt, completion, inputs, outputs):
    return {"id": mid, "name": name, "pricing": {"prompt": prompt, "completion": completion},
            "architecture": {"input_modalities": inputs, "output_modalities": outputs}}


CATALOG = [
    _or_model("openai/gpt-6-luna", "GPT-6 Luna", "0.0000001", "0.0000005", ["text", "image"], ["text"]),
    _or_model("x/solo-testo", "Solo testo", "0.000002", "0.00001", ["text"], ["text"]),
    _or_model("meta/muse-image", "Muse Image", "0", "0.00004", ["text", "image"], ["image"]),
]


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class FakeCloud:
    """Backend RT Cloud e OpenRouter finti, con lo stesso contratto di cloud/src/app.ts."""

    def __init__(self):
        self.subscription = "none"
        self.topup_balance = 0
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        path = url.split("cloud.test", 1)[1]
        self.calls.append((method, path, json))
        auth = (headers or {}).get("Authorization")
        if path == "/v1/plans":
            return FakeResponse(200, {"plans": [{"id": "mese", "label": "3,99 € al mese"},
                                                {"id": "anno", "label": "29,99 € all'anno"}], "models": MODELS,
                                      "topup": {"min_cents": 500, "max_cents": 20000, "valid_days": 365}})
        if path == "/v1/auth/start":
            return FakeResponse(200, {"ok": True})
        if path == "/v1/auth/verify":
            if json["code"] != "123456":
                return FakeResponse(400, {"error": {"code": "invalid_code", "message": "Codice non valido o scaduto"}})
            return FakeResponse(200, {"token": TOKEN})
        if auth != f"Bearer {TOKEN}":
            return FakeResponse(401, {"error": {"code": "unauthorized", "message": "Accesso richiesto"}})
        if path == "/v1/me":
            active = self.subscription in ("active", "canceled") or self.topup_balance > 0
            return FakeResponse(200, {
                "email": "studente@example.com",
                "subscription": {"status": self.subscription, "plan": "base" if active else None,
                                 "current_period_end": None, "monthly_quota_usd": 1.44 if active else 0},
                "topup": {"balance_usd": self.topup_balance, "next_expiry": None},
                "openrouter_key": OR_KEY if active else None,
                "models": MODELS,
                "vision_model": MODELS[1],
            })
        if path == "/v1/checkout":
            return FakeResponse(200, {"url": "https://sandbox.polar.sh/checkout/x"})
        if path == "/v1/topup":
            if json["amount_cents"] < 500:
                return FakeResponse(400, {"error": {"code": "invalid_amount", "message": "Importo tra 5 € e 200 €"}})
            return FakeResponse(200, {"url": f"https://sandbox.polar.sh/checkout/topup?amount={json['amount_cents']}"})
        if path == "/v1/portal":
            return FakeResponse(200, {"url": "https://sandbox.polar.sh/portal"})
        if path == "/v1/auth/logout":
            return FakeResponse(200, {"ok": True})
        return FakeResponse(404, {"error": {"code": "not_found", "message": "?"}})

    def get(self, url, headers=None, timeout=None):
        if url == "https://openrouter.ai/api/v1/models":
            self.catalog_calls = getattr(self, "catalog_calls", 0) + 1
            return FakeResponse(200, {"data": CATALOG})
        assert url == "https://openrouter.ai/api/v1/key"
        assert headers["Authorization"] == f"Bearer {OR_KEY}"
        return FakeResponse(200, {"data": {"usage": 0.4, "limit": 1.44, "limit_remaining": 1.04}})


@pytest.fixture
def cloud(tmp_path, monkeypatch, rt_db):
    workspace_with_example_config(tmp_path, monkeypatch)
    monkeypatch.setenv("RT_CLOUD_URL", "https://cloud.test")
    monkeypatch.delenv("RT_CLOUD_TOKEN", raising=False)
    fake = FakeCloud()
    from rt.services import cloud_service
    monkeypatch.setattr(cloud_service.requests, "request", fake.request)
    monkeypatch.setattr(cloud_service.requests, "get", fake.get)
    yield fake
    os.environ.pop("RT_CLOUD_TOKEN", None)


def _clean(res):
    assert OR_KEY not in res.text and TOKEN not in res.text
    return res


def _login(api_client):
    assert api_client.post("/api/v1/cloud/login/start", json={"email": "studente@example.com"}).status_code == 204
    res = _clean(api_client.post("/api/v1/cloud/login/verify",
                                 json={"email": "studente@example.com", "code": "123456"}))
    assert res.status_code == 200
    return res.json()


def test_not_available_without_url(api_client, tmp_path, monkeypatch, rt_db):
    workspace_with_example_config(tmp_path, monkeypatch)
    monkeypatch.delenv("RT_CLOUD_URL", raising=False)
    data = api_client.get("/api/v1/cloud").json()
    assert data["available"] is False and data["logged_in"] is False
    res = api_client.post("/api/v1/cloud/login/start", json={"email": "a@example.com"})
    assert res.status_code == 503


def test_wrong_code(api_client, cloud):
    res = api_client.post("/api/v1/cloud/login/verify", json={"email": "studente@example.com", "code": "000000"})
    assert res.status_code == 400
    assert api_client.get("/api/v1/cloud").json()["logged_in"] is False


def test_login_without_subscription_installs_nothing(api_client, cloud):
    data = _login(api_client)
    assert data["logged_in"] is True and data["email"] == "studente@example.com"
    assert data["subscription"]["status"] == "none"
    assert data["connection"] is False and data["balance"] is None
    settings = api_client.get("/api/v1/settings").json()
    assert settings["connections"] == []


def test_active_subscription_becomes_connection_with_phases(api_client, cloud):
    _login(api_client)
    cloud.subscription = "active"
    data = _clean(api_client.post("/api/v1/cloud/sync", json={"assign_all": True})).json()
    assert data["connection"] is True
    assert data["balance"] == {"limit_usd": 1.44, "usage_usd": 0.4, "remaining_usd": 1.04}

    settings = _clean(api_client.get("/api/v1/settings")).json()
    connection = next(c for c in settings["connections"] if c["name"] == "RT Cloud")
    assert connection["provider"] == "openrouter"
    assert sorted(connection["models"]) == sorted(MODELS)
    phases = {p["job"]: p for p in settings["phases"]}
    for job in ("outline", "rewrite", "review", "recall"):
        assert phases[job]["connection"] == "RT Cloud" and phases[job]["model"] == MODELS[0]
    assert phases["image_description"]["connection"] == "RT Cloud"
    assert phases["image_description"]["model"] == MODELS[1]
    # le infografiche richiedono modelli d'immagine: restano come sono
    assert phases["enrichment_image"]["connection"] != "RT Cloud"

    from rt.core.config import get_api_key
    assert get_api_key(connection["credentials"][0]["name"]) == OR_KEY

    # una seconda sincronizzazione non duplica nulla
    _clean(api_client.post("/api/v1/cloud/sync", json={}))
    names = [c["name"] for c in api_client.get("/api/v1/settings").json()["connections"]]
    assert names.count("RT Cloud") == 1


def test_sync_without_assign_all_keeps_existing_phases(api_client, cloud):
    api_client.post("/api/v1/settings/connections",
                    json={"name": "Mia", "provider": "openrouter", "api_keys": ["sk-or-v1-mia-chiave-0123456789"]})
    api_client.put("/api/v1/settings/phases/rewrite", json={"connection": "Mia", "model": "openai/gpt-5"})
    _login(api_client)
    cloud.subscription = "active"
    api_client.post("/api/v1/cloud/sync", json={})
    phases = {p["job"]: p for p in api_client.get("/api/v1/settings").json()["phases"]}
    assert phases["rewrite"]["connection"] == "Mia"
    assert phases["outline"]["connection"] == "RT Cloud"


def test_checkout_portal_logout(api_client, cloud):
    assert api_client.post("/api/v1/cloud/checkout", json={}).status_code == 401
    _login(api_client)
    assert api_client.post("/api/v1/cloud/checkout", json={"plan": "base"}).json()["url"].startswith("https://sandbox.polar.sh")
    assert api_client.post("/api/v1/cloud/portal").json()["url"].endswith("/portal")
    data = api_client.post("/api/v1/cloud/logout").json()
    assert data["logged_in"] is False
    assert ("POST", "/v1/auth/logout", None) in cloud.calls


def test_plans(api_client, cloud):
    data = api_client.get("/api/v1/cloud/plans").json()
    assert [p["id"] for p in data["plans"]] == ["mese", "anno"]
    assert data["models"] == MODELS


def test_topup(api_client, cloud):
    _login(api_client)
    assert api_client.post("/api/v1/cloud/topup", json={"amount_cents": 400}).status_code == 400
    res = api_client.post("/api/v1/cloud/topup", json={"amount_cents": 2000})
    assert res.json()["url"].endswith("amount=2000")
    assert api_client.get("/api/v1/cloud/plans").json()["topup"]["min_cents"] == 500


def test_topup_keeps_key_after_subscription_ends(api_client, cloud):
    _login(api_client)
    cloud.subscription = "revoked"
    cloud.topup_balance = 13.33
    data = _clean(api_client.post("/api/v1/cloud/sync", json={})).json()
    assert data["topup"]["balance_usd"] == 13.33
    assert data["connection"] is True
    assert data["balance"]["remaining_usd"] == 1.04


def test_status_lists_pool_and_choose_model(api_client, cloud):
    _login(api_client)
    cloud.subscription = "active"
    data = api_client.post("/api/v1/cloud/sync", json={"assign_all": True}).json()
    assert [m["id"] for m in data["pool"]] == MODELS
    assert data["pool"][0]["recommended"] is True
    assert data["current_model"] == MODELS[0]

    data = _clean(api_client.post("/api/v1/cloud/model", json={"model": "x/solo-testo"})).json()
    assert data["current_model"] == "x/solo-testo"
    phases = {p["job"]: p for p in api_client.get("/api/v1/settings").json()["phases"]}
    assert phases["outline"]["model"] == "x/solo-testo" and phases["outline"]["connection"] == "RT Cloud"
    assert phases["image_description"]["model"] == MODELS[1]  # la visione resta com'era


def test_choose_model_needs_connection(api_client, cloud):
    _login(api_client)
    assert api_client.post("/api/v1/cloud/model", json={"model": "x/solo-testo"}).status_code == 409


def test_catalog_filtered_by_capability(api_client, cloud):
    from rt.services import cloud_service
    cloud_service._catalog_cache.update(at=0.0, models=None)
    text = api_client.get("/api/v1/cloud/catalog").json()
    assert [m["id"] for m in text] == ["openai/gpt-6-luna", "x/solo-testo"]  # dal più economico
    assert text[0]["lesson_usd"] == 0.055
    assert [m["id"] for m in api_client.get("/api/v1/cloud/catalog?capability=vision").json()] == ["openai/gpt-6-luna"]
    assert [m["id"] for m in api_client.get("/api/v1/cloud/catalog?capability=image").json()] == ["meta/muse-image"]
    assert api_client.get("/api/v1/cloud/catalog?capability=boh").status_code == 400
    assert cloud.catalog_calls == 1  # in cache
