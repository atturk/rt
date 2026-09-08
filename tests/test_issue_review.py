import os
import json
import sys
import pytest
from unittest.mock import patch, MagicMock
from rt.core.models import (
    ASRIssue, ASRLevel, ScienceIssue, ScienceType, ScienceSeverity,
    ReviewDecision, DecisionLedger, SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.state import WorkflowState

from rt.pipeline.ledger import (
    get_pending_issues, record_decision, save_ledger, load_ledger,
    find_asr_issue_by_id, find_science_issue_by_id,
    resolve_asr_accept_text, resolve_asr_reject_text,
    resolve_science_accept_text, resolve_science_reject_text
)
from rt.telegram import issue_queue as tg_queue
from rt.pipeline.issue_review import start_review_via_telegram, send_current_issue
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
                content="Questo è il testo con il target ASR e una affermazione scientifica.",
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

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.9, level=ASRLevel.GREEN, reason="r1"),
        ASRIssue(id="asr_2", segment_id="seg_000001", source_text="err2", candidate="corr2", confidence=0.7, level=ASRLevel.YELLOW, reason="r2"),
        ASRIssue(id="asr_3", segment_id="seg_000002", source_text="err3", candidate="corr3", confidence=0.4, level=ASRLevel.RED, reason="r3"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="reason 1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="reason 2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    # Senza decisioni: asr_2 (YELLOW) e asr_3 (RED) incluse (GREEN esclusa), sci_1 e sci_2 incluse
    pending_asr, pending_sci = get_pending_issues(lesson_dir)
    assert [x.id for x in pending_asr] == ["asr_2", "asr_3"]
    assert [x.id for x in pending_sci] == ["sci_1", "sci_2"]

    # Registra una decisione per asr_2 e sci_1
    record_decision(lesson_dir, "asr_2", "accepted", resolved_text="corr2")
    record_decision(lesson_dir, "sci_1", "rejected", resolved_text="claim 1")

    pending_asr2, pending_sci2 = get_pending_issues(lesson_dir)
    assert [x.id for x in pending_asr2] == ["asr_3"]
    assert [x.id for x in pending_sci2] == ["sci_2"]


def test_start_review_via_telegram_and_advance(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_y", segment_id="seg_000001", source_text="err_y", candidate="corr_y", confidence=0.8, level=ASRLevel.YELLOW, reason="mot_y"),
        ASRIssue(id="asr_r", segment_id="seg_000002", source_text="err_r", candidate="corr_r", confidence=0.5, level=ASRLevel.RED, reason="mot_r"),
    ]
    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim", reason="reason", suggested_fix="Sostituire con: \"fix\""),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    sent_messages = []

    def mock_send(cfg, text, reply_markup=None, message_thread_id=None):
        sent_messages.append({"text": text, "reply_markup": reply_markup, "thread_id": message_thread_id})
        return {"ok": True}

    monkeypatch.setattr("rt.telegram.client.send_message", mock_send)
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=123))

    start_review_via_telegram(lesson_dir, asr_issues, sci_issues)

    # 1. Verifica coda salvata
    queue = tg_queue.load_queue(lesson_dir)
    assert queue is not None
    assert queue.current_index == 0
    assert queue.issue_ids == ["asr_y", "asr_r", "sci_1"]
    assert queue.issue_types == {"asr_y": "asr", "asr_r": "asr", "sci_1": "science"}

    # 2. Verifica che sia stato mandato il primo messaggio
    assert len(sent_messages) == 1
    assert "Ambiguità ASR (YELLOW)" in sent_messages[0]["text"]
    assert sent_messages[0]["reply_markup"] is not None

    # 3. Avanza e invia seconda issue
    record_decision(lesson_dir, "asr_y", "accepted", resolved_text="corr_y")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 2
    assert "Ambiguità ASR (RED)" in sent_messages[1]["text"]

    # 4. Avanza e invia terza issue (scienza)
    record_decision(lesson_dir, "asr_r", "rejected", resolved_text="err_r")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 3
    assert "Science Critic (ERR_DOCENTE)" in sent_messages[2]["text"]

    # 5. Avanza oltre la fine: review completata e transizione a READY_TO_BUILD
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 4
    assert "✨ Review completata" in sent_messages[3]["text"]

    from rt.core.state import get_current_state
    state = get_current_state(os.path.join(lesson_dir, "info.yaml"))
    assert state == WorkflowState.READY_TO_BUILD


def test_cmd_review_channel_telegram(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_y", segment_id="seg_000001", source_text="err_y", candidate="corr_y", confidence=0.8, level=ASRLevel.YELLOW, reason="mot_y"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    start_called = []

    def mock_start(ld, asr, sci):
        start_called.append((ld, len(asr), len(sci)))

    monkeypatch.setattr("rt.pipeline.issue_review.start_review_via_telegram", mock_start)

    from types import SimpleNamespace
    args = SimpleNamespace(lesson_dir=lesson_dir, channel="telegram", auto_accept=None, auto_accept_asr=None, auto_accept_science=None)

    # builtins.input non deve mai essere chiamato
    with patch("builtins.input", side_effect=AssertionError("input() non deve essere invocato in modalità telegram")):
        result = cmd_review(args)

    assert len(start_called) == 1
    assert start_called[0] == (lesson_dir, 1, 0)
    # Regressione: la revisione è stata delegata in modo asincrono a Telegram, non è
    # ancora completa -> il chiamante (cmd_run) NON deve procedere automaticamente al build.
    assert result is False


def test_cmd_review_non_tty_stops_with_message(tmp_path, capsys, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_y", segment_id="seg_000001", source_text="err_y", candidate="corr_y", confidence=0.8, level=ASRLevel.YELLOW, reason="mot_y"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    from types import SimpleNamespace
    args = SimpleNamespace(lesson_dir=lesson_dir, channel="terminal", auto_accept=None, auto_accept_asr=None, auto_accept_science=None)

    with patch("builtins.input", side_effect=AssertionError("input() non deve essere chiamato se non-tty")):
        result = cmd_review(args)

    captured = capsys.readouterr().out
    assert "[HUMAN REVIEW REQUIRED]" in captured
    assert "Ci sono 1 issue ASR" in captured
    # Regressione: nessuna decisione è stata presa -> il chiamante (cmd_run) NON deve
    # procedere automaticamente al build (comportamento già garantito prima di questo
    # task direttamente dentro cmd_run, ora spostato dentro cmd_review: deve restare vero).
    assert result is False


def test_cmd_run_with_review_does_not_build_when_review_deferred(tmp_path, monkeypatch):
    """Regressione trovata in revisione: cmd_run(with_review=True) chiamava cmd_review()
    e procedeva SEMPRE al build subito dopo, a prescindere dal fatto che la revisione
    fosse stata effettivamente completata. Con canale Telegram (o terminale non-tty),
    cmd_review() delega/si ferma e ritorna False: cmd_run() deve fermarsi anche lui,
    senza chiamare run_build(), finché l'utente non lancia 'rt build' a mano."""
    import argparse
    from rt.cli import cmd_run

    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    build_called = []

    def fake_run_build(*a, **kw):
        build_called.append((a, kw))
        return {"skipped": False, "rielaborato": "x", "pre_elaborato": "x",
                "revisioni_asr": "x", "errori_concettuali": "x", "problemi_scientifici": "x"}

    args = argparse.Namespace(
        input=lesson_dir, force=False, mock=True, with_review=True, channel="telegram",
        date=None, materia=None, argomenti=None, dest_dir=None, model=None,
        skip_transcribe=False, auto_accept=False, rename=False,
    )

    with patch("rt.cli.run_prepare", return_value={"skipped": True, "segment_count": 1, "duration_seconds": 1.0}), \
         patch("rt.cli.run_outline", return_value={"skipped": True, "validation_report": {"units_count": 1, "coverage_percentage": 100}}), \
         patch("rt.cli.confirm_or_revise_outline", return_value=None), \
         patch("rt.cli.run_rewrite", return_value={"skipped": True, "total_units": 1, "processed_units": 1}), \
         patch("rt.cli.run_review_asr", return_value={"skipped": True, "total_issues": 1, "green_auto_applied": 0, "yellow_review_queue": 1, "red_human_required": 0}), \
         patch("rt.cli.run_review_science", return_value={"skipped": True, "total_science_issues": 0, "docente_issues": 0, "reconstruction_issues": 0, "science_checks": 0}), \
         patch("rt.cli.cmd_review", return_value=False) as mock_cmd_review, \
         patch("rt.cli.run_build", side_effect=fake_run_build):
        cmd_run(args)

    mock_cmd_review.assert_called_once()
    assert build_called == [], "run_build() non deve essere chiamato se cmd_review() segnala che la revisione non è ancora completa (return False)"
