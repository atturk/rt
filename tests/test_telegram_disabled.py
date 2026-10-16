"""
tests/test_telegram_disabled.py
Notifiche Telegram spente di predefinito: niente invii e messaggio di prova rifiutato con
telegram_disabled; si riaccendono dalle impostazioni (o con RT_TELEGRAM_ENABLED).
"""
import pytest

from tests.api_support import isolated_workspace, workspace_with_example_config


@pytest.fixture
def off(monkeypatch):
    # il conftest le accende per i test delle notifiche: qui vale il predefinito
    monkeypatch.delenv("RT_TELEGRAM_ENABLED", raising=False)


def test_default_is_off_and_nothing_goes_to_telegram(off, tmp_path, monkeypatch):
    from rt.core.config import RTConfig, telegram_enabled
    from rt.telegram.config import TelegramConfigError, load_telegram_config
    from rt.telegram.notify import send_notification
    workspace_with_example_config(tmp_path, monkeypatch)
    assert RTConfig().telegram.enabled is False
    assert telegram_enabled() is False
    with pytest.raises(TelegramConfigError, match="spente"):
        load_telegram_config()
    assert send_notification("prova", "ciao") is False


def test_old_config_keys_are_ignored():
    from rt.core.config import RTConfig
    cfg = RTConfig.model_validate({"telegram": {"enabled": True, "default_channel": "telegram",
                                                "topics": {"BIOCHIMICA": 5}, "misc_topic_id": 9}})
    assert cfg.telegram.enabled is True
    assert not hasattr(cfg.telegram, "topics")


def test_env_forces_it(off, tmp_path, monkeypatch):
    from rt.core.config import telegram_enabled
    workspace_with_example_config(tmp_path, monkeypatch)
    monkeypatch.setenv("RT_TELEGRAM_ENABLED", "1")
    assert telegram_enabled() is True
    monkeypatch.setenv("RT_TELEGRAM_ENABLED", "0")
    assert telegram_enabled() is False


def test_api_refuses_the_test_message_until_enabled(off, api_client, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    assert api_client.get("/api/v1/settings").json()["telegram"]["enabled"] is False
    res = api_client.post("/api/v1/settings/telegram/test")
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_disabled", res.text

    res = api_client.put("/api/v1/settings/telegram/enabled", json={"enabled": True})
    assert res.status_code == 200 and res.json()["telegram"]["enabled"] is True
    res = api_client.post("/api/v1/settings/telegram/test")
    assert res.status_code == 200, res.text

    res = api_client.put("/api/v1/settings/telegram/enabled", json={"enabled": False})
    assert res.json()["telegram"]["enabled"] is False
