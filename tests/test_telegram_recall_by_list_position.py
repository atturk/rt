import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional, List, Dict, Any

from rt.telegram.daemon import handle_list_command, handle_recall_command
from rt.telegram import registry


def _create_fake_lesson(root: str, folder_name: str, materia: str, data: str, argomenti: str) -> str:
    path = os.path.join(root, folder_name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(f"materia: {materia}\ndata: '{data}'\nargomenti: {argomenti}\n")
    return path


def test_handle_list_registers_message_mapping(tmp_path):
    lessons_root = str(tmp_path / "lessons")
    state_dir = str(tmp_path / "state")
    os.makedirs(state_dir, exist_ok=True)

    l1 = _create_fake_lesson(lessons_root, "l1", "BIOCHIMICA", "2026-09-01", "Glicolisi")
    l2 = _create_fake_lesson(lessons_root, "l2", "BIOCHIMICA", "2026-09-02", "Krebs")

    sent_message_mock = MagicMock()
    sent_message_mock.message_id = 777

    update = MagicMock()
    update.effective_message.message_thread_id = None
    update.effective_message.reply_text = AsyncMock(return_value=sent_message_mock)

    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg = MagicMock()
        cfg.telegram.lessons_root = lessons_root
        cfg.telegram.topics = {}
        mock_cfg.return_value = cfg

        asyncio.run(handle_list_command(update, context))

    resolved = registry.resolve_list_message(777, state_dir)
    assert resolved is not None
    assert len(resolved) == 2
    assert resolved[0] == os.path.abspath(l1)
    assert resolved[1] == os.path.abspath(l2)


def test_handle_recall_reply_to_list_valid_position(tmp_path):
    lessons_root = str(tmp_path / "lessons")
    state_dir = str(tmp_path / "state")
    os.makedirs(state_dir, exist_ok=True)

    # Crea 12 lezioni. La lezione 1 ha data 2026-11-11 (contiene "11" in data).
    # La lezione 11 (1-based) ha materia BIOCHIMICA, data 2026-09-20, argomenti "Target".
    dirs = []
    for i in range(1, 13):
        if i == 1:
            d = _create_fake_lesson(lessons_root, f"lesson_{i:02d}", "BIOCHIMICA", "2026-09-01", "Capitolo 11")
        elif i == 11:
            d = _create_fake_lesson(lessons_root, f"lesson_{i:02d}", "BIOCHIMICA", "2026-09-20", "Target")
        else:
            d = _create_fake_lesson(lessons_root, f"lesson_{i:02d}", "BIOCHIMICA", f"2026-09-{i:02d}", f"Arg {i}")
        dirs.append(d)

    list_msg_id = 888
    registry.register_list_message(list_msg_id, dirs, state_dir)

    reply_to = MagicMock()
    reply_to.message_id = list_msg_id

    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_message.message_thread_id = None
    update.effective_message.reply_to_message = reply_to
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = ["11"]
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.pipeline.recall_session.start_recall_via_telegram") as mock_start:
        cfg = MagicMock()
        cfg.telegram.lessons_root = lessons_root
        cfg.telegram.topics = {}
        mock_cfg.return_value = cfg

        asyncio.run(handle_recall_command(update, context))

        # Deve essere avviata la lezione in posizione 11 (dirs[10]), non la lezione 1 che conteneva '11' nella data
        mock_start.assert_called_once_with(os.path.abspath(dirs[10]), "alternato", None, False)


def test_handle_recall_without_reply_falls_back_to_text_search(tmp_path):
    lessons_root = str(tmp_path / "lessons")
    state_dir = str(tmp_path / "state")
    os.makedirs(state_dir, exist_ok=True)

    l1 = _create_fake_lesson(lessons_root, "lesson_01", "BIOCHIMICA", "2026-09-01", "Capitolo 11")

    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_message.message_thread_id = None
    update.effective_message.reply_to_message = None  # NOT a reply
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = ["11"]
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.pipeline.recall_session.start_recall_via_telegram") as mock_start:
        cfg = MagicMock()
        cfg.telegram.lessons_root = lessons_root
        cfg.telegram.topics = {}
        mock_cfg.return_value = cfg

        asyncio.run(handle_recall_command(update, context))

        # Risolve testualmente a l1 (che ha 11 nella data)
        mock_start.assert_called_once_with(os.path.abspath(l1), "alternato", None, False)


def test_handle_recall_reply_to_list_out_of_range_error(tmp_path):
    lessons_root = str(tmp_path / "lessons")
    state_dir = str(tmp_path / "state")
    os.makedirs(state_dir, exist_ok=True)

    l1 = _create_fake_lesson(lessons_root, "l1", "BIOCHIMICA", "2026-09-01", "Glicolisi")
    l2 = _create_fake_lesson(lessons_root, "l2", "BIOCHIMICA", "2026-09-02", "Krebs")

    list_msg_id = 999
    registry.register_list_message(list_msg_id, [l1, l2], state_dir)

    reply_to = MagicMock()
    reply_to.message_id = list_msg_id

    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_message.message_thread_id = None
    update.effective_message.reply_to_message = reply_to
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = ["99"]
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.pipeline.recall_session.start_recall_via_telegram") as mock_start:
        cfg = MagicMock()
        cfg.telegram.lessons_root = lessons_root
        cfg.telegram.topics = {}
        mock_cfg.return_value = cfg

        asyncio.run(handle_recall_command(update, context))

        mock_start.assert_not_called()
        update.effective_message.reply_text.assert_called_once()
        msg = update.effective_message.reply_text.call_args[0][0]
        assert "⚠️ Posizione 99 non valida" in msg
        assert "la lista contiene 2 lezioni" in msg


def test_handle_recall_reply_to_list_non_numeric_keeps_text_search(tmp_path):
    lessons_root = str(tmp_path / "lessons")
    state_dir = str(tmp_path / "state")
    os.makedirs(state_dir, exist_ok=True)

    l1 = _create_fake_lesson(lessons_root, "l1", "BIOCHIMICA", "2026-11-11", "Lipidi")

    list_msg_id = 999
    registry.register_list_message(list_msg_id, [l1], state_dir)

    reply_to = MagicMock()
    reply_to.message_id = list_msg_id

    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_message.message_thread_id = None
    update.effective_message.reply_to_message = reply_to
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = ["11", "novembre"]  # Non puramente numerico
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.pipeline.recall_session.start_recall_via_telegram") as mock_start:
        cfg = MagicMock()
        cfg.telegram.lessons_root = lessons_root
        cfg.telegram.topics = {}
        mock_cfg.return_value = cfg

        asyncio.run(handle_recall_command(update, context))

        # Dovrebbe fare ricerca testuale per '11 novembre'
        mock_start.assert_called_once_with(os.path.abspath(l1), "alternato", None, False)
