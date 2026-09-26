"""
tests/test_api_settings_probes.py
RT4-FA5: "Prova" di connessione e modello (anche prima di salvarli) e ricerca web con SearXNG,
contro server finti su 127.0.0.1. Nessuna risposta contiene la chiave.
"""
import pytest
from fastapi.testclient import TestClient

from tests.api_support import fake_llm_server, fake_searxng_server, workspace_with_example_config

KEY = "sk-segreto-prova-modello-0123456789abcdef"


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    monkeypatch.delenv("RT_API_MOCK", raising=False)
    return workspace_with_example_config(tmp_path, monkeypatch)


@pytest.fixture
def llm():
    server, url = fake_llm_server()
    yield server, url
    server.shutdown()


def fresh(api_token):
    from rt.api.app import create_app
    client = TestClient(create_app())
    client.headers["Authorization"] = f"Bearer {api_token}"
    return client


def _connection(client, base_url, name="Locale"):
    res = client.post("/api/v1/settings/connections",
                      json={"name": name, "provider": "openai_compatible", "base_url": base_url, "api_keys": [KEY]})
    assert res.status_code == 201, res.text


def test_model_test_minimal_call_before_saving(api_client, ws, llm):
    server, url = llm
    _connection(api_client, f"{url}/v1")
    before = api_client.get("/api/v1/settings").json()["phases"]
    res = api_client.post("/api/v1/settings/models/test", json={"connection": "Locale", "model": "mai-salvato"})
    assert res.status_code == 200, res.text
    assert KEY not in res.text
    data = res.json()
    assert data["ok"] is True and data["status_code"] == 200 and data["reply"] == "ok"
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert data["provider"] == "openai_compatible" and data["model"] == "mai-salvato"
    # chiamata minima: prompt di poche parole, pochi token di uscita, niente streaming
    sent = server.requests[-1]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == f"Bearer {KEY}"
    assert sent["json"]["max_tokens"] <= 16 and sent["json"]["stream"] is False
    assert len(sent["json"]["messages"]) == 1 and len(sent["json"]["messages"][0]["content"].split()) <= 5
    # la prova non salva nulla
    assert api_client.get("/api/v1/settings").json()["phases"] == before


def test_model_test_reports_provider_error(api_client, ws, llm):
    _, url = llm
    _connection(api_client, f"{url}/v1")
    data = api_client.post("/api/v1/settings/models/test", json={"connection": "Locale", "model": "inesistente"}).json()
    assert data["ok"] is False and data["status_code"] == 404
    assert "HTTP 404" in data["message"] and "does not exist" in data["message"]


def test_model_test_unreachable_and_timeout(api_client, ws, llm, monkeypatch):
    _connection(api_client, "http://127.0.0.1:9/v1", name="Chiusa")
    data = api_client.post("/api/v1/settings/models/test", json={"connection": "Chiusa", "model": "m"}).json()
    assert data["ok"] is False and data["message"].startswith("Server non raggiungibile")
    assert KEY not in data["message"]

    _, url = llm
    _connection(api_client, f"{url}/v1", name="Lenta")
    monkeypatch.setattr("rt.services.probes.MODEL_TIMEOUT_SECONDS", 0.5)
    data = api_client.post("/api/v1/settings/models/test", json={"connection": "Lenta", "model": "lento"}).json()
    assert data["ok"] is False and "Nessuna risposta entro" in data["message"]


def test_model_test_mock_and_validation(api_client, ws, monkeypatch):
    _connection(api_client, "http://127.0.0.1:9/v1")
    data = api_client.post("/api/v1/settings/models/test", json={"connection": "Locale", "model": "m", "mock": True}).json()
    assert data["ok"] is True and data["message"].startswith("Mock")
    monkeypatch.setenv("RT_API_MOCK", "1")
    assert api_client.post("/api/v1/settings/models/test", json={"connection": "Locale", "model": "m"}).json()["ok"] is True
    res = api_client.post("/api/v1/settings/models/test", json={"connection": "Nessuna", "model": "m"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_setting"
    assert api_client.post("/api/v1/settings/models/test", json={"connection": "Locale", "model": " "}).status_code == 422


def test_web_search_saved_and_read_by_add_images(api_client, api_token, ws):
    assert api_client.get("/api/v1/settings").json()["web_search"] == {"searxng_base_url": None}
    res = api_client.put("/api/v1/settings/web-search", json={"searxng_base_url": " http://localhost:8088/ "})
    assert res.status_code == 200, res.text
    assert fresh(api_token).get("/api/v1/settings").json()["web_search"]["searxng_base_url"] == "http://localhost:8088"
    # add_images legge l'URL da load_config(): nessun file da modificare a mano
    from rt.core.config import load_config
    assert load_config().searxng_base_url == "http://localhost:8088"
    assert api_client.put("/api/v1/settings/web-search", json={"searxng_base_url": "localhost"}).status_code == 422
    assert api_client.put("/api/v1/settings/web-search", json={"searxng_base_url": ""}).status_code == 200
    assert fresh(api_token).get("/api/v1/settings").json()["web_search"]["searxng_base_url"] is None


def test_web_search_test_counts_results(api_client, ws):
    server, url = fake_searxng_server(results=4)
    try:
        data = api_client.post("/api/v1/settings/web-search/test", json={"searxng_base_url": url}).json()
    finally:
        server.shutdown()
    assert data["ok"] is True and data["results"] == 4 and "4 immagini" in data["message"]


def test_web_search_test_explains_json_format(api_client, ws):
    server, url = fake_searxng_server(json_enabled=False)
    try:
        data = api_client.post("/api/v1/settings/web-search/test", json={"searxng_base_url": url}).json()
    finally:
        server.shutdown()
    assert data["ok"] is False and data["results"] == 0
    assert "formato JSON" in data["message"] and "search.formats" in data["message"]


def test_web_search_test_unreachable(api_client, ws):
    data = api_client.post("/api/v1/settings/web-search/test", json={"searxng_base_url": "http://127.0.0.1:9"}).json()
    assert data["ok"] is False and "Impossibile raggiungere SearXNG" in data["message"]


def test_add_images_web_search_surfaces_json_error(tmp_path):
    from types import SimpleNamespace
    from rt.pipeline.add_images import fetch_web_images
    server, url = fake_searxng_server(json_enabled=False)
    outline = SimpleNamespace(macro_sections=[SimpleNamespace(id="M1", title="Lipidi", units=[])])
    try:
        with pytest.raises(ValueError, match="search.formats"):
            fetch_web_images(str(tmp_path), outline, total_count=2, base_url=url)
    finally:
        server.shutdown()
