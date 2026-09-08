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
    get_pending_issues, record_decision, revert_last_decision, save_ledger, load_ledger,
    apply_asr_decisions_to_text,
    find_asr_issue_by_id, find_science_issue_by_id,
    resolve_asr_accept_text, resolve_asr_reject_text,
    resolve_science_accept_text, resolve_science_reject_text
)
from rt.telegram import issue_queue as tg_queue
from rt.pipeline.issue_review import start_review_via_telegram, send_current_issue, run_interactive_review
from rt.telegram.config import TelegramConfig
from rt.cli import cmd_review_asr, cmd_review_science


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
        mid = 100 + len(sent_messages)
        sent_messages.append({"text": text, "reply_markup": reply_markup, "thread_id": message_thread_id, "message_id": mid})
        return {"ok": True, "message_id": mid}

    monkeypatch.setattr("rt.telegram.client.send_message", mock_send)
    monkeypatch.setattr("rt.telegram.config.load_telegram_config", lambda: TelegramConfig(bot_token="tok", chat_id=123))

    from rt.telegram import session as tg_session
    from rt.core.config import load_config
    runtime_cfg = load_config().telegram

    start_review_via_telegram(lesson_dir, asr_issues, sci_issues)

    # 1. Verifica coda salvata
    queue = tg_queue.load_queue(lesson_dir)
    assert queue is not None
    assert queue.current_index == 0
    assert queue.issue_ids == ["asr_y", "asr_r", "sci_1"]
    assert queue.issue_types == {"asr_y": "asr", "asr_r": "asr", "sci_1": "science"}

    # 2. Verifica che sia stato mandato il primo messaggio e tracciato il message_id
    assert len(sent_messages) == 1
    assert "Ambiguità ASR (YELLOW)" in sent_messages[0]["text"]
    assert sent_messages[0]["reply_markup"] is not None
    sess = tg_session.get_active_session(runtime_cfg.state_dir, 123, None)
    assert sess is not None
    assert sess["message_id"] == 100

    # 3. Avanza e invia seconda issue
    record_decision(lesson_dir, "asr_y", "accepted", resolved_text="corr_y")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 2
    assert "Ambiguità ASR (RED)" in sent_messages[1]["text"]
    sess = tg_session.get_active_session(runtime_cfg.state_dir, 123, None)
    assert sess["message_id"] == 101

    # 4. Avanza e invia terza issue (scienza)
    record_decision(lesson_dir, "asr_r", "rejected", resolved_text="err_r")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 3
    assert "Science Critic (ERR_DOCENTE)" in sent_messages[2]["text"]
    sess = tg_session.get_active_session(runtime_cfg.state_dir, 123, None)
    assert sess["message_id"] == 102

    # 5. Avanza oltre la fine: review completata e transizione a READY_TO_BUILD
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix")
    tg_queue.advance(lesson_dir)
    send_current_issue(lesson_dir)

    assert len(sent_messages) == 4
    assert "✨ Review completata" in sent_messages[3]["text"]
    assert tg_session.get_active_session(runtime_cfg.state_dir, 123, None) is None

    from rt.core.state import get_current_state
    state = get_current_state(os.path.join(lesson_dir, "info.yaml"))
    assert state == WorkflowState.READY_TO_BUILD


def test_telegram_callback_indietro(tmp_path, monkeypatch):
    from rt.telegram.daemon import _handle_issue_callback
    from rt.telegram import registry
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.8, level=ASRLevel.YELLOW, reason="m1"),
        ASRIssue(id="asr_2", segment_id="seg_000002", source_text="err2", candidate="corr2", confidence=0.5, level=ASRLevel.RED, reason="m2"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    # Coda creata con index 1 (prima issue già decisa)
    record_decision(lesson_dir, "asr_1", "accepted", resolved_text="corr1")
    q = tg_queue.create_queue(lesson_dir, ["asr_1", "asr_2"], {"asr_1": "asr", "asr_2": "asr"})
    q.current_index = 1
    tg_queue._save(q, lesson_dir)

    state_dir = str(tmp_path / "tg_state")
    short_id = registry.register_pending(lesson_dir, round_=1, kind="issue_review", state_dir=state_dir, extra={"issue_id": "asr_2", "issue_type": "asr"})

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

    # Decision for asr_1 should have been reverted
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 0


def test_interactive_terminal_backward_navigation(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.8, level=ASRLevel.YELLOW, reason="m1"),
        ASRIssue(id="asr_2", segment_id="seg_000002", source_text="err2", candidate="corr2", confidence=0.5, level=ASRLevel.RED, reason="m2"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Simula input utente:
    # 1. Su asr_1 -> 'b' (prova indietro al primo elemento -> non regredisce)
    # 2. Su asr_1 -> 'a' (accetta)
    # 3. Su asr_2 -> 'b' (torna indietro -> revert asr_1 e ripropone asr_1)
    # 4. Su asr_1 ripresentata -> 'r' (rifiuta invece di accettare)
    # 5. Su asr_2 -> 'a' (accetta)
    inputs = iter(["b", "a", "b", "r", "a"])
    with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    ledger = load_ledger(lesson_dir)
    # Due decisioni finali registrate
    decisions_map = {d.issue_id: d for d in ledger.decisions}
    assert decisions_map["asr_1"].decision == "rejected"
    assert decisions_map["asr_2"].decision == "accepted"


def test_history_mode_terminal_and_telegram(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.8, level=ASRLevel.YELLOW, reason="m1"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    # Già decisa nel ledger
    record_decision(lesson_dir, "asr_1", "accepted", resolved_text="corr1")

    # 1. Telegram con history -> avviso e fallback a pendenti (che sono 0 -> True immediato)
    res_tg = run_interactive_review(lesson_dir, "asr", channel="telegram", history=True)
    assert res_tg is True
    out = capsys.readouterr().out
    assert "⚠️  La modalità --history è disponibile solo da terminale" in out

    # 2. Terminal con history -> mostra issue già decisa e ri-decisione aggiunge nuova voce
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch("builtins.input", side_effect=["r"]):
        res_term = run_interactive_review(lesson_dir, "asr", channel="terminal", history=True)

    assert res_term is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[1].decision == "rejected"


def test_history_mode_backward_does_not_revert_untouched_historical_decision(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.8, level=ASRLevel.YELLOW, reason="m1"),
        ASRIssue(id="asr_2", segment_id="seg_000002", source_text="err2", candidate="corr2", confidence=0.5, level=ASRLevel.RED, reason="m2"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    # Decisione storica preesistente per asr_1
    record_decision(lesson_dir, "asr_1", "accepted", resolved_text="corr1")
    ledger_before = load_ledger(lesson_dir)
    assert len(ledger_before.decisions) == 1

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # In sessione --history:
    # 1. Su asr_1 -> 's' (salta senza toccare la decisione storica)
    # 2. Su asr_2 -> 'b' (torna indietro a asr_1)
    # 3. Su asr_1 ripresentata -> 's' (salta di nuovo)
    # 4. Su asr_2 -> 'q' (esci)
    inputs = iter(["s", "b", "s", "q"])
    with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal", history=True)

    assert res is False  # interrupted with 'q'
    ledger_after = load_ledger(lesson_dir)
    # La decisione storica per asr_1 deve restare intatta
    assert len(ledger_after.decisions) == 1
    assert ledger_after.decisions[0].issue_id == "asr_1"
    assert ledger_after.decisions[0].decision == "accepted"
    assert ledger_after.decisions[0].resolved_text == "corr1"


def test_history_mode_backward_science_does_not_revert_untouched_historical_decision(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    sci_issues = [
        ScienceIssue(id="sci_1", type=ScienceType.ERR_DOCENTE, severity=ScienceSeverity.HIGH, unit_id="U1", claim="claim 1", reason="reason 1", suggested_fix="fix 1"),
        ScienceIssue(id="sci_2", type=ScienceType.SCIENCE_CHECK, severity=ScienceSeverity.LOW, unit_id="U1", claim="claim 2", reason="reason 2", suggested_fix="fix 2"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    # Decisione storica preesistente per sci_1
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="fix 1")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # In sessione --history su science:
    # 1. Su sci_1 -> 's' (salta)
    # 2. Su sci_2 -> 'b' (indietro a sci_1)
    # 3. Su sci_1 -> 'q' (esci)
    inputs = iter(["s", "b", "q"])
    with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
        res = run_interactive_review(lesson_dir, "science", channel="terminal", history=True)

    assert res is False
    ledger_after = load_ledger(lesson_dir)
    assert len(ledger_after.decisions) == 1
    assert ledger_after.decisions[0].issue_id == "sci_1"
    assert ledger_after.decisions[0].decision == "accepted"


def test_run_review_science_applies_decided_asr_to_prompt(tmp_path):
    from rt.pipeline.review_science import run_review_science
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="target ASR", candidate="correzione ASR applicata", confidence=0.9, level=ASRLevel.YELLOW, reason="m1"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    record_decision(lesson_dir, "asr_1", "accepted", resolved_text="correzione ASR applicata")

    prompts_captured = []

    def mock_call_structured(prompt, **kwargs):
        prompts_captured.append(prompt)
        from rt.llm.prompts import ScienceIssueList
        return ScienceIssueList(issues=[])

    with patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        res = run_review_science(lesson_dir, force=True, force_mock=True)

    assert len(prompts_captured) > 0
    # La correzione ASR deve comparire nel prompt passato al critic
    assert "correzione ASR applicata" in prompts_captured[0]

    # Ma il draft su disco NON deve essere stato modificato
    with open(os.path.join(lesson_dir, "draft.json"), "r", encoding="utf-8") as f:
        draft_on_disk = json.load(f)
    assert "target ASR" in draft_on_disk["units"][0]["content"]


def test_cmd_run_with_review_does_not_build_when_review_deferred(tmp_path, monkeypatch):
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
         patch("rt.cli.run_interactive_review", return_value=False) as mock_review, \
         patch("rt.cli.run_build", side_effect=fake_run_build):
        cmd_run(args)

    mock_review.assert_called_once()
    assert build_called == [], "run_build() non deve essere chiamato se run_interactive_review() ritorna False"


def test_run_review_science_warning_when_asr_pending(tmp_path, capsys):
    from rt.pipeline.review_science import run_review_science
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    # 1. ASR review mai eseguita (asr_issues.json assente)
    with patch("rt.llm.client.LLMClient.call_structured", return_value=MagicMock(issues=[])):
        run_review_science(lesson_dir, force=True, force_mock=True)

    out = capsys.readouterr().out
    assert "⚠️  Ci sono issue ASR non ancora generate/decise" in out

    # 2. ASR review con issue pendenti
    asr_issues = [
        ASRIssue(id="asr_1", segment_id="seg_000001", source_text="err1", candidate="corr1", confidence=0.8, level=ASRLevel.YELLOW, reason="m1"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)

    with patch("rt.llm.client.LLMClient.call_structured", return_value=MagicMock(issues=[])):
        run_review_science(lesson_dir, force=True, force_mock=True)

    out2 = capsys.readouterr().out
    assert "⚠️  Ci sono issue ASR non ancora generate/decise" in out2


def test_interactive_review_auto_accept(tmp_path):
    lesson_dir = str(tmp_path)
    _create_sample_lesson(lesson_dir)

    asr_issues = [
        ASRIssue(id="asr_y", segment_id="seg_000001", source_text="err_y", candidate="corr_y", confidence=0.8, level=ASRLevel.YELLOW, reason="mot_y"),
        ASRIssue(id="asr_r", segment_id="seg_000002", source_text="err_r", candidate="corr_r", confidence=0.5, level=ASRLevel.RED, reason="mot_r"),
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)

    # auto-accept yellow -> auto-accetta asr_y, lascia asr_r da rivedere
    # Con non-tty si ferma e ritorna False perché asr_r resta
    with patch("sys.stdin.isatty", return_value=False):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal", auto_accept="yellow")
    assert res is False

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_y"
    assert ledger.decisions[0].decision == "accepted"

    # Ora auto-accept red -> auto-accetta asr_r -> non resta più nulla -> ritorna True
    res2 = run_interactive_review(lesson_dir, "asr", channel="terminal", auto_accept="red")
    assert res2 is True
    ledger2 = load_ledger(lesson_dir)
    assert len(ledger2.decisions) == 2


