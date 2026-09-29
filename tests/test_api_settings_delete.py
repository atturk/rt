"""
tests/test_api_settings_delete.py
Beta 4.1.0b3: eliminazione di connessioni e chiavi dalle Impostazioni, parità con
'rt secrets unset', e /system/info per la scheda Info. Nessuna risposta contiene un segreto.
"""
import os

import pytest
import yaml

from tests.api_support import workspace_with_example_config
from tests.test_api_settings import fresh

KEY_A = "sk-or-v1-segreto-da-eliminare-AAAA-0123456789"
KEY_B = "sk-or-v1-segreto-da-eliminare-BBBB-9876543210"


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    monkeypatch.delenv("RT_STT_API_KEY", raising=False)
    root = workspace_with_example_config(tmp_path, monkeypatch)
    yield root
    os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
    os.environ.pop("RT_STT_API_KEY", None)


def _general():
    from rt.services.config_service import general_config_path
    with open(general_config_path(), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _env_text():
    from rt.services.config_service import env_path
    path = env_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _connection(api_client, name="Studio", keys=(KEY_A, KEY_B)):
    res = api_client.post("/api/v1/settings/connections", json={"name": name, "provider": "openrouter", "api_keys": list(keys)})
    assert res.status_code == 201, res.text
    conn = next(c for c in res.json()["connections"] if c["name"] == name)
    env_vars = {c["name"]: c["env_var"] for c in res.json()["credentials"]}
    return [env_vars[c["name"]] for c in conn["credentials"]]


def test_delete_connection_removes_entry_credentials_and_keys(api_client, api_token, ws):
    env_vars = _connection(api_client)
    api_client.post("/api/v1/settings/connections/Studio/models", json={"model": "openai/gpt-4.1"})
    assert all(os.environ.get(v) for v in env_vars)

    res = api_client.delete("/api/v1/settings/connections/Studio")
    assert res.status_code == 200, res.text
    assert KEY_A not in res.text and KEY_B not in res.text
    assert "Studio" not in [c["name"] for c in res.json()["connections"]]
    # riletto da un'app nuova e dal disco
    data = fresh(api_token).get("/api/v1/settings").json()
    assert "Studio" not in [c["name"] for c in data["connections"]]
    general = _general()
    assert all(c.get("name") != "Studio" for c in general.get("connections") or [])
    assert all(c.get("env_var") not in env_vars for c in general.get("credentials") or [])
    assert [c["name"] for c in general["credentials"]] == ["openrouter"]  # le altre restano
    assert KEY_A not in _env_text() and KEY_B not in _env_text()
    assert not any(v in os.environ for v in env_vars)

    assert api_client.delete("/api/v1/settings/connections/Studio").status_code == 404


def test_delete_connection_in_use_is_409_with_the_settings_that_use_it(api_client, ws):
    _connection(api_client)
    assert api_client.put("/api/v1/settings/phases/review", json={"connection": "Studio", "model": "m/review"}).status_code == 200
    res = api_client.delete("/api/v1/settings/connections/Studio")
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "connection_in_use"
    assert err["details"]["usages"] == ["Review (primaria)"]
    assert "Review" in err["message"]
    assert "Studio" in [c["name"] for c in api_client.get("/api/v1/settings").json()["connections"]]


def test_delete_connection_used_by_jev_is_409(api_client, ws):
    from rt.services import config_service
    from rt.services.config_service import general_config_path
    data = _general()
    data["jev"] = {**data.get("jev", {}), "enabled": False, "relevance_mode": "active",
                   "relevance_model": "typesafe/jev-1.13", "credential": "openrouter"}
    config_service.write_yaml_atomic(general_config_path(), data)
    res = api_client.delete("/api/v1/settings/connections/openrouter")
    assert res.status_code == 409
    assert res.json()["error"]["details"]["usages"] == ["Decisioni JEV"]
    data["jev"]["relevance_mode"] = "disabled"
    config_service.write_yaml_atomic(general_config_path(), data)
    assert api_client.delete("/api/v1/settings/connections/openrouter").status_code == 200
    assert not _general().get("credentials")


def test_delete_secret_env_and_idempotent(api_client, ws):
    env_var = _connection(api_client, "Solo", (KEY_A,))[0]
    assert api_client.delete("/api/v1/secrets/NON_DICHIARATO").status_code == 404
    res = api_client.delete(f"/api/v1/secrets/{env_var}")
    assert res.status_code == 200
    assert res.json() == {"name": env_var, "set": False, "removed_from": ["env"]}
    assert KEY_A not in _env_text() and env_var not in os.environ
    creds = api_client.get("/api/v1/settings").json()["credentials"]
    assert next(c for c in creds if c["env_var"] == env_var)["set"] is False  # dichiarata, ma mancante
    assert api_client.delete(f"/api/v1/secrets/{env_var}").json()["removed_from"] == []


def test_delete_secret_from_store_like_cli_unset(api_client, ws, tmp_path, monkeypatch):
    from rt.cli import main
    from rt.security import secrets as sec
    from rt.services import secrets_service
    monkeypatch.setenv("RT_SECRETS_FILE", str(tmp_path / "secrets.enc"))
    monkeypatch.setenv("RT_MASTER_KEY", sec.generate_master_key())
    sec._reset_for_tests()
    secrets_service.init_store()
    try:
        assert api_client.put("/api/v1/secrets/RT_STT_API_KEY", json={"value": "stt-chiave-web-123456"}).json()["stored_in"] == "store"
        res = api_client.delete("/api/v1/secrets/RT_STT_API_KEY")
        assert res.json()["removed_from"] == ["store"]
        assert secrets_service.store().get("RT_STT_API_KEY") is None
        assert "RT_STT_API_KEY" not in os.environ
        assert api_client.get("/api/v1/settings").json()["transcription"]["api_key_set"] is False

        # stessa operazione da terminale: archivio e .env
        from rt.services import config_service
        secrets_service.set_secret("RT_STT_API_KEY", "stt-chiave-cli-654321")
        config_service.set_env_var(config_service.env_path(), "RT_STT_API_KEY", "stt-chiave-env-000000")
        try:
            main(["secrets", "unset", "RT_STT_API_KEY"])
        except SystemExit as exc:
            assert not exc.code
        assert secrets_service.store().get("RT_STT_API_KEY") is None
        assert "RT_STT_API_KEY" not in _env_text()
    finally:
        sec._reset_for_tests()


def test_system_info(api_client, ws, monkeypatch, tmp_path):
    from rt.core import version
    monkeypatch.setattr(version, "get_update_channel", lambda: "beta")
    res = api_client.get("/api/v1/system/info")
    assert res.status_code == 200
    data = res.json()
    from rt.core.config import _default_project_root
    assert data["version"] == version.get_current_version(_default_project_root())
    assert data["update_channel"] == "beta"
    assert data["prerelease"] == version.is_prerelease(data["version"])
    assert os.path.isabs(data["data_dir"]) and data["python_version"].count(".") == 2
