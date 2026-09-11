import os
from rt.telegram.config import resolve_topic_id


def test_resolve_topic_id(tmp_path):
    lesson_dir = str(tmp_path / "test_lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-08'
materia: BIOCHIMICA
argomenti: Lipidi
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    # 1. Materia mappata -> topic id
    assert resolve_topic_id(lesson_dir, {"BIOCHIMICA": 5}) == 5
    # 2. Case insensitive uppercase mapping test
    assert resolve_topic_id(lesson_dir, {"biochimica": 5}) is None  # topics map keys are expected uppercase
    # 5. Fallback a misc_topic_id se materia non in mappa
    assert resolve_topic_id(lesson_dir, {"ALTRA": 9}, misc_topic_id=99) == 99


def test_resolve_topic_id_missing_or_empty_info(tmp_path):
    # Cartella senza info.yaml
    empty_dir = str(tmp_path / "empty_lesson")
    os.makedirs(empty_dir, exist_ok=True)
    assert resolve_topic_id(empty_dir, {"BIOCHIMICA": 5}) is None
    assert resolve_topic_id(empty_dir, {"BIOCHIMICA": 5}, misc_topic_id=99) == 99

    # info.yaml senza campo materia
    no_materia_dir = str(tmp_path / "no_materia_lesson")
    os.makedirs(no_materia_dir, exist_ok=True)
    with open(os.path.join(no_materia_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("argomenti: Lipidi\n")
    assert resolve_topic_id(no_materia_dir, {"BIOCHIMICA": 5}) is None
    assert resolve_topic_id(no_materia_dir, {"BIOCHIMICA": 5}, misc_topic_id=99) == 99


def test_reverse_resolve_materia():
    from rt.telegram.config import reverse_resolve_materia

    topics = {"BIOCHIMICA": 5, "ANATOMIA": 10}
    assert reverse_resolve_materia(5, topics) == "BIOCHIMICA"
    assert reverse_resolve_materia(10, topics) == "ANATOMIA"
    assert reverse_resolve_materia(99, topics) is None
    assert reverse_resolve_materia(None, topics) is None


def test_notify_build_completed_with_topic(tmp_path, monkeypatch):
    from unittest.mock import patch, MagicMock
    from rt.telegram.notify import notify_build_completed

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    lesson_dir = str(tmp_path / "lesson_notify")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\n")

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        cfg_obj = MagicMock()
        cfg_obj.telegram.topics = {"BIOCHIMICA": 42}
        cfg_obj.telegram.misc_topic_id = None
        cfg_obj.telegram.state_dir = str(tmp_path / "state")
        mock_cfg.return_value = cfg_obj

        notify_build_completed(lesson_dir, {"rielaborato": "test.md"}, "Lezione 1")
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs.get("message_thread_id") == 42


def test_notify_build_completed_missing_config_silent(tmp_path, monkeypatch):
    from unittest.mock import patch
    from rt.telegram.notify import notify_build_completed
    from rt.telegram.config import TelegramConfigError

    lesson_dir = str(tmp_path / "lesson_notify_no_cfg")
    os.makedirs(lesson_dir, exist_ok=True)

    with patch("rt.telegram.config.load_telegram_config") as mock_cfg:
        mock_cfg.side_effect = TelegramConfigError("no token")
        # Deve terminare in modo silenzioso senza sollevare eccezioni
        notify_build_completed(lesson_dir, {"rielaborato": "test.md"}, "Lezione 1")


