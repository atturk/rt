"""
tests/test_api_auth.py
RT4-E1: scheletro dell'API, errori uniformi e autenticazione a utente singolo.
"""
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from rt.api.app import create_app


@pytest.fixture
def anon(rt_db):
    return TestClient(create_app())


def test_health_is_public(anon):
    res = anon.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok" and res.json()["database"] is True


def test_without_token_401(anon):
    res = anon.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_wrong_token_401(anon, api_token):
    res = anon.get("/api/v1/auth/me", headers={"Authorization": "Bearer sbagliato"})
    assert res.status_code == 401


def test_right_token_200(anon, api_token):
    res = anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"})
    assert res.status_code == 200 and res.json() == {"actor": "api"}


def test_token_is_stored_hashed(rt_db, api_token):
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(rt_db) as s:
        record = SettingRepository(s).get("api.auth")
    assert api_token not in str(record) and len(record["token_hash"]) == 64


def test_reset_token_invalidates_previous(anon, rt_db, api_token):
    from rt.api.auth import reset_token
    new = reset_token(rt_db)
    assert anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"}).status_code == 401
    assert anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_ensure_token_only_first_time(rt_db):
    from rt.api.auth import ensure_token
    assert ensure_token(rt_db)
    assert ensure_token(rt_db) is None


def test_cookie_session_and_csrf(anon, api_token):
    assert anon.post("/api/v1/auth/session", json={"token": "no"}).status_code == 401
    res = anon.post("/api/v1/auth/session", json={"token": api_token})
    assert res.status_code == 200
    set_cookie = res.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("rt_session="))
    assert "HttpOnly" in session_cookie and "SameSite=strict" in session_cookie
    csrf = res.json()["csrf_token"]
    # GET con il solo cookie: ok
    assert anon.get("/api/v1/auth/me").status_code == 200
    # scrittura con cookie senza header CSRF: 403
    assert anon.delete("/api/v1/auth/session").status_code == 403
    # con l'header giusto: ok, e la sessione non vale più
    assert anon.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf}).status_code == 204
    anon.cookies.clear()
    assert anon.get("/api/v1/auth/me").status_code == 401


def test_errors_are_uniform(api_client):
    res = api_client.get("/api/v1/non-esiste")
    assert res.status_code == 404
    assert set(res.json()["error"]) == {"code", "message", "details"}


def test_cors_only_for_configured_origin(rt_db):
    client = TestClient(create_app(cors_origins=["http://localhost:5173"]))
    ok = client.options("/api/v1/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.options("/api/v1/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert other.headers.get("access-control-allow-origin") is None
    plain = TestClient(create_app(cors_origins=[]))
    assert plain.get("/api/v1/health", headers={"Origin": "http://localhost:5173"}).headers.get("access-control-allow-origin") is None


def test_no_auth_refused_off_loopback(rt_db):
    from rt.api.server import prepare
    messages = []
    assert prepare(no_auth=True, host="0.0.0.0", say=messages.append) is False


def test_prepare_shows_token_once(rt_db):
    from rt.api.server import prepare
    first, second = [], []
    assert prepare(say=first.append) and prepare(say=second.append)
    assert any("Token API" in m for m in first) and not any("Token API" in m for m in second)


def test_openapi_export_is_current():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, os.path.join(root, "scripts", "export_openapi.py"), "--check"],
                          capture_output=True, text=True, env={**os.environ, "RT_DATABASE_URL": "off"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
