"""
Test per Task 73: concurrent_updates nel demone Telegram e locking del recall bank.
"""
import os
import time
import threading
from unittest.mock import patch, MagicMock
import pytest

from rt.core.models import RecallBank, RecallQuestion, RecallQuestionStatus, RecallQuestionType, RecallAnswer
from rt.pipeline.recall import (
    load_recall_bank,
    save_recall_bank,
    recall_bank_lock,
    get_recall_bank_lock_path,
    record_recall_answer,
    get_next_pending_question,
)

from rt.core.filelock import acquire_file_lock, release_file_lock, file_lock


def test_daemon_concurrent_updates_flag():
    """Verifica che run_daemon configuri concurrent_updates(True) sull'ApplicationBuilder."""
    with patch("rt.telegram.daemon.load_telegram_config") as mock_tg_cfg, \
         patch("rt.telegram.daemon.load_config") as mock_cfg, \
         patch("rt.telegram.daemon.Application.builder") as mock_builder_factory, \
         patch("rt.telegram.daemon_status.write_daemon_pid"), \
         patch("rt.telegram.daemon_status.remove_daemon_pid"):

        mock_tg_cfg.return_value.bot_token = "dummy_token"
        mock_cfg.return_value.telegram.state_dir = "/tmp/state"

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.concurrent_updates.return_value = mock_builder
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app
        mock_builder_factory.return_value = mock_builder

        from rt.telegram.daemon import run_daemon
        run_daemon(state_dir="/tmp/test_state")

        mock_builder.concurrent_updates.assert_called_once_with(True)


def test_file_lock_stale_recovery(tmp_path):
    """Verifica che un lock stale (> 30s) venga rimosso e riacquisito con successo."""
    lock_file = str(tmp_path / "test.lock")
    # Crea un file lock artificiale con data nel passato (60 secondi fa)
    with open(lock_file, "w") as f:
        f.write("stale")
    past_time = time.time() - 60
    os.utime(lock_file, (past_time, past_time))

    # L'acquisizione del lock deve avere successo e rimuovere il lock vecchio
    with file_lock(lock_file, stale_sec=30.0):
        assert os.path.exists(lock_file)

    assert not os.path.exists(lock_file)


def test_concurrent_recall_bank_updates_no_lost_updates(tmp_path):
    """Simula due thread concorrenti che aggiungono risposte diverse al recall bank.
    Garantisce che il locking prevenga lost updates."""
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    # Inizializza bank con 2 domande
    q1 = RecallQuestion(id="q1", type=RecallQuestionType.MIRATA, question_text="Domanda 1", unit_ids=["u1"])
    q2 = RecallQuestion(id="q2", type=RecallQuestionType.MIRATA, question_text="Domanda 2", unit_ids=["u1"])
    bank = RecallBank(questions=[q1, q2])
    save_recall_bank(bank, lesson_dir)

    errors = []

    def answer_worker(qid: str, text: str):
        try:
            record_recall_answer(lesson_dir, qid, text, is_voice=False, evaluation="OK")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=answer_worker, args=("q1", "Risposta 1"))
    t2 = threading.Thread(target=answer_worker, args=("q2", "Risposta 2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Errori nei worker concorrenti: {errors}"

    # Verifica stato finale: entrambe le domande devono essere ANSWERED e avere relative risposte
    final_bank = load_recall_bank(lesson_dir)
    assert len(final_bank.answers) == 2
    answered_qids = {a.question_id for a in final_bank.answers}
    assert answered_qids == {"q1", "q2"}
    for q in final_bank.questions:
        assert q.status == RecallQuestionStatus.ANSWERED
