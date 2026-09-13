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


def test_notify_build_completed_with_dedicated_topic(tmp_path, monkeypatch):
    from unittest.mock import patch, MagicMock
    from rt.telegram.notify import notify_build_completed

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    lesson_dir = str(tmp_path / "lesson_notify_dedicated")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\ndata: '2026-09-08'\nargomenti: Lipidi e membrane\n")

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        cfg_obj = MagicMock()
        cfg_obj.telegram.topics = {"BIOCHIMICA": 42}
        cfg_obj.telegram.misc_topic_id = None
        cfg_obj.telegram.state_dir = str(tmp_path / "state")
        mock_cfg.return_value = cfg_obj

        notify_build_completed(lesson_dir, {"rielaborato": "/abs/path/rielaborato.md"}, "Lezione 1")
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs.get("message_thread_id") == 42
        text = kwargs.get("text")
        assert "Lezione pronta" in text
        assert "2026-09-08" in text
        assert "Lipidi e membrane" in text
        assert "/list" in text
        # Topic dedicato -> la materia BIOCHIMICA non deve apparire
        assert "BIOCHIMICA" not in text
        assert "rielaborato.md" not in text


def test_notify_build_completed_with_generic_topic(tmp_path, monkeypatch):
    from unittest.mock import patch, MagicMock
    from rt.telegram.notify import notify_build_completed

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    lesson_dir = str(tmp_path / "lesson_notify_generic")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: FARMACOLOGIA\ndata: '2026-09-09'\nargomenti: Farmacocinetica\n")

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        cfg_obj = MagicMock()
        cfg_obj.telegram.topics = {"BIOCHIMICA": 42}  # FARMACOLOGIA non in mappa -> generico
        cfg_obj.telegram.misc_topic_id = 99
        cfg_obj.telegram.state_dir = str(tmp_path / "state")
        mock_cfg.return_value = cfg_obj

        notify_build_completed(lesson_dir, {"rielaborato": "/abs/path/rielaborato.md"}, "Lezione 2")
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs.get("message_thread_id") == 99
        text = kwargs.get("text")
        assert "Lezione pronta" in text
        assert "2026-09-09" in text
        assert "Farmacocinetica" in text
        # Topic generico -> la materia FARMACOLOGIA DEVE apparire
        assert "FARMACOLOGIA" in text
        assert "/list" in text
        assert "rielaborato.md" not in text


def test_notify_build_completed_no_argomenti(tmp_path, monkeypatch):
    from unittest.mock import patch, MagicMock
    from rt.telegram.notify import notify_build_completed

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    lesson_dir = str(tmp_path / "lesson_no_args")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\ndata: '2026-09-10'\n")

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        cfg_obj = MagicMock()
        cfg_obj.telegram.topics = {"BIOCHIMICA": 42}
        cfg_obj.telegram.misc_topic_id = None
        cfg_obj.telegram.state_dir = str(tmp_path / "state")
        mock_cfg.return_value = cfg_obj

        notify_build_completed(lesson_dir, {}, "Lezione 3")
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        text = kwargs.get("text")
        assert "📌" not in text
        assert "2026-09-10" in text
        assert "/list" in text


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


import asyncio


def test_handle_list_command_empty_lessons_root(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch
    from rt.telegram.daemon import handle_list_command

    empty_root = str(tmp_path / "empty_lessons")
    os.makedirs(empty_root, exist_ok=True)

    update = MagicMock()
    update.effective_message.message_thread_id = None
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"state_dir": str(tmp_path / "state")}

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg = MagicMock()
        cfg.telegram.lessons_root = empty_root
        cfg.telegram.topics = {"BIOCHIMICA": 42}
        mock_cfg.return_value = cfg

        asyncio.run(handle_list_command(update, context))

    update.effective_message.reply_text.assert_called_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert f"Nessuna lezione trovata in '{empty_root}'" in reply
    assert "rt config" in reply


def test_handle_list_command_different_topic(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch
    from rt.telegram.daemon import handle_list_command

    root_dir = str(tmp_path / "lessons")
    l1 = os.path.join(root_dir, "lesson_bio")
    os.makedirs(l1, exist_ok=True)
    with open(os.path.join(l1, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\ndata: '2026-09-08'\n")

    update = MagicMock()
    update.effective_message.message_thread_id = 99  # Topic per ANATOMIA
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"state_dir": str(tmp_path / "state")}

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg = MagicMock()
        cfg.telegram.lessons_root = root_dir
        cfg.telegram.topics = {"BIOCHIMICA": 42, "ANATOMIA": 99}
        mock_cfg.return_value = cfg

        asyncio.run(handle_list_command(update, context))

    update.effective_message.reply_text.assert_called_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert "Nessuna lezione trovata per la materia di questo topic" in reply
    assert "1 lezioni totali in altri topic/materie" in reply





