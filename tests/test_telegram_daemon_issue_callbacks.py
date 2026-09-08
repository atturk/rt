import os
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rt.telegram import registry, conversation_state as convo, issue_queue as tg_queue
from rt.telegram.daemon import handle_callback, handle_text, _handle_issue_callback, _handle_start_review_callback
from rt.core.models import ASRIssue, ASRLevel, ScienceIssue, ScienceType, ScienceSeverity, SegmentsData, Segment, Draft, DraftUnit
from rt.pipeline.ledger import load_ledger


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=1,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="Ciao"),
        ]
    )

    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="U1",
                title="Unit 1",
                content="Testo con cand.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                key_concepts=[]
            )
        ]
    )

    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    asr_issues = [
        ASRIssue(id="asr_01", segment_id="seg_000001", source_text="orig", candidate="cand", confidence=0.8, level=ASRLevel.YELLOW, reason="mot"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)


    sci_issues = [
        ScienceIssue(id="sci_01", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="errore", reason="mot", suggested_fix="fix esatto"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)


def _make_mock_callback_update(data: str, chat_id: int = 12345):
    update = MagicMock()
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update.callback_query = query
    update.effective_chat.id = chat_id
    update.effective_message.message_thread_id = None
    return update


def _make_mock_context(state_dir: str):
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}
    context.bot.send_message = AsyncMock()
    return context


def test_issue_callback_accept(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["asr_01"], {"asr_01": "asr"})
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_01", "issue_type": "asr"}
    )

    update = _make_mock_callback_update(f"ia:{short_id}")
    context = _make_mock_context(state_dir)

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next:
        asyncio.run(handle_callback(update, context))
        assert mock_send_next.called

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_01"
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[0].resolved_text == "cand"

    queue = tg_queue.load_queue(lesson_dir)
    assert queue.current_index == 1


def test_issue_callback_reject(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["sci_01"], {"sci_01": "science"})
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "sci_01", "issue_type": "science"}
    )

    update = _make_mock_callback_update(f"ir:{short_id}")
    context = _make_mock_context(state_dir)

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next:
        asyncio.run(handle_callback(update, context))
        assert mock_send_next.called

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "sci_01"
    assert ledger.decisions[0].decision == "rejected"
    assert ledger.decisions[0].resolved_text == "errore"


def test_issue_callback_skip(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["asr_01"], {"asr_01": "asr"})
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_01", "issue_type": "asr"}
    )

    update = _make_mock_callback_update(f"is:{short_id}")
    context = _make_mock_context(state_dir)

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next:
        asyncio.run(handle_callback(update, context))
        assert mock_send_next.called

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 0  # Saltata: nessuna decisione registrata

    queue = tg_queue.load_queue(lesson_dir)
    assert queue.current_index == 1


def test_issue_callback_edit_and_text_response(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["asr_01"], {"asr_01": "asr"})
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_01", "issue_type": "asr"}
    )

    # 1. Clic su Modifica (ie)
    update_cb = _make_mock_callback_update(f"ie:{short_id}", chat_id=999)
    context = _make_mock_context(state_dir)

    asyncio.run(handle_callback(update_cb, context))

    # Verifica stato awaiting feedback
    awaiting = convo.get_awaiting_feedback(state_dir, 999)
    assert awaiting is not None
    assert awaiting["kind"] == "issue_edit"
    assert awaiting["extra"]["issue_id"] == "asr_01"

    # 2. Utente invia testo correzione
    update_msg = MagicMock()
    update_msg.effective_chat.id = 999
    update_msg.effective_message.message_thread_id = None
    update_msg.message.text = "testo corretto manualmente"
    update_msg.message.reply_text = AsyncMock()

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next:
        asyncio.run(handle_text(update_msg, context))
        assert mock_send_next.called

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_01"
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "testo corretto manualmente"

    # Awaiting feedback deve essere stato cancellato
    assert convo.get_awaiting_feedback(state_dir, 999) is None
    queue = tg_queue.load_queue(lesson_dir)
    assert queue.current_index == 1


def test_start_review_callback(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    short_id = registry.register_pending(
        lesson_dir, round_=1, kind="start_issue_review", state_dir=state_dir
    )

    update = _make_mock_callback_update(f"ivr:{short_id}")
    context = _make_mock_context(state_dir)

    with patch("rt.pipeline.issue_review.start_review_via_telegram") as mock_start:
        asyncio.run(handle_callback(update, context))
        assert mock_start.called
        args, kwargs = mock_start.call_args
        assert args[0] == lesson_dir
