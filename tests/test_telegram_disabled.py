"""
tests/test_telegram_disabled.py
Telegram spento di predefinito: niente invii, decisioni nel terminale, azioni dell'API
rifiutate con telegram_disabled; si riaccende dalle impostazioni (o con RT_TELEGRAM_ENABLED).
"""
import pytest

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline, workspace_with_example_config


@pytest.fixture
def off(monkeypatch):
    # il conftest lo accende per i test del bot: qui vale il predefinito
    monkeypatch.delenv("RT_TELEGRAM_ENABLED", raising=False)


def test_default_is_off_and_nothing_goes_to_telegram(off, tmp_path, monkeypatch):
    from rt.core.config import RTConfig, telegram_enabled
    from rt.telegram.config import TelegramConfigError, load_telegram_config
    workspace_with_example_config(tmp_path, monkeypatch)
    assert RTConfig().telegram.enabled is False
    assert telegram_enabled() is False
    with pytest.raises(TelegramConfigError, match="disattivato"):
        load_telegram_config()
    # anche con default_channel telegram le decisioni restano nel terminale
    cfg = RTConfig.model_validate({"telegram": {"default_channel": "telegram"}})
    assert cfg.telegram.channel == "terminal"
    cfg.telegram.enabled = True
    assert cfg.telegram.channel == "telegram"


def test_env_forces_it(off, tmp_path, monkeypatch):
    from rt.core.config import telegram_enabled
    workspace_with_example_config(tmp_path, monkeypatch)
    monkeypatch.setenv("RT_TELEGRAM_ENABLED", "1")
    assert telegram_enabled() is True
    monkeypatch.setenv("RT_TELEGRAM_ENABLED", "0")
    assert telegram_enabled() is False


def test_api_refuses_telegram_actions_until_enabled(off, api_client, tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    run_mock_pipeline(make_lesson(root))
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]

    settings = api_client.get("/api/v1/settings").json()
    assert settings["telegram"]["enabled"] is False
    assert api_client.get("/api/v1/recall/telegram").json()["enabled"] is False
    for method, path, body in [
        ("post", f"/api/v1/lessons/{lesson_id}/recall/telegram/start", {"qtype": "quiz"}),
        ("post", "/api/v1/telegram/daemon/start", None),
        ("post", "/api/v1/settings/telegram/listen-topics", None),
    ]:
        res = getattr(api_client, method)(path, json=body) if body is not None else getattr(api_client, method)(path)
        assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_disabled", (path, res.text)

    res = api_client.put("/api/v1/settings/telegram/enabled", json={"enabled": True})
    assert res.status_code == 200 and res.json()["telegram"]["enabled"] is True
    assert api_client.get("/api/v1/recall/telegram").json()["enabled"] is True
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/telegram/start", json={"qtype": "quiz"})
    assert res.json()["error"]["code"] != "telegram_disabled"

    res = api_client.put("/api/v1/settings/telegram/enabled", json={"enabled": False})
    assert res.json()["telegram"]["enabled"] is False
