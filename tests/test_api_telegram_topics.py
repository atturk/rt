"""
tests/test_api_telegram_topics.py
RT4-FA6: topic Telegram dalla web con il Bot API finto (tests/api_support.fake_telegram_server):
nome del topic rilevato durante l'ascolto, messaggio di prova, cancellazione dei soli messaggi
ricevuti durante l'ultimo ascolto, anteprima e rivelazione di token e Chat ID, ultime notifiche.
"""
import pytest
from fastapi.testclient import TestClient

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import fake_telegram_server, workspace_with_example_config

BOT = "987654321:AAH-segreto-bot-telegram-zyxwvu"
CHAT = "-1001234567890"


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    root = workspace_with_example_config(tmp_path, monkeypatch)
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID", raising=False)
    yield root
    import os
    os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
    os.environ.pop("RT_TELEGRAM_CHAT_ID", None)


@pytest.fixture
def telegram(monkeypatch):
    server, base = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    yield server
    server.shutdown()


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="test-worker")


def listen(client, worker):
    res = client.post("/api/v1/settings/telegram/listen-topics")
    assert res.status_code == 202, res.text
    while worker.run_once() is not None:
        pass
    got = client.get(f"/api/v1/jobs/{res.json()['job_id']}").json()
    assert got["state"] == "succeeded", got
    return got["result"]


def configure(client, topics=None):
    res = client.put("/api/v1/settings/telegram", json={"bot_token": BOT, "chat_id": CHAT, "topics": topics or {}})
    assert res.status_code == 200, res.text
    return res.json()


def test_listen_detects_topic_names_and_matching_materia(api_client, ws, telegram, worker):
    # BIOCHIMICA è una materia nota (topic già salvato); "Anatomia umana" no.
    configure(api_client, {"BIOCHIMICA": 5})
    result = listen(api_client, worker)
    assert result["topics"] == [12, 27, 33]
    assert result["names"] == {"12": "Biochimica", "27": "Anatomia umana"}  # 33: nome non recuperabile
    assert result["materie"] == {"12": "BIOCHIMICA"}
    # solo i messaggi degli utenti, mai quello di servizio che crea il topic (id 12)
    assert sorted(m["message_id"] for m in result["messages"]) == [40, 41, 42, 43, 44]
    assert all(m["chat_id"] == CHAT for m in result["messages"])
    assert BOT not in str(result)


def test_topic_names_are_saved_with_the_topics(api_client, api_token, ws):
    res = api_client.put("/api/v1/settings/telegram", json={
        "topics": {"BIOCHIMICA": 12, "ANATOMIA": 27}, "topic_names": {"12": "Biochimica", "27": "Anatomia umana", "99": "Altro"}})
    assert res.status_code == 200, res.text
    from rt.api.app import create_app
    fresh = TestClient(create_app())
    fresh.headers["Authorization"] = f"Bearer {api_token}"
    tg = fresh.get("/api/v1/settings").json()["telegram"]
    assert tg["topic_names"] == {"12": "Biochimica", "27": "Anatomia umana"}  # 99 non è un topic salvato
    # senza topic_names nel corpo i nomi restano; togliendo il topic sparisce anche il nome
    api_client.put("/api/v1/settings/telegram", json={"topics": {"BIOCHIMICA": 12}})
    assert fresh.get("/api/v1/settings").json()["telegram"]["topic_names"] == {"12": "Biochimica"}


def test_test_message_goes_to_the_topic(api_client, ws, telegram):
    res = api_client.post("/api/v1/settings/telegram/test-topic", json={"topic_id": 12, "materia": "biochimica"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "telegram_not_configured"
    configure(api_client)
    res = api_client.post("/api/v1/settings/telegram/test-topic", json={"topic_id": 12, "materia": "biochimica"})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True and res.json()["text"] == "Questo è il topic di BIOCHIMICA"
    assert telegram.calls[-1] == ("sendMessage", {"chat_id": CHAT, "text": "Questo è il topic di BIOCHIMICA",
                                                  "message_thread_id": 12})
    assert BOT not in res.text
    # la prova compare tra le ultime notifiche della pagina Bot Telegram
    sent = api_client.get("/api/v1/telegram/notifications").json()
    assert sent[0]["kind"] == "prova" and sent[0]["topic_id"] == 12 and sent[0]["text"] == "Questo è il topic di BIOCHIMICA"


def test_test_message_error_is_reported(api_client, ws, telegram, monkeypatch):
    configure(api_client)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:rifiutato")
    res = api_client.post("/api/v1/settings/telegram/test-topic", json={"topic_id": 12, "materia": "X"})
    assert res.status_code == 200 and res.json()["ok"] is False
    assert "Unauthorized" in res.json()["message"] and "rifiutato" not in res.text


def test_cleanup_deletes_only_messages_of_the_last_listen(api_client, ws, telegram, worker):
    configure(api_client)
    assert api_client.get("/api/v1/settings/telegram/listen-messages").json() == {
        "job_id": None, "finished_at": None, "count": 0, "cleaned": False}
    assert api_client.post("/api/v1/settings/telegram/listen-messages/delete").status_code == 404

    listen(api_client, worker)
    info = api_client.get("/api/v1/settings/telegram/listen-messages").json()
    assert info["count"] == 5 and info["cleaned"] is False and info["job_id"]

    telegram.calls.clear()
    res = api_client.post("/api/v1/settings/telegram/listen-messages/delete")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["deleted"] == 4
    assert out["failed"] == [{"message_id": 42, "reason": "più vecchio di 48 ore (limite di Telegram)"}]
    # solo deleteMessage, solo i messaggi dell'ascolto: mai la radice del topic (12) né altri
    assert {m for m, _ in telegram.calls} == {"deleteMessage"}
    assert sorted(b["message_id"] for _, b in telegram.calls) == [40, 41, 43, 44]
    assert telegram.deleted == {(CHAT, 40), (CHAT, 41), (CHAT, 43), (CHAT, 44)}
    assert api_client.get("/api/v1/settings/telegram/listen-messages").json()["cleaned"] is True

    # ripetere non cancella altro: Telegram risponde che non li trova più
    again = api_client.post("/api/v1/settings/telegram/listen-messages/delete").json()
    assert again["deleted"] == 0 and {f["reason"] for f in again["failed"]} >= {"non trovato (già cancellato?)"}


def test_cleanup_uses_the_last_successful_listen(api_client, ws, telegram, worker, monkeypatch):
    """Un ascolto fallito dopo quello riuscito non cambia i messaggi da cancellare."""
    configure(api_client)
    first = listen(api_client, worker)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:rifiutato")
    assert listen(api_client, worker)["ok"] is False
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", BOT)
    assert api_client.get("/api/v1/settings/telegram/listen-messages").json()["count"] == len(first["messages"])


def test_preview_and_reveal_of_token_and_chat_id(api_client, ws):
    tg = api_client.get("/api/v1/settings").json()["telegram"]
    assert (tg["bot_token_set"], tg["bot_token_preview"], tg["chat_id_set"], tg["chat_id_preview"]) == (False, None, False, None)
    res = api_client.post("/api/v1/settings/telegram/reveal", json={"field": "bot_token"})
    assert res.status_code == 200 and res.json() == {"field": "bot_token", "value": None}

    configure(api_client)
    res = api_client.get("/api/v1/settings")
    assert BOT not in res.text and CHAT not in res.text  # la risposta normale ha solo l'anteprima
    tg = res.json()["telegram"]
    assert tg["bot_token_preview"] == "9876…xwvu" and tg["chat_id_preview"] == "-100…7890" and tg["chat_id_set"] is True

    res = api_client.post("/api/v1/settings/telegram/reveal", json={"field": "bot_token"})
    assert res.json() == {"field": "bot_token", "value": BOT} and res.headers["cache-control"] == "no-store"
    assert api_client.post("/api/v1/settings/telegram/reveal", json={"field": "chat_id"}).json()["value"] == CHAT
    assert api_client.post("/api/v1/settings/telegram/reveal", json={"field": "altro"}).status_code == 422


def test_reveal_requires_authentication(ws):
    from rt.api.app import create_app
    anonymous = TestClient(create_app())
    res = anonymous.post("/api/v1/settings/telegram/reveal", json={"field": "bot_token"})
    assert res.status_code == 401


def test_mask_value():
    from rt.services.settings_service import mask_value
    assert mask_value("") is None
    assert mask_value("123456:ABCDEFwXyZ") == "1234…wXyZ"
    assert mask_value("-1001") == "…"
    assert mask_value("-100777") == "-1…77"


def test_notifications_log(tmp_path):
    from rt.telegram.notify_log import MAX_ENTRIES, recent_notifications, record_notification
    state = str(tmp_path / "state")
    assert recent_notifications(state_dir=state) == []
    for i in range(MAX_ENTRIES + 5):
        record_notification("issue", f"<b>{i}</b> issue &amp; altro", 7, state_dir=state)
    items = recent_notifications(limit=100, state_dir=state)
    assert len(items) == MAX_ENTRIES
    assert items[0]["text"] == f"{MAX_ENTRIES + 4} issue & altro" and items[0]["topic_id"] == 7


def test_topic_names_from_bot_api_messages():
    from rt.services.telegram_topics import match_materia, topic_names
    msgs = [
        {"message_id": 5, "message_thread_id": 5, "forum_topic_created": {"name": "Fisiologia"}},
        {"message_id": 9, "message_thread_id": 5, "forum_topic_edited": {"name": "Fisiologia II"}},
        {"message_id": 10, "message_thread_id": 8, "reply_to_message": {"message_id": 8, "forum_topic_created": {"name": "Chimica"}}},
        # risposta a un messaggio qualunque: il nome non si ricava
        {"message_id": 11, "message_thread_id": 20, "reply_to_message": {"message_id": 15, "text": "x"}},
    ]
    assert topic_names(msgs) == {5: "Fisiologia II", 8: "Chimica"}
    assert match_materia("Patologia Generale", ["PATOLOGIA GENERALE", "BIOCHIMICA"]) == "PATOLOGIA GENERALE"
    assert match_materia("Fisiología", ["FISIOLOGIA"]) == "FISIOLOGIA"
    assert match_materia("Anatomia umana", ["ANATOMIA"]) is None
