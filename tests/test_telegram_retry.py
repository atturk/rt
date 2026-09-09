import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.error import RetryAfter

from rt.telegram.client import send_message, edit_message_reply_markup, delete_message, TelegramAPIError
from rt.telegram.config import TelegramConfig
from rt.telegram.daemon import _send_with_retry, _handle_issue_callback, handle_text, handle_status
from rt.telegram import registry, conversation_state as convo, pending as tg_pending


def test_client_send_message_retries_on_429_and_succeeds():
    cfg = TelegramConfig(bot_token="fake_tok", chat_id=12345)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 0.05",
        "parameters": {"retry_after": 0.05},
    }

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {
        "ok": True,
        "result": {"message_id": 999},
    }

    with patch("requests.post", side_effect=[resp_429, resp_ok]) as mock_post, \
         patch("time.sleep") as mock_sleep:
        res = send_message(cfg, text="Test flood control")
        assert res == {"message_id": 999}
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(0.05)


def test_client_send_message_raises_on_persistent_429():
    cfg = TelegramConfig(bot_token="fake_tok", chat_id=12345)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 0.05",
        "parameters": {"retry_after": 0.05},
    }

    with patch("requests.post", side_effect=[resp_429, resp_429]) as mock_post, \
         patch("time.sleep") as mock_sleep:
        with pytest.raises(TelegramAPIError) as exc_info:
            send_message(cfg, text="Persistent flood")
        assert "Too Many Requests" in str(exc_info.value)
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(0.05)


def test_client_delete_message_succeeds():
    """delete_message è usata dagli script di verifica live contro il bot reale per
    ripulire i messaggi di test dal gruppo a fine esecuzione (non deve mai far accumulare
    traffico di prova nel gruppo dell'utente)."""
    cfg = TelegramConfig(bot_token="fake_tok", chat_id=12345)
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {"ok": True, "result": True}

    with patch("requests.post", return_value=resp_ok) as mock_post:
        assert delete_message(cfg, message_id=999) is True
        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload == {"chat_id": 12345, "message_id": 999}
        assert "deleteMessage" in mock_post.call_args.args[0]


def test_client_delete_message_returns_false_instead_of_raising_when_already_gone():
    """Un messaggio già cancellato o troppo vecchio (>48h) non deve far fallire uno
    script di pulizia: solo gli altri messaggi restano da cancellare."""
    cfg = TelegramConfig(bot_token="fake_tok", chat_id=12345)
    resp_fail = MagicMock()
    resp_fail.status_code = 400
    resp_fail.json.return_value = {
        "ok": False, "error_code": 400, "description": "Bad Request: message to delete not found",
    }

    with patch("requests.post", return_value=resp_fail):
        assert delete_message(cfg, message_id=999) is False


def test_daemon_send_with_retry_succeeds_after_one_retry_after():
    call_count = 0

    async def flaky_send():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RetryAfter(retry_after=0.02)
        return "delivered"

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = asyncio.run(_send_with_retry(flaky_send, max_retries=1))
        assert res == "delivered"
        assert call_count == 2
        mock_sleep.assert_called_once_with(0.02)


def test_daemon_send_with_retry_raises_when_retries_exhausted():
    call_count = 0

    async def always_failing_send():
        nonlocal call_count
        call_count += 1
        raise RetryAfter(retry_after=0.02)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(RetryAfter):
            asyncio.run(_send_with_retry(always_failing_send, max_retries=1))
        assert call_count == 2
        mock_sleep.assert_called_once_with(0.02)


def test_daemon_handle_issue_callback_edit_retries_on_retry_after(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")

    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_01", "issue_type": "asr"}
    )

    update = MagicMock()
    query = MagicMock()
    query.answer = AsyncMock()
    update.callback_query = query
    update.effective_chat.id = 12345
    update.effective_message.message_thread_id = None

    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}

    send_call_count = 0

    async def mock_bot_send(*args, **kwargs):
        nonlocal send_call_count
        send_call_count += 1
        if send_call_count == 1:
            raise RetryAfter(retry_after=0.01)
        return MagicMock()

    context.bot.send_message = mock_bot_send

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        asyncio.run(_handle_issue_callback(update, context, "ie", short_id))
        assert send_call_count == 2
        mock_sleep.assert_called_once_with(0.01)

    awaiting = convo.get_awaiting_feedback(state_dir, 12345)
    assert awaiting is not None
    assert awaiting["kind"] == "issue_edit"


def test_daemon_handle_status_retries_on_retry_after(tmp_path):
    state_dir = str(tmp_path / "state")

    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_message.message_thread_id = None

    status_call_count = 0

    async def mock_reply(*args, **kwargs):
        nonlocal status_call_count
        status_call_count += 1
        if status_call_count == 1:
            raise RetryAfter(retry_after=0.03)
        return MagicMock()

    update.effective_message.reply_text = mock_reply
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        asyncio.run(handle_status(update, context))
        assert status_call_count == 2
        mock_sleep.assert_called_once_with(0.03)
