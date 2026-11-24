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


def test_outline_notification_suppressed_in_auto_and_timer_modes(bot, monkeypatch):
    from rt.core import config as config_mod
    from rt.telegram.notify import TelegramJobNotifier, _outline_auto_approved
    real_load = config_mod.load_config
    notifier = TelegramJobNotifier()
    for mode, expected_auto in (("auto", True), ("timer", True), ("manual", False)):
        def patched(*args, _m=mode, **kwargs):
            cfg = real_load(*args, **kwargs)
            cfg.ui.outline_mode = _m
            return cfg
        monkeypatch.setattr(config_mod, "load_config", patched)
        assert _outline_auto_approved() is expected_auto
        notifier.job_waiting(None, {"kind": "outline_approval", "payload": {}})
    assert len(_sent_texts(bot)) == 1
    assert "Scaletta da approvare" in _sent_texts(bot)[0]


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


def test_disabled_notification_event_is_not_sent(bot, monkeypatch):
    from rt.core import config as config_mod
    from rt.telegram.notify import notify_build_completed, notify_decision_needed, notify_job_failed, notify_review_completed
    real_load = config_mod.load_config

    def patched(*args, **kwargs):
        cfg = real_load(*args, **kwargs)
        cfg.telegram.notify["lezione_pronta"] = False
        cfg.telegram.notify["verifica_pronta"] = False
        cfg.telegram.notify["errore"] = False
        cfg.telegram.notify["scaletta_da_approvare"] = False
        cfg.telegram.notify["issue_da_decidere"] = True
        return cfg

    monkeypatch.setattr(config_mod, "load_config", patched)
    assert notify_build_completed("", {}, "Titolo") is False
    assert notify_review_completed("", 2, "Titolo") is False
    assert notify_job_failed(None, "Titolo", "boom") is False
    assert notify_decision_needed("outline_approval", None, "Titolo") is False
    assert _sent_texts(bot) == []
    assert notify_decision_needed("science_issue", None, "Titolo", count=2) is True
    assert len(_sent_texts(bot)) == 1
    from rt.telegram.notify_log import recent_notifications
    assert recent_notifications(1)[0]["kind"] == "issue_da_decidere"


def test_verifica_pronta_once_per_manual_job_and_no_duplicate_with_pipeline(bot, api_client, tmp_path, monkeypatch, rt_db):
    from rt.cli_jobs import prepare_worker_process
    from rt.core import config as config_mod
    from rt.services.jobs import DbJobQueue
    from rt.services.pipeline_service import unregister_build_notifiers
    from rt.services.worker import Worker, unregister_job_notifiers
    from rt.telegram.notify_log import recent_notifications
    from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline

    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=False, auto_accept=True)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]

    prepare_worker_process(DbJobQueue(rt_db))
    worker = Worker(DbJobQueue(rt_db), worker_id="tg-worker")
    try:
        # 1. Job manuale review_unit su più unità: UNA sola notifica verifica_pronta
        bot.sent.clear()
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs",
                              json={"type": "run_phase", "phase": "review", "units": ["1.1", "9.9"], "mock": True})
        assert res.status_code == 202, res.text
        while worker.run_once() is not None:
            pass
        texts = _sent_texts(bot)
        assert len(texts) == 1
        assert "Verifica completata" in texts[0]
        assert "issue da decidere in RT" in texts[0]
        assert recent_notifications(1)[0]["kind"] == "verifica_pronta"

        # 2. Job review_part su più parti: UNA sola notifica verifica_pronta
        bot.sent.clear()
        from rt.pipeline.anchors import make_anchor
        from rt.pipeline.rewrite import load_draft
        unit = load_draft(lesson_dir).units[0]
        anchor = make_anchor(unit.content, 0, min(40, len(unit.content))).model_dump()
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs",
                              json={"type": "review_part",
                                    "parts": [{"unit_id": unit.unit_id, "anchor": anchor}],
                                    "mock": True})
        assert res.status_code == 202, res.text
        while worker.run_once() is not None:
            pass
        texts = _sent_texts(bot)
        assert len(texts) == 1
        assert "Verifica completata" in texts[0]

        # 3. Pipeline con review e issue pendenti: parte solo verifica_pronta, NON issue_da_decidere
        bot.sent.clear()
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs",
                              json={"type": "run_pipeline", "force": True, "with_review": True, "auto_accept": False, "mock": True})
        assert res.status_code == 202, res.text
        while worker.run_once() is not None:
            pass
        texts = _sent_texts(bot)
        assert len(texts) == 1
        assert "Verifica completata" in texts[0]
        assert not any("Issue da decidere" in t for t in texts)

        # 4. Se verifica_pronta è spenta ma issue_da_decidere è accesa, parte issue_da_decidere
        bot.sent.clear()
        real_load = config_mod.load_config

        def patched(*args, **kwargs):
            cfg = real_load(*args, **kwargs)
            cfg.telegram.notify["verifica_pronta"] = False
            return cfg

        monkeypatch.setattr(config_mod, "load_config", patched)
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs",
                              json={"type": "run_pipeline", "force": True, "with_review": True, "auto_accept": False, "mock": True})
        assert res.status_code == 202, res.text
        while worker.run_once() is not None:
            pass
        texts = _sent_texts(bot)
        assert len(texts) == 1
        assert "Issue da decidere" in texts[0]
    finally:
        unregister_build_notifiers()
        unregister_job_notifiers()


def test_api_clear_notifications_and_save_notify_prefs(bot, api_client, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace
    isolated_workspace(tmp_path, monkeypatch)
    res = api_client.put("/api/v1/settings/telegram/notify", json={"notify": {"errore": False, "verifica_pronta": True}})
    assert res.status_code == 200, res.text
    prefs = res.json()["telegram"]["notify"]
    assert prefs["errore"] is False and prefs["verifica_pronta"] is True and prefs["lezione_pronta"] is True

    api_client.post("/api/v1/settings/telegram/test")
    assert len(api_client.get("/api/v1/telegram/notifications").json()) == 1
    cleared = api_client.delete("/api/v1/telegram/notifications")
    assert cleared.status_code == 200 and cleared.json()["cleared"] == 1
    assert api_client.get("/api/v1/telegram/notifications").json() == []


def test_worker_reads_updated_chat_id_from_env_file(tmp_path, monkeypatch):
    from rt.core import config as config_mod
    from rt.telegram.notify import send_notification
    from tests.api_support import isolated_workspace

    isolated_workspace(tmp_path, monkeypatch)
    server, base = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID", raising=False)
    config_mod._DOTENV_INJECTED.clear()
    env_path = tmp_path / "work" / ".env"
    try:
        env_path.write_text('RT_TELEGRAM_CHAT_ID="111"\n', encoding="utf-8")
        assert send_notification("prova", "uno") is True
        assert server.sent[-1][1]["chat_id"] == "111"

        env_path.write_text('RT_TELEGRAM_CHAT_ID="222"\n', encoding="utf-8")
        assert send_notification("prova", "due") is True
        assert server.sent[-1][1]["chat_id"] == "222"
    finally:
        config_mod._DOTENV_INJECTED.clear()
        server.shutdown()


def test_client_429_caps_retry_after_at_30_seconds():
    cfg = TelegramConfig(bot_token="tok", chat_id="1")
    flood = MagicMock(status_code=429)
    flood.json.return_value = {"ok": False, "error_code": 429, "description": "Too Many Requests",
                               "parameters": {"retry_after": 120}}
    with patch("requests.post", side_effect=[flood, flood]) as post, patch("time.sleep") as sleep:
        with pytest.raises(TelegramAPIError, match="Too Many Requests"):
            send_message(cfg, "ciao")
    assert post.call_count == 2
    sleep.assert_called_once_with(30.0)


def test_failed_prep_job_notifies_with_lesson_materia_and_no_exception_prefix(bot, tmp_path, monkeypatch, rt_db):
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import NOTIFY_FAILED_TYPES, Worker, register_job_notifier, unregister_job_notifiers
    from rt.telegram.notify import TelegramJobNotifier
    from tests.api_support import isolated_workspace

    assert {"ingest_sources", "ingest_notes", "review_unit", "review_part"} <= NOTIFY_FAILED_TYPES
    isolated_workspace(tmp_path, monkeypatch)

    def fail_prep(job, ctx):
        raise ValueError("Formato audio non supportato")

    queue = DbJobQueue(rt_db)
    worker = Worker(queue, handlers={"ingest_audio": fail_prep}, stt="macparakeet")
    register_job_notifier(TelegramJobNotifier())
    try:
        queue.enqueue("ingest_audio", None, {
            "inputs": ["/tmp/lezione_cuore.m4a"],
            "options": {"date": "2026-11-24", "materia": "ANATOMIA"},
        })
        job = worker.run_once()
        assert job.state == "failed"
        texts = _sent_texts(bot)
        assert len(texts) == 1
        assert "lezione_cuore.m4a" in texts[0]
        assert "2026-11-24 · ANATOMIA" in texts[0]
        assert "Formato audio non supportato" in texts[0]
        assert "ValueError" not in texts[0]
    finally:
        unregister_job_notifiers()
