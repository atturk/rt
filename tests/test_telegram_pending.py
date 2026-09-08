import os
import pytest
from rt.core.models import TelegramPendingStatus
from rt.telegram.pending import (
    create_pending,
    load_pending,
    mark_responded,
    get_pending_path,
)


def test_telegram_pending_lifecycle(tmp_path):
    lesson_dir = str(tmp_path)
    
    # 1. Nessun pending all'inizio
    assert load_pending(lesson_dir) is None
    
    # 2. Creazione pending
    summary_text = "📋 <b>Titolo Lezione</b>\n1. Macro\n  1.1 Unit"
    state = create_pending(
        lesson_dir=lesson_dir,
        round_=1,
        short_id="abc1234567",
        outline_summary_text=summary_text,
    )
    assert state.round == 1
    assert state.short_id == "abc1234567"
    assert state.status == TelegramPendingStatus.PENDING
    assert state.outline_summary_text == summary_text
    assert state.feedback_text is None
    assert state.responded_at is None
    assert state.responded_via is None

    # Nessun file .tmp residuo
    assert not os.path.exists(get_pending_path(lesson_dir) + ".tmp")
    assert os.path.isfile(get_pending_path(lesson_dir))

    # 3. Load pending
    loaded = load_pending(lesson_dir)
    assert loaded is not None
    assert loaded.short_id == "abc1234567"
    assert loaded.status == TelegramPendingStatus.PENDING

    # 4. Mark responded (approved)
    updated = mark_responded(lesson_dir, status="approved", responded_via="telegram")
    assert updated.status == TelegramPendingStatus.APPROVED
    assert updated.responded_via == "telegram"
    assert updated.responded_at is not None
    assert not os.path.exists(get_pending_path(lesson_dir) + ".tmp")

    # Verifica persistenza su disco
    reloaded = load_pending(lesson_dir)
    assert reloaded.status == TelegramPendingStatus.APPROVED
    assert reloaded.responded_via == "telegram"


def test_telegram_pending_changes_requested(tmp_path):
    lesson_dir = str(tmp_path)
    create_pending(
        lesson_dir=lesson_dir,
        round_=2,
        short_id="xyz9876543",
        outline_summary_text="summary",
    )
    
    updated = mark_responded(
        lesson_dir,
        status="changes_requested",
        responded_via="telegram",
        feedback_text="Dividi la sezione 2 in due parti",
    )
    assert updated.status == TelegramPendingStatus.CHANGES_REQUESTED
    assert updated.feedback_text == "Dividi la sezione 2 in due parti"
    assert updated.responded_via == "telegram"


def test_mark_responded_raises_file_not_found(tmp_path):
    lesson_dir = str(tmp_path)
    with pytest.raises(FileNotFoundError, match="telegram_pending.json non trovato"):
        mark_responded(lesson_dir, status="approved", responded_via="telegram")
