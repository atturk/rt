import os
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.outline_review import confirm_or_revise_outline
from rt.telegram.pending import create_pending, load_pending, mark_responded
from rt.telegram.config import TelegramConfig


@pytest.fixture
def synthetic_outline_lesson(tmp_path):
    lesson_dir = str(tmp_path / "test_lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    
    info_content = """data: '2026-09-08'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: 'test_lesson'
file_audio: test.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)
        
    transcript_content = """---
data: '2026-09-08'
materia: BIOCHIMICA
---

*00:02*
Introduzione alla lezione di biochimica sui lipidi.

*00:20*
I lipidi sono depositati nel tessuto adiposo.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)
        
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    return lesson_dir


def test_terminal_approve_direct(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    with patch("builtins.input", side_effect=["A"]) as mock_input:
        confirm_or_revise_outline(lesson_dir, channel="terminal", force_mock=True)
        assert mock_input.call_count == 1


def test_terminal_changes_requested_then_approve(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    # M -> feedback -> A
    with patch("builtins.input", side_effect=["M", "Aggiungi dettagli sulle lipasi", "A"]) as mock_input:
        with patch("rt.pipeline.outline_review.run_outline_revision", wraps=__import__("rt.pipeline.outline", fromlist=["run_outline_revision"]).run_outline_revision) as mock_rev:
            confirm_or_revise_outline(lesson_dir, channel="terminal", force_mock=True)
            assert mock_input.call_count == 3
            assert mock_rev.call_count == 1


def test_gating_rule_skips_when_rewrite_valid(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)

    # Con rewrite VALID, input() non deve MAI essere chiamato
    with patch("builtins.input", side_effect=AssertionError("input() non doveva essere chiamato")):
        confirm_or_revise_outline(lesson_dir, channel="terminal", force=False, force_mock=True)


def test_gating_rule_bypassed_with_force(synthetic_outline_lesson):
    lesson_dir = synthetic_outline_lesson
    run_rewrite(lesson_dir, force_mock=True)

    # Con force=True, la conferma viene richiesta comunque
    with patch("builtins.input", side_effect=["A"]) as mock_input:
        confirm_or_revise_outline(lesson_dir, channel="terminal", force=True, force_mock=True)
        assert mock_input.call_count == 1


def test_telegram_fallback_when_config_missing(synthetic_outline_lesson, monkeypatch):
    lesson_dir = synthetic_outline_lesson
    monkeypatch.delenv("RT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID", raising=False)

    with patch("builtins.input", side_effect=["A"]) as mock_input:
        confirm_or_revise_outline(lesson_dir, channel="telegram", force_mock=True)
        assert mock_input.call_count == 1


def test_telegram_fallback_when_api_error(synthetic_outline_lesson, monkeypatch, tmp_path):
    lesson_dir = synthetic_outline_lesson
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    state_dir = str(tmp_path / ".rt_telegram")
    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.poll_interval_seconds = 0.01
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        with patch("rt.telegram.client.send_message", side_effect=__import__("rt.telegram.client", fromlist=["TelegramAPIError"]).TelegramAPIError("Network error")):
            with patch("builtins.input", side_effect=["A"]) as mock_input:
                confirm_or_revise_outline(lesson_dir, channel="telegram", force_mock=True)
                assert mock_input.call_count == 1


def test_telegram_polling_approved(synthetic_outline_lesson, monkeypatch, tmp_path):
    lesson_dir = synthetic_outline_lesson
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    state_dir = str(tmp_path / ".rt_telegram")
    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.poll_interval_seconds = 0.01
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        with patch("rt.telegram.client.send_message", return_value={"message_id": 1}):
            # Simula che dopo un breve intervallo lo stato diventa approved
            def mock_sleep(sec):
                # Simula la risposta del daemon
                mark_responded(lesson_dir, status="approved", responded_via="telegram")

            with patch("time.sleep", side_effect=mock_sleep):
                confirm_or_revise_outline(lesson_dir, channel="telegram", force_mock=True)

            state = load_pending(lesson_dir)
            assert state.status == "approved"


def test_telegram_resume_applies_stale_changes_requested_feedback(synthetic_outline_lesson, monkeypatch, tmp_path):
    """Regressione: se il daemon ha già scritto status='changes_requested' (l'utente ha
    già mandato il feedback su Telegram) ma il processo 'rt run' viene interrotto prima
    di consumarlo (Ctrl+C, crash, terminale chiuso), un riavvio di confirm_or_revise_outline
    deve applicare SUBITO quel feedback invece di ignorarlo silenziosamente e rimandare
    l'outline non rivista con un nuovo round (bug riscontrato in revisione: il feedback
    veniva perso senza alcun errore visibile)."""
    lesson_dir = synthetic_outline_lesson
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    create_pending(lesson_dir, round_=1, short_id="deadbeef01", outline_summary_text="old summary")
    mark_responded(
        lesson_dir, status="changes_requested", responded_via="telegram",
        feedback_text="Accorpa le prime due unità didattiche"
    )

    state_dir = str(tmp_path / ".rt_telegram")
    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.poll_interval_seconds = 0.01
        cfg_obj.telegram.topics = {}
        mock_cfg.return_value = cfg_obj

        sent_messages = []
        real_run_outline_revision = __import__("rt.pipeline.outline", fromlist=["run_outline_revision"]).run_outline_revision
        with patch("rt.telegram.client.send_message", side_effect=lambda cfg, text, reply_markup=None, message_thread_id=None: sent_messages.append(text) or {"message_id": 1}), \
             patch("rt.pipeline.outline_review.run_outline_revision", wraps=real_run_outline_revision) as mock_rev, \
             patch("time.sleep", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                confirm_or_revise_outline(lesson_dir, channel="telegram", force_mock=True)

    # Il feedback già presente deve essere stato applicato esattamente una volta (non
    # ignorato, non riapplicato in loop), con un solo nuovo messaggio inviato (nuovo
    # round pulito) e nessuna ricorsione infinita.
    mock_rev.assert_called_once_with(lesson_dir, feedback="Accorpa le prime due unità didattiche", force_mock=True)
    assert len(sent_messages) == 1
    pending_after = load_pending(lesson_dir)
    assert pending_after.status == "pending"
    assert pending_after.round == 2
    assert pending_after.short_id != "deadbeef01"
    assert pending_after.feedback_text is None  # nuovo round pulito, non eredita il vecchio feedback già consumato


def test_telegram_outline_review_topic_routing(synthetic_outline_lesson, monkeypatch, tmp_path):
    lesson_dir = synthetic_outline_lesson
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "123456")

    state_dir = str(tmp_path / ".rt_telegram")
    with patch("rt.core.config.load_config") as mock_cfg:
        cfg_obj = MagicMock()
        cfg_obj.telegram.state_dir = state_dir
        cfg_obj.telegram.poll_interval_seconds = 0.01
        cfg_obj.telegram.topics = {"BIOCHIMICA": 5}
        mock_cfg.return_value = cfg_obj

        with patch("rt.telegram.client.send_message", return_value={"message_id": 1}) as mock_send, \
             patch("time.sleep", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                confirm_or_revise_outline(lesson_dir, channel="telegram", force_mock=True)

            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args
            assert kwargs.get("message_thread_id") == 5

