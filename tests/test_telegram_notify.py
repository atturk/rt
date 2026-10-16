"""
tests/test_telegram_notify.py
Notifiche Telegram nella chat personale: invio con il token e la chat salvati, registro delle
ultime notifiche, rilevamento della chat dopo /start e notifiche dei job del worker.
"""
from unittest.mock import MagicMock, patch

import pytest

from rt.telegram.client import TelegramAPIError, send_message
from rt.telegram.config import TelegramConfig
from tests.api_support import PRIVATE_CHAT, fake_telegram_server


@pytest.fixture
def bot(monkeypatch):
    server, base = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "555123")
    yield server
    server.shutdown()


def _sent_texts(server):
    return [body["text"] for method, body in server.sent if method == "sendMessage"]


def test_client_retries_once_on_429():
    cfg = TelegramConfig(bot_token="tok", chat_id="1")
    flood = MagicMock(status_code=429)
    flood.json.return_value = {"ok": False, "error_code": 429, "description": "Too Many Requests",
                               "parameters": {"retry_after": 0.05}}
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"ok": True, "result": {"message_id": 9}}
    with patch("requests.post", side_effect=[flood, ok]) as post, patch("time.sleep") as sleep:
        assert send_message(cfg, "ciao") == {"message_id": 9}
    assert post.call_count == 2
    sleep.assert_called_once_with(0.05)
    with patch("requests.post", side_effect=[flood, flood]), patch("time.sleep"):
        with pytest.raises(TelegramAPIError, match="Too Many Requests"):
            send_message(cfg, "ciao")


def test_notification_goes_to_the_personal_chat_and_is_logged(bot):
    from rt.telegram.notify import notify_build_completed
    from rt.telegram.notify_log import recent_notifications
    assert notify_build_completed("", {"reason": "rielaborata"}, lesson_title="Lipidi <1>") is True
    method, body = bot.sent[-1]
    assert method == "sendMessage" and body["chat_id"] == "555123"
    assert "Lezione pronta" in body["text"] and "Lipidi &lt;1&gt;" in body["text"]
    last = recent_notifications(1)[0]
    assert last["kind"] == "lezione_pronta" and last["ok"] is True and "<b>" not in last["text"]


def test_nothing_is_sent_when_disabled(bot, monkeypatch):
    from rt.telegram.notify import send_notification
    monkeypatch.setenv("RT_TELEGRAM_ENABLED", "0")
    assert send_notification("prova", "ciao") is False
    assert bot.calls == []


def test_send_errors_hide_the_token(monkeypatch):
    from rt.telegram.notify import send_notification
    from rt.telegram.notify_log import recent_notifications
    server, base = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "rifiutato-123")
    try:
        assert send_notification("prova", "ciao") is False
        with pytest.raises(RuntimeError) as exc:
            send_notification("prova", "ciao", raise_errors=True)
        assert "rifiutato-123" not in str(exc.value)
        assert recent_notifications(1)[0]["ok"] is False
    finally:
        server.shutdown()


def test_detect_private_chat_ignores_groups(bot):
    from rt.telegram.notify import detect_private_chat
    assert detect_private_chat("123:abc") == {"chat_id": str(PRIVATE_CHAT["id"]), "name": "Ada Rossi"}


def test_detect_private_chat_without_start(monkeypatch):
    from rt.telegram.notify import detect_private_chat
    server, base = fake_telegram_server(updates=[])
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    try:
        assert detect_private_chat("123:abc") is None
    finally:
        server.shutdown()


def test_job_notifier_messages(bot, monkeypatch):
    from rt.telegram.notify import TelegramJobNotifier
    notifier = TelegramJobNotifier()
    monkeypatch.setattr("rt.telegram.notify._outline_auto_approved", lambda: True)
    notifier.job_waiting(None, {"kind": "outline_approval", "payload": {}})
    assert _sent_texts(bot) == []  # la scaletta si approva da sola
    monkeypatch.setattr("rt.telegram.notify._outline_auto_approved", lambda: False)
    notifier.job_waiting(None, {"kind": "outline_approval", "payload": {}})
    notifier.job_waiting(None, {"kind": "science_issue", "payload": {"pending": [{}, {}, {}]}})
    notifier.job_waiting(None, {"kind": "setup_metadata", "payload": {}})
    notifier.job_failed(None, "audio illeggibile")
    texts = _sent_texts(bot)
    assert len(texts) == 3
    assert "Scaletta da approvare" in texts[0]
    assert "Issue da decidere</b> (3)" in texts[1]
    assert "Lavorazione non riuscita" in texts[2] and "audio illeggibile" in texts[2]


def test_worker_notifies_waiting_and_failed_jobs():
    from types import SimpleNamespace
    from rt.services.jobs import JobState
    from rt.services.worker import _notify_job_outcome, register_job_notifier, unregister_job_notifiers
    notifier = MagicMock()
    register_job_notifier(notifier)
    try:
        job = SimpleNamespace(id="j1", type="run_pipeline", lesson_path="/l")
        _notify_job_outcome(job, SimpleNamespace(state=JobState.WAITING_FOR_DECISION, lesson_path=None,
                                                 decision={"kind": "science_issue"}, error=None))
        notifier.job_waiting.assert_called_once_with("/l", {"kind": "science_issue"})
        _notify_job_outcome(job, SimpleNamespace(state=JobState.FAILED, lesson_path=None, decision=None, error="x"))
        notifier.job_failed.assert_called_once_with("/l", "x")
        other = SimpleNamespace(id="j2", type="unit_relevance", lesson_path="/l")
        _notify_job_outcome(other, SimpleNamespace(state=JobState.FAILED, lesson_path=None, decision=None, error="x"))
        assert notifier.job_failed.call_count == 1  # i job di servizio non disturbano
        notifier.job_waiting.side_effect = RuntimeError("rete")
        _notify_job_outcome(job, SimpleNamespace(state=JobState.WAITING_FOR_DECISION, lesson_path=None,
                                                 decision={"kind": "outline_approval"}, error=None))
    finally:
        unregister_job_notifiers()


def test_api_finds_the_chat_and_sends_a_test(bot, api_client, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace
    isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID")
    res = api_client.post("/api/v1/settings/telegram/chat", json={"bot_token": "123:abc"})
    assert res.status_code == 200, res.text
    assert res.json()["found"] is True and res.json()["name"] == "Ada Rossi"
    settings = api_client.get("/api/v1/settings").json()["telegram"]
    assert settings["chat_id_set"] is True and settings["bot_token_set"] is True
    res = api_client.post("/api/v1/settings/telegram/test")
    assert res.status_code == 200 and res.json()["ok"] is True, res.text
    assert _sent_texts(bot)[-1].startswith("👋")
    assert api_client.get("/api/v1/telegram/notifications").json()[0]["kind"] == "prova"
