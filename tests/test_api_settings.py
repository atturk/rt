"""
tests/test_api_settings.py
RT4-E4: impostazioni via API. Ogni scrittura si rilegge da un'app nuova; nessuna risposta
contiene il valore di un segreto.
"""
import json

import pytest
from fastapi.testclient import TestClient

from tests.api_support import workspace_with_example_config

KEY_A = "sk-or-v1-segreto-connessione-AAAA-0123456789"
KEY_B = "sk-or-v1-segreto-connessione-BBBB-9876543210"
BOT = "987654321:AAH-segreto-bot-telegram-zyxwvu"
STT = "stt-segreto-chiave-5555-abcdef"
SECRETS = (KEY_A, KEY_B, BOT, STT)
JOBS = ("outline", "rewrite", "review", "recall", "image_description",
        "enrichment_writer", "enrichment_visualizer", "enrichment_image")


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    for name in ("RT_STT_API_KEY",):
        monkeypatch.delenv(name, raising=False)
    root = workspace_with_example_config(tmp_path, monkeypatch)
    yield root
    import os
    os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
    os.environ.pop("RT_STT_API_KEY", None)


def fresh(api_token):
    from rt.api.app import create_app
    client = TestClient(create_app())
    client.headers["Authorization"] = f"Bearer {api_token}"
    return client


def _no_secret(res):
    text = res.text
    for secret in SECRETS:
        assert secret not in text, f"segreto nella risposta di {res.request.url}"
    return res


def test_settings_snapshot(api_client, ws):
    data = _no_secret(api_client.get("/api/v1/settings")).json()
    assert "lessons_root" not in data
    assert [p["job"] for p in data["phases"]] == list(JOBS)
    assert data["transcription"]["engine"] == "macparakeet"


def test_fresh_install_has_no_connections(api_client, ws, monkeypatch):
    """4.1.0b2: il general.yaml di esempio dichiarava una credenziale 'openrouter' senza chiave,
    e la configurazione guidata mostrava "Connessioni già configurate: openrouter" a ogni nuova
    installazione. Una nuova installazione deve partire senza connessioni né credenziali."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    data = api_client.get("/api/v1/settings").json()
    assert data["connections"] == []
    assert data["credentials"] == []
    assert all(p["connection"] is None for p in data["phases"])
    # Jev (credenziale di default "openrouter") resta inattivo senza rompere nulla:
    # registry pulito come in un processo appena avviato su questa configurazione.
    from rt.core.config import load_config
    from rt.llm.credentials import CredentialRegistry
    from rt.llm.jev_client import JevError, JevNoulQuestion, call_jev
    monkeypatch.setattr("rt.llm.jev_client.GLOBAL_CREDENTIALS", CredentialRegistry())
    with pytest.raises(JevError, match="non configurata"):
        call_jev("stato", {"q": JevNoulQuestion(instructions="?")}, job_name="test",
                 credential=load_config().jev.credential)


def test_jev_default_credential_falls_back_to_openrouter_connection(monkeypatch):
    """La credenziale Jev di default "openrouter" usa la prima connessione OpenRouter configurata."""
    from rt.core.config import JevConfig
    from rt.llm.credentials import CredentialRef, CredentialRegistry
    registry = CredentialRegistry()
    registry.register(CredentialRef(name="web_mia_1", provider="openrouter", env_var="RT_TEST_JEV_KEY"))
    monkeypatch.setenv("RT_TEST_JEV_KEY", KEY_A)
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *a, **k: None)
    assert registry.get_api_key(JevConfig().credential) == KEY_A


def test_setup_required_and_data_dir(api_client, api_token, ws, tmp_path):
    """Le lezioni stanno nel database: la cartella delle lezioni (anche configurata e sparita,
    come dopo un aggiornamento da 3.x) non blocca la SPA nella configurazione guidata."""
    import os
    data = api_client.get("/api/v1/settings").json()
    # Nuova installazione: nessuna connessione, quindi configurazione guidata.
    assert data["setup_required"] is True
    from rt.storage import fs
    assert data["data_dir"] == fs.data_dir() and os.path.isabs(data["data_dir"])
    api_client.post("/api/v1/settings/connections",
                    json={"name": "Studio", "provider": "openrouter", "api_keys": ["sk-or-v1-chiave-0123456789"]})
    import shutil
    shutil.rmtree(ws)
    assert fresh(api_token).get("/api/v1/settings").json()["setup_required"] is False
    # La cartella delle lezioni non si imposta più dall'API.
    assert api_client.put("/api/v1/settings/lessons-root", json={"path": ws}).status_code in (404, 405)


def test_setup_wizard_can_be_postponed(api_client, api_token, ws):
    """"Configura dopo" nella configurazione guidata: senza connessioni la SPA non ci torna più."""
    assert api_client.get("/api/v1/settings").json()["setup_required"] is True
    res = api_client.put("/api/v1/settings/notices", json={"notice": "setup_wizard", "dismissed": True})
    assert res.status_code == 200 and res.json()["setup_required"] is False
    assert fresh(api_token).get("/api/v1/settings").json()["setup_required"] is False


def test_connection_and_all_six_phases_persist(api_client, api_token, ws):
    res = api_client.post("/api/v1/settings/connections",
                          json={"name": "Studio", "provider": "openrouter", "api_keys": [KEY_A, KEY_B]})
    assert res.status_code == 201, res.text
    _no_secret(res)
    for i, job in enumerate(JOBS):
        res = api_client.put(f"/api/v1/settings/phases/{job}", json={"connection": "Studio", "model": f"model/{job}-{i}"})
        assert res.status_code == 200, res.text
    # nuovo client e nuova app: il valore arriva dal backend, non dalla pagina
    data = _no_secret(fresh(api_token).get("/api/v1/settings")).json()
    assigned = {p["job"]: (p["connection"], p["model"]) for p in data["phases"]}
    assert assigned == {job: ("Studio", f"model/{job}-{i}") for i, job in enumerate(JOBS)}
    conn = next(c for c in data["connections"] if c["name"] == "Studio")
    assert [c["set"] for c in conn["credentials"]] == [True, True]
    from rt.core.config import load_config
    assert load_config().jobs["review"].primary.model == "model/review-2"


def test_phase_validation_errors_are_422(api_client, ws):
    res = api_client.put("/api/v1/settings/phases/outline", json={"connection": "Inesistente", "model": "x"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_setting"
    res = api_client.put("/api/v1/settings/phases/nonfase", json={"connection": "x", "model": "x"})
    assert res.status_code == 422


def test_route_roundtrip(api_client, api_token, ws):
    api_client.post("/api/v1/settings/connections", json={"name": "Solo", "provider": "openrouter", "api_keys": [KEY_A]})
    cred = api_client.get("/api/v1/settings").json()["connections"][-1]["credentials"][0]["name"]
    res = api_client.put("/api/v1/settings/routes/rewrite/secondary",
                         json={"provider": "openrouter", "credential": cred, "model": "second/model"})
    assert res.status_code == 200, res.text
    got = fresh(api_token).get("/api/v1/settings/routes/rewrite/secondary").json()
    assert (got["credential"], got["model"]) == (cred, "second/model")


def test_transcription_telegram_pricing_persist(api_client, api_token, ws, tmp_path):
    res = api_client.put("/api/v1/settings/transcription",
                         json={"engine": "custom", "base_url": "http://127.0.0.1:9000/v1", "model": "whisper", "api_key": STT})
    assert res.status_code == 200, res.text
    res = api_client.put("/api/v1/settings/telegram",
                         json={"bot_token": BOT, "chat_id": "-100777", "topics": {"biochimica": 12}, "misc_topic_id": 3})
    assert res.status_code == 200, res.text
    pricing = {"openrouter": {"model/x": {"input_per_million": 1.5, "output_per_million": 3.0}}}
    assert api_client.put("/api/v1/settings/pricing", json=pricing).status_code == 200

    data = _no_secret(fresh(api_token).get("/api/v1/settings")).json()
    assert data["transcription"] == {"engine": "custom", "base_url": "http://127.0.0.1:9000/v1",
                                     "model": "whisper", "api_key_set": True}
    assert data["telegram"]["bot_token_set"] is True and data["telegram"]["chat_id_preview"] == "-1…77"
    assert data["telegram"]["topics"] == {"BIOCHIMICA": 12} and data["telegram"]["misc_topic_id"] == 3
    assert data["pricing"] == pricing
    bad = api_client.put("/api/v1/settings/pricing", json={"openrouter": {"m": {"input_per_million": "tanto"}}})
    assert bad.status_code == 422


def test_put_secret_env_and_store(api_client, ws, tmp_path, monkeypatch):
    from rt.security import secrets as sec
    from rt.services import secrets_service
    api_client.post("/api/v1/settings/connections", json={"name": "Solo", "provider": "openrouter", "api_keys": [KEY_A]})
    env_var = api_client.get("/api/v1/settings").json()["credentials"][-1]["env_var"]
    assert api_client.put("/api/v1/secrets/NON_DICHIARATO", json={"value": "x" * 12}).status_code == 404
    res = _no_secret(api_client.put(f"/api/v1/secrets/{env_var}", json={"value": KEY_B}))
    assert res.json() == {"name": env_var, "set": True, "stored_in": "env"}

    monkeypatch.setenv("RT_SECRETS_FILE", str(tmp_path / "work" / "config" / "secrets.enc"))
    monkeypatch.setenv("RT_MASTER_KEY", sec.generate_master_key())
    sec._reset_for_tests()
    secrets_service.init_store()
    res = _no_secret(api_client.put("/api/v1/secrets/RT_STT_API_KEY", json={"value": STT}))
    assert res.json()["stored_in"] == "store"
    assert secrets_service.store().get("RT_STT_API_KEY") == STT
    sec._reset_for_tests()


def test_no_json_response_contains_a_secret(api_client, ws):
    api_client.post("/api/v1/settings/connections", json={"name": "Studio", "provider": "openrouter", "api_keys": [KEY_A, KEY_B]})
    api_client.put("/api/v1/settings/transcription", json={"engine": "macparakeet", "api_key": STT})
    api_client.put("/api/v1/settings/telegram", json={"bot_token": BOT, "chat_id": "-1001"})
    schema = api_client.get("/openapi.json").json()
    for path, ops in schema["paths"].items():
        if "get" in ops and "{" not in path:
            res = api_client.get(path)
            if res.headers.get("content-type", "").startswith("application/json"):
                _no_secret(res)
                json.loads(res.text)


def test_telegram_daemon_status_and_guard(api_client, ws, monkeypatch):
    import rt.telegram.daemon_status as ds
    monkeypatch.setattr(ds, "DEFAULT_PID_PATH", str(ws + "/tg.pid"))
    assert api_client.get("/api/v1/telegram/daemon").json() == {"running": False, "pid": None}
    # senza token e chat configurati non parte nulla
    res = api_client.post("/api/v1/telegram/daemon/start")
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_not_configured"
    assert api_client.post("/api/v1/telegram/daemon/stop").json()["running"] is False
