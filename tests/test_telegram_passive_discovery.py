from unittest.mock import patch

from rt.services.telegram_topics import listen_existing_daemon, remember_topic_message


def test_existing_daemon_discovers_without_polling(rt_db):
    message = {"message_id": 42, "message_thread_id": 42, "chat": {"id": -1001},
               "forum_topic_created": {"name": "BIOCHIMICA"}}
    with patch("rt.services.telegram_topics.time.time", side_effect=[100, 101]):
        # Start the observation before the bot receives the message.
        def receive(_seconds):
            remember_topic_message(message)
        with patch("rt.services.telegram_topics.time.sleep", side_effect=receive):
            result = listen_existing_daemon(seconds=20)
    assert result["topics"] == [42]
    assert result["names"] == {"42": "BIOCHIMICA"}
