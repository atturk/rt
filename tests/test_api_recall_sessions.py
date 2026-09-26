"""
tests/test_api_recall_sessions.py
RT4-FA7: sessioni di recall. "Termina sessione" nella web app (riepilogo salvato), avvio e
interruzione su Telegram dall'app tramite il bot (comandi in telegram_commands eseguiti dal
daemon, Bot API finta), registro condiviso delle sessioni aggiornato dal daemon.
"""
import os

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import fake_telegram_server, isolated_workspace, make_lesson, run_mock_pipeline

TOPIC = 12


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    # il topic della materia della lezione di prova (BIOCHIMICA)
    with open(os.path.join("config", "general.yaml"), "a", encoding="utf-8") as f:
        f.write(f"  topics:\n    BIOCHIMICA: {TOPIC}\n")
    return root


@pytest.fixture
def lesson_id(api_client, ws, rt_db):
    run_mock_pipeline(make_lesson(ws))
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={"mock": True}).status_code == 202
    worker = Worker(DbJobQueue(rt_db), worker_id="w", mock=True)
    while worker.run_once() is not None:
        pass
    return lid


@pytest.fixture
def bot(monkeypatch):
    """Bot configurato e in esecuzione, con la Bot API finta."""
    server, url = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", url)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:finto")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "-100")
    monkeypatch.setattr("rt.telegram.daemon_status.is_daemon_running", lambda *a: True)
    yield server
    server.shutdown()


def _state(client, lid):
    res = client.get(f"/api/v1/lessons/{lid}/recall/session")
    assert res.status_code == 200, res.text
    return res.json()


def test_web_session_end_saves_summary(api_client, lesson_id):
    lid = lesson_id
    assert _state(api_client, lid)["web"] is None
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/session/end").status_code == 404

    quiz = api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"}).json()
    history = api_client.get(f"/api/v1/lessons/{lid}/recall/history").json()
    correct = next(q for q in history["questions"] if q["id"] == quiz["id"])
    # la soluzione non si vede prima di rispondere: si ricava dal quiz del bank
    from rt.pipeline.recall import load_recall_bank
    from rt.services.lesson_service import resolve_lesson_dir
    bank = load_recall_bank(resolve_lesson_dir(lid))
    right = next(q for q in bank.questions if q.id == correct["id"]).correct_index
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/answer",
                           json={"question_id": quiz["id"], "choice": right}).json()["correct"] is True
    api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "mirata"})

    web = _state(api_client, lid)["web"]
    assert web["state"] == "active" and web["channel"] == "web" and web["questions"] == 2

    res = api_client.post(f"/api/v1/lessons/{lid}/recall/session/end")
    assert res.status_code == 200, res.text
    ended = res.json()
    assert ended["state"] == "ended" and ended["ended_by"] == "web" and ended["ended_at"]
    assert ended["summary"] == {"questions": 2, "answered": 1, "quiz_answered": 1, "correct": 1}

    # stato salvato: la sessione resta chiusa e il riepilogo si rilegge
    state = _state(api_client, lid)
    assert state["web"] is None and state["last"]["id"] == ended["id"]
    assert state["last"]["summary"]["correct"] == 1
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/session/end").status_code == 404
    from rt.services.recall_service import load_recall_session_state
    assert load_recall_session_state(resolve_lesson_dir(lid))["current_question_id"] is None

    # una nuova domanda apre una nuova sessione e nasconde il riepilogo precedente
    api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"})
    state = _state(api_client, lid)
    assert state["web"]["id"] != ended["id"] and state["web"]["questions"] == 1 and state["last"] is None


def test_telegram_start_requires_configured_running_bot(api_client, lesson_id, monkeypatch):
    lid = lesson_id
    monkeypatch.delenv("RT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID", raising=False)
    status = api_client.get("/api/v1/recall/telegram").json()
    assert status == {"configured": False, "running": False, "sessions": []}
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_not_configured"

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:finto")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "-100")
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_not_running"
    assert _state(api_client, lid)["command"] is None


def test_telegram_start_and_interrupt_from_app(api_client, lesson_id, bot):
    from rt.core.config import load_config
    from rt.telegram import recall_preferences, session as tg_session
    from rt.telegram.app_commands import process_pending_commands
    lid = lesson_id
    assert api_client.get("/api/v1/recall/telegram").json()["running"] is True

    res = api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "mirata"})
    assert res.status_code == 202, res.text
    assert res.json()["state"] == "pending"
    state = _state(api_client, lid)
    assert state["telegram"] is None and state["command"]["kind"] == "start_recall"

    # il daemon esegue la richiesta: la sessione parte nel topic della materia
    assert process_pending_commands(force_mock=True) == 1
    state = _state(api_client, lid)
    assert state["command"]["state"] == "done", state["command"]
    session = state["telegram"]
    assert session["state"] == "active" and session["lesson_id"] == lid and session["qtype"] == "mirata"
    state_dir = load_config().telegram.state_dir
    assert recall_preferences.get_active_style(state_dir) == "mirata"
    assert tg_session.get_active_session(state_dir, "-100", TOPIC)["kind"] == "recall"
    questions = [p for m, p in bot.calls if m == "sendMessage" and "reply_markup" in p]
    assert questions and all(p["message_thread_id"] == TOPIC for p in questions)
    listed = api_client.get("/api/v1/recall/telegram").json()["sessions"]
    assert [s["id"] for s in listed] == [session["id"]]

    # con la sessione su Telegram la web non pone domande, e non se ne avvia un'altra
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_session_active"
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_session_active"

    # Interrompi: il registro la chiude subito, il bot libera il topic e lo scrive
    bot.calls.clear()
    res = api_client.post(f"/api/v1/recall/telegram/sessions/{session['id']}/stop")
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "interrupted" and res.json()["ended_by"] == "app"
    assert _state(api_client, lid)["telegram"] is None
    assert process_pending_commands() == 1
    assert tg_session.get_active_session(state_dir, "-100", TOPIC) is None
    sent = [p for m, p in bot.calls if m == "sendMessage"]
    assert [p["text"] for p in sent] == ["⏹ Sessione interrotta dall'app."]
    assert sent[0]["message_thread_id"] == TOPIC
    assert any(m == "editMessageReplyMarkup" for m, _ in bot.calls)
    assert api_client.post(f"/api/v1/recall/telegram/sessions/{session['id']}/stop").status_code == 409
    assert api_client.post("/api/v1/recall/telegram/sessions/999/stop").status_code == 404
    assert api_client.get("/api/v1/recall/telegram").json()["sessions"] == []

    # la web torna a porre domande
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"}).status_code == 200


def test_telegram_session_closed_from_telegram_updates_registry(api_client, lesson_id, bot):
    """/quit (o la fine della riserva) chiude la sessione anche nel registro letto dall'API."""
    from rt.core.config import load_config
    from rt.telegram import session as tg_session
    from rt.telegram.app_commands import process_pending_commands
    lid = lesson_id
    api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    process_pending_commands(force_mock=True)
    assert _state(api_client, lid)["telegram"]["state"] == "active"

    tg_session.end_session(load_config().telegram.state_dir, "-100", TOPIC, ended_by="telegram")
    state = _state(api_client, lid)
    assert state["telegram"] is None
    from rt.services.recall_sessions import list_sessions
    closed = list_sessions(channel="telegram", state="ended")
    assert closed and closed[0]["ended_by"] == "telegram" and closed[0]["summary"] is not None


def test_telegram_start_failure_is_reported(api_client, lesson_id, bot, monkeypatch):
    """Il topic è occupato da un'altra attività: il comando fallisce con il motivo."""
    from rt.core.config import load_config
    from rt.telegram import session as tg_session
    from rt.telegram.app_commands import process_pending_commands
    lid = lesson_id
    tg_session.start_session(load_config().telegram.state_dir, "-100", TOPIC, "issue_review", "/altra/lezione")
    api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    process_pending_commands(force_mock=True)
    state = _state(api_client, lid)
    assert state["telegram"] is None
    assert state["command"]["state"] == "failed" and "attività in corso" in state["command"]["error"]


def test_web_session_blocks_telegram_start(api_client, lesson_id, bot):
    lid = lesson_id
    api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"})
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/telegram/start", json={"qtype": "quiz"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "web_session_active"
