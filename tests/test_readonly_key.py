"""Test per la gestione della chiave di sola lettura (AP1) e l'endpoint /settings/readonly-key."""
import os
import pytest
from fastapi.testclient import TestClient

from rt.api.app import create_app
from rt.api.readonly_auth import get_readonly_key


LOCAL = ("127.0.0.1", 50000)


def test_readonly_key_api_lifecycle(api_client, tmp_path, monkeypatch):
    """Creata la chiave, GET restituisce key uguale al token e base_url con la porta configurata;

    dopo DELETE key è null e il segreto non c'è più; con il token di sola lettura GET
    /settings/readonly-key è rifiutato.
    """
    # 1. Creazione chiave
    res_post = api_client.post("/api/v1/settings/readonly-key")
    assert res_post.status_code == 200, res_post.text
    created = res_post.json()
    token = created["key"]
    assert token.startswith("rt_ro_")

    # Verifica che il segreto sia memorizzato
    assert get_readonly_key() == token

    # 2. GET con token principale restituisce key e base_url
    res_get = api_client.get("/api/v1/settings/readonly-key")
    assert res_get.status_code == 200
    info = res_get.json()
    assert info["configured"] is True
    assert info["key"] == token
    assert info["base_url"].startswith("http://127.0.0.1:")
    assert info["base_url"].endswith("/api/v1/readonly")

    # 3. GET /settings/readonly-key con il token di sola lettura deve essere rifiutato (401)
    unauthorized_client = TestClient(create_app(), client=LOCAL)
    res_ro = unauthorized_client.get(
        "/api/v1/settings/readonly-key",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_ro.status_code == 401
    assert res_ro.json()["error"]["code"] == "unauthorized"

    # 4. DELETE revoca la chiave e cancella il segreto
    res_del = api_client.delete("/api/v1/settings/readonly-key")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # Dopo DELETE: key è null e il segreto non c'è più
    assert get_readonly_key() is None
    res_get_after = api_client.get("/api/v1/settings/readonly-key")
    assert res_get_after.status_code == 200
    info_after = res_get_after.json()
    assert info_after["configured"] is False
    assert info_after["key"] is None


def test_legacy_key_without_secret_returns_null_key(api_client, rt_db):
    """Una chiave creata prima della 4.3.8 (senza segreto) ha configured=True ma key=null."""
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    from rt.api.readonly_auth import READONLY_AUTH_KEY

    # Pulisce eventuale segreto residuo
    os.environ.pop("RT_READONLY_KEY", None)

    # Scrive solo hash e preview nel DB, simulando una chiave creata prima della 4.3.8
    with session_scope(rt_db) as session:
        SettingRepository(session).set(
            READONLY_AUTH_KEY,
            {
                "salt": "fakesalt12345678",
                "token_hash": "fakehash",
                "created_at": "2026-10-01T12:00:00",
                "key_preview": "rt_ro_le…gacy",
            },
        )

    res = api_client.get("/api/v1/settings/readonly-key")
    assert res.status_code == 200
    info = res.json()
    assert info["configured"] is True
    assert info["key_preview"] == "rt_ro_le…gacy"
    assert info["key"] is None
