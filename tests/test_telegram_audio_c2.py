"""
tests/test_telegram_audio_c2.py
Test di accettazione per la Fase C2:
- Invio file vocale Telegram via send_voice (multipart + retry 429)
- Deduplica audio in Telegram review (audio_sent)
- Gestione issue senza audio
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rt.telegram.config import TelegramConfig
from rt.telegram.client import send_voice, TelegramAPIError
from rt.telegram.audio_sent import get_sent_audio, record_sent_audio
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.manifest import init_or_update_manifest
from rt.telegram import issue_queue as tg_queue
from rt.pipeline.issue_review import send_current_issue


# ---------------------------------------------------------------------------
# 1. send_voice multipart & 429 retry tests
# ---------------------------------------------------------------------------

def test_send_voice_multipart_success(tmp_path):
    cfg = TelegramConfig(bot_token="TEST_BOT_TOKEN", chat_id=987654)
    fake_voice = str(tmp_path / "clip.mp3")
    with open(fake_voice, "wb") as f:
        f.write(b"AUDIO_VOICE_BYTES")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "message_id": 42,
            "voice": {"file_id": "VOICE_FILE_123"}
        }
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = send_voice(
            cfg,
            voice_path=fake_voice,
            caption="Audio prova",
            reply_to_message_id=10,
            message_thread_id=55,
            timeout=20.0
        )

        assert res["message_id"] == 42
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "https://api.telegram.org/botTEST_BOT_TOKEN/sendVoice"
        assert call_kwargs["data"]["chat_id"] == 987654
        assert call_kwargs["data"]["caption"] == "Audio prova"
        assert call_kwargs["data"]["reply_to_message_id"] == 10
        assert call_kwargs["data"]["message_thread_id"] == 55
        assert "voice" in call_kwargs["files"]
        assert call_kwargs["timeout"] == 20.0


def test_send_voice_retry_on_429(tmp_path):
    cfg = TelegramConfig(bot_token="TEST_BOT_TOKEN", chat_id=987654)
    fake_voice = str(tmp_path / "clip.mp3")
    with open(fake_voice, "wb") as f:
        f.write(b"AUDIO_VOICE_BYTES")

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests",
        "parameters": {"retry_after": 0.01}
    }

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {
        "ok": True,
        "result": {"message_id": 99}
    }

    with patch("requests.post", side_effect=[resp_429, resp_ok]) as mock_post, \
         patch("time.sleep") as mock_sleep:
        res = send_voice(cfg, fake_voice)
        assert res["message_id"] == 99
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(0.01)


def test_send_voice_error_after_retries(tmp_path):
    cfg = TelegramConfig(bot_token="TEST_BOT_TOKEN", chat_id=987654)
    fake_voice = str(tmp_path / "clip.mp3")
    with open(fake_voice, "wb") as f:
        f.write(b"AUDIO_VOICE_BYTES")

    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.json.return_value = {
        "ok": False,
        "error_code": 400,
        "description": "Bad Request: wrong format"
    }

    with patch("requests.post", return_value=resp_400):
        with pytest.raises(TelegramAPIError, match="Bad Request"):
            send_voice(cfg, fake_voice)


# ---------------------------------------------------------------------------
# 2. telegram_audio_sent module tests
# ---------------------------------------------------------------------------

def test_audio_sent_tracking(tmp_path):
    lesson_dir = str(tmp_path)
    assert get_sent_audio(lesson_dir, "seg_001", "seg_002") is None

    record_sent_audio(lesson_dir, "seg_001", "seg_002", message_id=1234)

    sent = get_sent_audio(lesson_dir, "seg_001", "seg_002")
    assert sent is not None
    assert sent["message_id"] == 1234
    assert "recorded_at" in sent

    # Altro range non presente
    assert get_sent_audio(lesson_dir, "seg_002", "seg_003") is None


# ---------------------------------------------------------------------------
# 3. send_current_issue integration: deduplication and missing audio handling
# ---------------------------------------------------------------------------

def _setup_telegram_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="audio.mp3",
        audio_duration_seconds=120.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Parte 1"),
            Segment(id="seg_000002", index=2, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="Parte 2"),
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    audio_path = os.path.join(lesson_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"AUDIO_DATA")

    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="L1",
        date="2026-09-09",
        subject="Fisica",
        current_state="DRAFT_VALIDATED",
        audio_file="audio.mp3",
    )

    draft = Draft(
        schema_version="1.0",
        lesson_id="L1",
        units=[
            DraftUnit(
                unit_id="U1",
                title="Unità 1",
                content="Contenuto unità 1.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                key_concepts=[]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)


def test_telegram_review_science_audio_deduplication(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_telegram_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            claim="Claim 1",
            reason="Reason 1",
            suggested_fix="Fix 1"
        ),
        ScienceIssue(
            id="sci_002",
            type=ScienceType.SCIENCE_CHECK,
            severity=ScienceSeverity.LOW,
            unit_id="U1",
            claim="Claim 2",
            reason="Reason 2",
            suggested_fix="Fix 2"
        ),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    tg_queue.create_queue(lesson_dir, ["sci_001", "sci_002"], {"sci_001": "science", "sci_002": "science"})

    cfg = TelegramConfig(bot_token="MOCK_TOKEN", chat_id=12345)

    with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
         patch("rt.telegram.client.send_message") as mock_send_msg, \
         patch("rt.telegram.client.send_voice") as mock_send_voice, \
         patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/clip.mp3") as mock_cut:

        mock_send_msg.return_value = {"message_id": 100}
        mock_send_voice.return_value = {"message_id": 101}

        # 1. Prima issue sci_001 -> deve tagliare e inviare audio
        send_current_issue(lesson_dir)

        assert mock_send_msg.call_count == 1
        assert mock_cut.call_count == 1
        assert mock_send_voice.call_count == 1
        mock_send_voice.assert_called_once_with(
            cfg,
            voice_path="/tmp/clip.mp3",
            caption="🎧 Audio SCIENCE: sci_001",
            message_thread_id=None
        )

        # Avanza coda alla seconda issue (stessa unità U1)
        tg_queue.advance(lesson_dir)

        # 2. Seconda issue sci_002 -> NON deve tagliare/inviare voice, ma mandare reply testuale a 101
        send_current_issue(lesson_dir)

        assert mock_cut.call_count == 1  # non incrementato
        assert mock_send_voice.call_count == 1  # non incrementato
        # mock_send_msg ha inviato: 1) issue 1 testo, 2) issue 2 testo, 3) reply audio già inviato
        assert mock_send_msg.call_count == 3
        last_msg_call = mock_send_msg.call_args_list[-1]
        assert "Audio già inviato qui sopra" in last_msg_call[1]["text"]
        assert last_msg_call[1]["reply_to_message_id"] == 101


def test_telegram_review_missing_audio_does_not_fail(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_telegram_lesson(lesson_dir)

    # Rimuovi file audio
    audio_file = os.path.join(lesson_dir, "audio.mp3")
    if os.path.exists(audio_file):
        os.remove(audio_file)

    asr_issues = [
        ASRIssue(
            id="asr_001",
            segment_id="seg_000001",
            source_text="errore",
            candidate="correzione",
            confidence=0.8,
            level=ASRLevel.YELLOW,
            reason="test"
        )
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    tg_queue.create_queue(lesson_dir, ["asr_001"], {"asr_001": "asr"})
    cfg = TelegramConfig(bot_token="MOCK_TOKEN", chat_id=12345)

    with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
         patch("rt.telegram.client.send_message") as mock_send_msg, \
         patch("rt.telegram.client.send_voice") as mock_send_voice, \
         patch("rt.pipeline.issue_review.cut_clip") as mock_cut:

        mock_send_msg.return_value = {"message_id": 200}

        send_current_issue(lesson_dir)

        # Il messaggio testuale della issue arriva comunque
        assert mock_send_msg.call_count == 1
        # Nessun taglio né invio vocale
        assert mock_cut.call_count == 0
        assert mock_send_voice.call_count == 0
