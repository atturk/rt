import os
import json
import sys
import pytest
from unittest.mock import patch, MagicMock
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    ReviewDecision, DecisionLedger, SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.state import WorkflowState

from rt.pipeline.ledger import (
    get_pending_issues, record_decision, revert_last_decision, save_ledger, load_ledger,
    find_science_issue_by_id,
    resolve_science_accept_text, resolve_science_reject_text
)
from rt.telegram import issue_queue as tg_queue
from rt.pipeline.issue_review import start_review_via_telegram, send_current_issue, run_interactive_review
from rt.telegram.config import TelegramConfig
from rt.cli import cmd_review


def _create_sample_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    # segments.json
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=2,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="Ciao mondo"),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Seconda parte"),
        ]
    )

    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    # draft.json
    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="U1",
                title="Introduzione",
                content="Questo è il testo con una affermazione scientifica.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                key_concepts=[]
            )
        ]
    )

    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    # info.yaml
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\n")


def test_get_pending_issues(tmp_path):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="reason 1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="reason 2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    pending_asr, pending_sci = get_pending_issues(lesson_dir)
    assert pending_asr == []
    assert [x.id for x in pending_sci] == ["sci_1", "sci_2"]

    # Registra una decisione per sci_1
    record_decision(lesson_dir, "sci_1", "rejected", resolved_text="claim 1")

    pending_asr2, pending_sci2 = get_pending_issues(lesson_dir)
    assert pending_asr2 == []
    assert [x.id for x in pending_sci2] == ["sci_2"]


def test_ledger_append_only_and_revert(tmp_path):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    # Registra prima decisione
    d1 = record_decision(lesson_dir, "iss_1", "accepted", resolved_text="val1")
    ledger1 = load_ledger(lesson_dir)
    assert len(ledger1.decisions) == 1
    assert ledger1.decisions[0].resolved_text == "val1"

    # Registra seconda decisione per la stessa issue -> append-only, len diventa 2
    d2 = record_decision(lesson_dir, "iss_1", "edited", resolved_text="val2")
    ledger2 = load_ledger(lesson_dir)
    assert len(ledger2.decisions) == 2
    assert ledger2.decisions[0].resolved_text == "val1"
    assert ledger2.decisions[1].resolved_text == "val2"

    # Revert: rimuove l'ultima (val2)
    assert revert_last_decision(lesson_dir, "iss_1") is True
    ledger3 = load_ledger(lesson_dir)
    assert len(ledger3.decisions) == 1
    assert ledger3.decisions[0].resolved_text == "val1"

    # Revert ancora: rimuove la prima (val1)
    assert revert_last_decision(lesson_dir, "iss_1") is True
    ledger4 = load_ledger(lesson_dir)
    assert len(ledger4.decisions) == 0

    # Revert su issue inesistente -> False
    assert revert_last_decision(lesson_dir, "iss_1") is False


def test_start_review_via_telegram_and_advance(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim", reason="reason", suggested_fix="Sostituire con: \"fix\""),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    sent_messages = []

    def mock_send(cfg, text, reply_markup=None, message_thread_id=None):
        mid = 100 + len(sent_messages)
        sent_messages.append({"text": text, "reply_markup": reply_markup, "thread_id": message_thread_id, "message_id": mid})
        return {"ok": True, "message_id": mid}

    monkeypatch.setattr("rt.telegram.client.send_message", mock_send)
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=123))

    from rt.telegram import session as tg_session
    from rt.core.config import load_config
    runtime_cfg = load_config().telegram

    start_review_via_telegram(lesson_dir, sci_to_review=sci_issues)

    # 1. Verifica coda salvata
    queue = tg_queue.load_queue(lesson_dir)
    assert queue is not None
    assert queue.current_index == 0
    assert queue.issue_ids == ["sci_1"]

    # 2. Verifica che sia stato mandato il primo messaggio e tracciato il message_id
    assert len(sent_messages) == 1
    assert "Science Critic (ERR_DOCENTE)" in sent_messages[0]["text"]
    assert sent_messages[0]["reply_markup"] is not None
    sess = tg_session.get_active_session(runtime_cfg.state_dir, 123, None)
    assert sess is not None
    assert sess["message_id"] == 100

    # 3. Avanza oltre la fine: review completata e transizione a READY_TO_BUILD
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 2
    assert "✨ Review completata" in sent_messages[1]["text"]
    assert tg_session.get_active_session(runtime_cfg.state_dir, 123, None) is None

    from rt.core.state import get_current_state
    state = get_current_state(os.path.join(lesson_dir, "info.yaml"))
    assert state == WorkflowState.READY_TO_BUILD


def test_telegram_callback_indietro(tmp_path, monkeypatch):
    from rt.telegram.daemon import _handle_issue_callback
    from rt.telegram import registry
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="r1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="r2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    # Coda creata con index 1 (prima issue già decisa)
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix 1")
    q = tg_queue.create_queue(lesson_dir, ["sci_1", "sci_2"], {"sci_1": "science", "sci_2": "science"})
    q.current_index = 1
    tg_queue._save(q, lesson_dir)

    state_dir = str(tmp_path / "tg_state")
    short_id = registry.register_pending(lesson_dir, round_=1, kind="issue_review", state_dir=state_dir, extra={"issue_id": "sci_2", "issue_type": "science"})

    query = MagicMock()
    query.answer = MagicMock(return_value=None)
    import asyncio
    query.answer = MagicMock(side_effect=lambda *a, **kw: asyncio.sleep(0))
    query.edit_message_reply_markup = MagicMock(side_effect=lambda *a, **kw: asyncio.sleep(0))
    update = MagicMock()
    update.callback_query = query
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send:
        asyncio.run(_handle_issue_callback(update, context, "ib", short_id))

    # current_index decrements to 0
    updated_q = tg_queue.load_queue(lesson_dir)
    assert updated_q.current_index == 0

    # Decision for sci_1 should have been reverted
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 0


def test_interactive_terminal_backward_navigation(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="r1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="r2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    inputs = iter(["b", "a", "b", "r", "a"])
    with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    ledger = load_ledger(lesson_dir)
    decisions_map = {d.issue_id: d for d in ledger.decisions}
    assert decisions_map["sci_1"].decision == "rejected"
    assert decisions_map["sci_2"].decision == "accepted"


def test_history_mode_terminal_and_telegram(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="r1", suggested_fix="fix 1"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix 1")

    # 1. Telegram con history -> avviso e fallback a pendenti (che sono 0 -> True immediato)
    res_tg = run_interactive_review(lesson_dir, "science", channel="telegram", history=True)
    assert res_tg is True
    out = capsys.readouterr().out
    assert "⚠️  La modalità --history è disponibile solo da terminale" in out

    # 2. Terminal con history -> mostra issue già decisa e ri-decisione aggiunge nuova voce
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch("builtins.input", side_effect=["r"]):
        res_term = run_interactive_review(lesson_dir, "science", channel="terminal", history=True)

    assert res_term is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[1].decision == "rejected"


def test_history_mode_backward_science_does_not_revert_untouched_historical_decision(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="reason 1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="reason 2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix 1")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    inputs = iter(["s", "b", "q"])
    with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
        res = run_interactive_review(lesson_dir, "science", channel="terminal", history=True)

    assert res is False
    ledger_after = load_ledger(lesson_dir)
    assert len(ledger_after.decisions) == 1
    assert ledger_after.decisions[0].issue_id == "sci_1"
    assert ledger_after.decisions[0].decision == "accepted"


def test_cmd_run_with_review_does_not_build_when_review_deferred(tmp_path, monkeypatch):
    import argparse
    from rt.cli import cmd_run

    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    build_called = []

    def fake_run_build(*a, **kw):
        build_called.append((a, kw))
        return {"skipped": False, "rielaborato": "x", "pre_elaborato": "x",
                "errori_concettuali": "x", "problemi_scientifici": "x"}

    args = argparse.Namespace(
        input=lesson_dir, force=False, mock=True, with_review=True, channel="telegram",
        date=None, materia=None, argomenti=None, dest_dir=None, model=None,
        skip_transcribe=False, auto_accept=False, rename=False,
    )

    with patch("rt.cli.run_prepare", return_value={"skipped": True, "segment_count": 1, "duration_seconds": 1.0}), \
         patch("rt.cli.run_outline", return_value={"skipped": True, "validation_report": {"units_count": 1, "coverage_percentage": 100}}), \
         patch("rt.cli.confirm_or_revise_outline", return_value=None), \
         patch("rt.cli.run_rewrite", return_value={"skipped": True, "total_units": 1, "processed_units": 1}), \
         patch("rt.cli.run_review", return_value={"skipped": True, "total_science_issues": 1, "docente_issues": 1, "reconstruction_issues": 0, "science_checks": 0}), \
         patch("rt.cli.run_interactive_review", return_value=False) as mock_review, \
         patch("rt.cli.run_build", side_effect=fake_run_build):
        cmd_run(args)

    mock_review.assert_called_once()
    assert build_called == [], "run_build() non deve essere chiamato se run_interactive_review() ritorna False"



