from unittest.mock import patch

from rt.db.models import Setting
from rt.db.session import session_scope
from rt.services.telegram_topics import DISCOVERY_KEY, listen_existing_daemon, remember_topic_message


def _message(**extra):
    return {"message_id": 42, "message_thread_id": 42, "chat": {"id": -1001},
            "forum_topic_created": {"name": "BIOCHIMICA"}, **extra}


def test_existing_daemon_discovers_without_polling(rt_db):
    def receive(_seconds):
        remember_topic_message(_message(text="appunti privati", from_={"id": 7}))
    with patch("rt.services.telegram_topics.time.sleep", side_effect=receive):
        result = listen_existing_daemon(seconds=20)
    assert result["topics"] == [42]
    assert result["names"] == {"42": "BIOCHIMICA"}
    with session_scope(rt_db) as session:  # finestra chiusa: nulla resta nel DB
        assert session.get(Setting, DISCOVERY_KEY) is None


def test_bot_stores_nothing_outside_a_listening_window(rt_db):
    remember_topic_message(_message())
    with session_scope(rt_db) as session:
        assert session.get(Setting, DISCOVERY_KEY) is None


def test_only_topic_fields_are_kept_during_the_window(rt_db):
    stored = []

    def receive(_seconds):
        remember_topic_message(_message(text="appunti privati", reply_to_message={"text": "altro", "message_id": 42}))
        with session_scope(rt_db) as session:
            stored.extend(event["message"] for event in session.get(Setting, DISCOVERY_KEY).value)
    with patch("rt.services.telegram_topics.time.sleep", side_effect=receive):
        listen_existing_daemon(seconds=20)
    assert stored and "appunti privati" not in str(stored) and "altro" not in str(stored)
