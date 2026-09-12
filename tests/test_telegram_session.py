import os
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rt.telegram import session as tg_session, registry
from rt.telegram.daemon import handle_quit, handle_status, _handle_issue_callback
from rt.telegram.notify import notify_issues_ready


def _make_mock_message_update(text: str = "/status", chat_id: int = 12345, thread_id: int = None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    message = MagicMock()
    message.text = text
    message.message_thread_id = thread_id
    message.reply_text = AsyncMock()
    update.effective_message = message
    update.message = message
    return update


def _make_mock_context(state_dir: str):
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}
    context.bot.send_message = AsyncMock()
    context.bot.edit_message_reply_markup = AsyncMock()
    return context


def test_session_lifecycle_and_roundtrip(tmp_path):
    state_dir = str(tmp_path / "state")
    lesson_dir = str(tmp_path / "lesson_a")
    os.makedirs(lesson_dir, exist_ok=True)

    # 1. No active session
    assert tg_session.get_active_session(state_dir, 12345, None) is None
    assert tg_session.get_active_session(state_dir, 12345, 101) is None

    # 2. Start session on general topic with message_id
    tg_session.start_session(state_dir, 12345, None, "outline_confirmation", lesson_dir, message_id=555)
    sess = tg_session.get_active_session(state_dir, 12345, None)
    assert sess is not None
    assert sess["kind"] == "outline_confirmation"
    assert sess["lesson_dir"] == os.path.abspath(lesson_dir)
    assert sess["chat_id"] == "12345"
    assert sess["thread_id"] is None
    assert sess["message_id"] == 555
    assert "started_at" in sess

    # Update session message_id
    tg_session.update_session_message(state_dir, 12345, None, 777)
    sess = tg_session.get_active_session(state_dir, 12345, None)
    assert sess["message_id"] == 777

    # Topic 101 is still free
    assert tg_session.get_active_session(state_dir, 12345, 101) is None

    # 3. Start session on topic 101
    lesson_dir_b = str(tmp_path / "lesson_b")
    tg_session.start_session(state_dir, 12345, 101, "issue_review", lesson_dir_b)
    sess_101 = tg_session.get_active_session(state_dir, 12345, 101)
    assert sess_101 is not None
    assert sess_101["kind"] == "issue_review"
    assert sess_101["lesson_dir"] == os.path.abspath(lesson_dir_b)
    assert sess_101["message_id"] is None

    # 4. End sessions
    tg_session.end_session(state_dir, 12345, None)
    assert tg_session.get_active_session(state_dir, 12345, None) is None
    assert tg_session.get_active_session(state_dir, 12345, 101) is not None

    tg_session.end_session(state_dir, 12345, 101)
    assert tg_session.get_active_session(state_dir, 12345, 101) is None


def test_notify_issues_ready_duplicate_suppression(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = str(tmp_path / "state")

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "12345")

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        mock_send.return_value = {"ok": True, "message_id": 9001}
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        # Prima chiamata -> invia keyboard con bottone Inizia review
        notify_issues_ready(lesson_dir, "asr", 3)
        assert mock_send.call_count == 1
        _, kwargs1 = mock_send.call_args
        assert kwargs1.get("reply_markup") is not None
        assert "3 issue ASR pronte" in kwargs1.get("text")

        sess = tg_session.get_active_session(state_dir, 12345, None)
        assert sess is not None
        assert sess["kind"] == "issue_review"
        assert sess["message_id"] == 9001

        # Seconda chiamata per la stessa lezione -> invia promemoria informativo senza bottoni
        notify_issues_ready(lesson_dir, "asr", 3)
        assert mock_send.call_count == 2
        _, kwargs2 = mock_send.call_args
        assert kwargs2.get("reply_markup") is None
        assert "Review già pronta" in kwargs2.get("text")


def test_conflict_between_review_and_outline(tmp_path, monkeypatch):
    lesson_dir_a = str(tmp_path / "lesson_a")
    lesson_dir_b = str(tmp_path / "lesson_b")
    os.makedirs(lesson_dir_a, exist_ok=True)
    os.makedirs(lesson_dir_b, exist_ok=True)
    state_dir = str(tmp_path / "state")

    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "12345")

    # Attiva una sessione outline_confirmation su topic 5
    tg_session.start_session(state_dir, 12345, 5, "outline_confirmation", lesson_dir_a)

    with patch("rt.core.config.load_config") as mock_cfg, \
         patch("rt.telegram.client.send_message") as mock_send:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {"LESSON_B": 5}
        mock_cfg.return_value = cfg_obj

        # Tenta di notificare issue_review per lesson_b sullo stesso topic 5
        with patch("rt.telegram.config.resolve_topic_id", return_value=5):
            notify_issues_ready(lesson_dir_b, "science", 2)

        assert mock_send.call_count == 1
        _, kwargs = mock_send.call_args
        assert "già un'attività in corso in questo topic (outline_confirmation)" in kwargs.get("text")
        assert "/quit" in kwargs.get("text")


def test_handle_quit_issue_review(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = str(tmp_path / "state")

    tg_session.start_session(state_dir, 12345, None, "issue_review", lesson_dir)
    assert tg_session.get_active_session(state_dir, 12345, None) is not None

    update = _make_mock_message_update("/quit", chat_id=12345)
    context = _make_mock_context(state_dir)

    asyncio.run(handle_quit(update, context))

    assert tg_session.get_active_session(state_dir, 12345, None) is None
    context.bot.edit_message_reply_markup.assert_not_called()
    update.effective_message.reply_text.assert_called_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert "Revisione interrotta" in reply


def test_handle_quit_issue_review_with_message_id(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = str(tmp_path / "state")

    tg_session.start_session(state_dir, 12345, None, "issue_review", lesson_dir, message_id=4321)
    assert tg_session.get_active_session(state_dir, 12345, None) is not None

    update = _make_mock_message_update("/quit", chat_id=12345)
    context = _make_mock_context(state_dir)

    asyncio.run(handle_quit(update, context))

    assert tg_session.get_active_session(state_dir, 12345, None) is None
    context.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=12345, message_id=4321, reply_markup=None
    )
    update.effective_message.reply_text.assert_called_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert "Revisione interrotta" in reply



def test_handle_quit_edit_message_reply_markup_error_suppressed(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = str(tmp_path / "state")

    tg_session.start_session(state_dir, 12345, None, "issue_review", lesson_dir, message_id=9999)

    update = _make_mock_message_update("/quit", chat_id=12345)
    context = _make_mock_context(state_dir)
    context.bot.edit_message_reply_markup.side_effect = RuntimeError("Message not found or cannot be edited")

    # Should not raise exception
    asyncio.run(handle_quit(update, context))

    assert tg_session.get_active_session(state_dir, 12345, None) is None
    context.bot.edit_message_reply_markup.assert_awaited_once()
    update.effective_message.reply_text.assert_called_once()


def test_handle_status(tmp_path):
    lesson_dir = str(tmp_path / "my_awesome_lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = str(tmp_path / "state")

    # 1. Without active session
    update = _make_mock_message_update("/status", chat_id=12345)
    context = _make_mock_context(state_dir)
    asyncio.run(handle_status(update, context))

    reply1 = update.effective_message.reply_text.call_args[0][0]
    assert "Nessuna attività in corso" in reply1

    # 2. With active session
    tg_session.start_session(state_dir, 12345, None, "outline_confirmation", lesson_dir)
    update = _make_mock_message_update("/status", chat_id=12345)
    asyncio.run(handle_status(update, context))

    reply2 = update.effective_message.reply_text.call_args[0][0]
    assert "outline_confirmation" in reply2
    assert "my_awesome_lesson" in reply2


def _setup_review_lesson(lesson_dir: str):
    from rt.core.models import SegmentsData, Segment
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=1,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="err"),
        ],
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)


def test_start_review_via_telegram_registers_session(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path / "lesson_direct")
    state_dir = str(tmp_path / "state")
    _setup_review_lesson(lesson_dir)

    from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
    from rt.pipeline.issue_review import start_review_via_telegram
    from rt.telegram.config import TelegramConfig

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="err", reason="reason", suggested_fix="corr")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr("rt.telegram.client.send_message", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=12345))

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        # Verify no session before
        assert tg_session.get_active_session(state_dir, 12345, None) is None

        # Call start_review_via_telegram directly
        start_review_via_telegram(lesson_dir, sci_to_review=sci_issues)

        # Verify session is registered!
        sess = tg_session.get_active_session(state_dir, 12345, None)
        assert sess is not None
        assert sess["kind"] == "issue_review"
        assert sess["lesson_dir"] == os.path.abspath(lesson_dir)

        # /status sees it
        update = _make_mock_message_update("/status", chat_id=12345)
        context = _make_mock_context(state_dir)
        asyncio.run(handle_status(update, context))
        reply = update.effective_message.reply_text.call_args[0][0]
        assert "issue_review" in reply
        assert "lesson_direct" in reply


def test_start_review_callback_integration_registers_session(tmp_path, monkeypatch):
    from rt.telegram.daemon import handle_callback
    from rt.telegram.config import TelegramConfig
    from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity

    lesson_dir = str(tmp_path / "lesson_cb")
    state_dir = str(tmp_path / "state")
    _setup_review_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="err", reason="reason", suggested_fix="corr")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    short_id = registry.register_pending(
        lesson_dir, round_=1, kind="start_issue_review", state_dir=state_dir
    )

    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_message.message_thread_id = None
    update.callback_query.data = f"ivr:{short_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()

    context = _make_mock_context(state_dir)

    monkeypatch.setattr("rt.telegram.client.send_message", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=12345))

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        asyncio.run(handle_callback(update, context))

        sess = tg_session.get_active_session(state_dir, 12345, None)
        assert sess is not None
        assert sess["kind"] == "issue_review"
        assert sess["lesson_dir"] == os.path.abspath(lesson_dir)


def test_start_review_via_telegram_prevents_duplicate_active_session(tmp_path, monkeypatch):
    from rt.pipeline.issue_review import start_review_via_telegram
    from rt.telegram.config import TelegramConfig
    from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
    from rt.telegram import issue_queue as tg_queue

    lesson_dir = str(tmp_path / "lesson_dup")
    state_dir = str(tmp_path / "state")
    _setup_review_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="err", reason="reason", suggested_fix="corr")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    sent_messages = []

    def mock_send(cfg, text, reply_markup=None, message_thread_id=None):
        mid = 100 + len(sent_messages)
        sent_messages.append({"text": text, "reply_markup": reply_markup, "thread_id": message_thread_id, "message_id": mid})
        return {"ok": True, "message_id": mid}

    monkeypatch.setattr("rt.telegram.client.send_message", mock_send)
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=12345))

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        # 1. Prima chiamata: crea sessione, crea coda, invia primo messaggio con bottoni
        with patch("rt.telegram.issue_queue.create_queue", wraps=tg_queue.create_queue) as mock_create_queue:
            start_review_via_telegram(lesson_dir, sci_to_review=sci_issues)
            assert mock_create_queue.call_count == 1
            assert len(sent_messages) == 1
            assert sent_messages[0]["reply_markup"] is not None

        # 2. Seconda chiamata identica: non deve ricreare la coda né inviare nuovi bottoni
        with patch("rt.telegram.issue_queue.create_queue", wraps=tg_queue.create_queue) as mock_create_queue:
            start_review_via_telegram(lesson_dir, sci_to_review=sci_issues)
            assert mock_create_queue.call_count == 0
            # Ha inviato un secondo messaggio che è solo il promemoria senza bottoni
            assert len(sent_messages) == 2
            assert "Review già in corso per questa lezione" in sent_messages[1]["text"]
            assert sent_messages[1]["reply_markup"] is None


def test_start_review_via_telegram_busy_different_activity(tmp_path, monkeypatch):
    from rt.pipeline.issue_review import start_review_via_telegram
    from rt.telegram.config import TelegramConfig
    from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
    from rt.telegram import issue_queue as tg_queue

    lesson_dir = str(tmp_path / "lesson_busy")
    state_dir = str(tmp_path / "state")
    _setup_review_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="err", reason="reason", suggested_fix="corr")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    # Crea sessione attiva di tipo diverso (es. outline_confirmation su un'altra lezione)
    tg_session.start_session(state_dir, 12345, None, "outline_confirmation", "/tmp/other_lesson")

    sent_messages = []

    def mock_send(cfg, text, reply_markup=None, message_thread_id=None):
        mid = 100 + len(sent_messages)
        sent_messages.append({"text": text, "reply_markup": reply_markup, "thread_id": message_thread_id, "message_id": mid})
        return {"ok": True, "message_id": mid}

    monkeypatch.setattr("rt.telegram.client.send_message", mock_send)
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=12345))

    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        with patch("rt.telegram.issue_queue.create_queue", wraps=tg_queue.create_queue) as mock_create_queue:
            start_review_via_telegram(lesson_dir, sci_to_review=sci_issues)
            # Coda non creata
            assert mock_create_queue.call_count == 0
            # Ha inviato messaggio "occupato"
            assert len(sent_messages) == 1
            assert "C'è già un'attività in corso in questo topic (outline_confirmation)" in sent_messages[0]["text"]
            assert sent_messages[0]["reply_markup"] is None

        # La sessione originaria non è stata toccata
        sess = tg_session.get_active_session(state_dir, 12345, None)
        assert sess["kind"] == "outline_confirmation"
        assert sess["lesson_dir"] == "/tmp/other_lesson"

