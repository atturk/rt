"""
tests/test_api_spa.py
RT4-F1: link di accesso monouso e SPA servita dalla stessa origine dell'API.
"""
import sys
import pytest
from fastapi.testclient import TestClient

from rt.api.app import create_app


@pytest.fixture
def spa_dir(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app-123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return str(dist)


@pytest.fixture
def anon(rt_db, spa_dir):
    return TestClient(create_app(spa_dir=spa_dir))


def test_login_link_requires_auth(anon):
    assert anon.post("/api/v1/auth/login-link").status_code == 401


def test_login_link_opens_session_once(anon, api_token):
    res = anon.post("/api/v1/auth/login-link", headers={"Authorization": f"Bearer {api_token}"})
    assert res.status_code == 200
    url = res.json()["url"]
    assert "/login?code=" in url and res.json()["expires_in"] > 0
    path = url.split("testserver", 1)[1]

    fresh = TestClient(anon.app)
    first = fresh.get(path, follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/"
    assert fresh.cookies.get("rt_session") and fresh.cookies.get("rt_csrf")
    assert fresh.get("/api/v1/auth/me").json() == {"actor": "api"}

    other = TestClient(anon.app)
    second = other.get(path, follow_redirects=False)
    assert second.status_code == 303 and second.headers["location"] == "/login?error=link"
    assert other.get("/api/v1/auth/me").status_code == 401


def test_expired_code_is_rejected(anon, rt_db):
    from rt.api.auth import create_login_code
    code = create_login_code(rt_db, ttl_seconds=-1)
    res = anon.get(f"/login?code={code}", follow_redirects=False)
    assert res.headers["location"] == "/login?error=link"


def test_spa_routes_fall_back_to_index(anon):
    for path in ("/", "/lezioni/3", "/impostazioni", "/login"):
        res = anon.get(path)
        assert res.status_code == 200 and "id=root" in res.text, path
        assert res.headers["cache-control"] == "no-cache"


def test_spa_serves_build_files(anon):
    res = anon.get("/assets/app-123.js")
    assert res.status_code == 200 and "immutable" in res.headers["cache-control"]
    assert anon.get("/favicon.svg").text == "<svg/>"


def test_spa_does_not_shadow_api_or_escape_dist(anon, tmp_path):
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    res = anon.get("/api/v1/nonesiste")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    assert anon.get("/docs").status_code == 200
    assert anon.get("/openapi.json").json()["info"]["title"] == "RT API"
    assert "no" != anon.get("/..%2Fsecret.txt").text



def test_missing_build_message(rt_db, monkeypatch):
    import rt.api.spa as spa
    monkeypatch.setattr(spa, "find_spa_dir", lambda: None)
    res = TestClient(create_app()).get("/lezioni")
    assert res.status_code == 404 and res.json()["error"]["code"] == "spa_not_built"


def test_rt_web_starts_the_spa_by_default(monkeypatch):
    import rt.api.launcher as launcher
    from rt.cli import build_parser, cmd_web
    calls = []
    monkeypatch.setattr(launcher, "run_spa", lambda port, open_browser: calls.append((port, open_browser)) or 0)
    parser, _ = build_parser()
    for argv in (["web", "--no-browser"], ["web", "--spa", "--no-browser"]):  # --spa: vecchio alias
        cmd_web(parser.parse_args(argv))
    cmd_web(parser.parse_args(["web", "--port", "9000"]))
    assert calls == [(8765, False), (8765, False), (9000, True)]


def test_rt_web_legacy_starts_gradio_with_a_warning(monkeypatch, capsys):
    import types
    from rt.cli import build_parser, cmd_web
    seen = []
    monkeypatch.setitem(sys.modules, "rt.web.app", types.SimpleNamespace(main=seen.append))
    parser, _ = build_parser()
    cmd_web(parser.parse_args(["web", "--legacy", "--no-browser", "--lessons-root", "/x"]))
    assert seen == [["--port", "7860", "--lessons-root", "/x", "--no-browser"]]
    assert "deprecata" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="solo con --legacy"):
        cmd_web(parser.parse_args(["web", "--lessons-root", "/x"]))


def test_worker_command_runs_rt_worker():
    import os
    from rt.api.launcher import worker_command
    cmd = worker_command(["--once"])
    assert os.path.isfile(cmd[1]) and cmd[1].endswith(os.path.join("bin", "rt"))
    assert cmd[2:] == ["worker", "--once"]
