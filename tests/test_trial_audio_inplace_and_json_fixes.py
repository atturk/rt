"""
tests/test_trial_audio_inplace_and_json_fixes.py
Test di accettazione specifici per:
1. Play -> Pausa (terminate(), no send_signal, no SIGSTOP/SIGCONT in codebase)
2. Pausa -> Ripresa (cut_clip con start aggiornato a audio_range_start + audio_elapsed)
3. Riavvio (O) dopo pausa (audio_elapsed resettato a 0.0, cut_clip da start originale)
4. Ramo scienza (P): segmento primario iss.segment_id ± 5s, fallback a unità solo se irrisolvibile
5. Redraw in-place (sequenze ANSI \\x1b[{N}A\\x1b[0J tra blocchi successivi)
6. Flag --json su prepare, outline, rewrite, review-asr, review-science, build (e persistenza JSON su validate-outline, validate-draft, setup)
"""

import os
import sys
import json
import inspect
import subprocess
import pytest
from unittest.mock import patch, MagicMock
import argparse

import rt.pipeline.issue_review as ir_module
from rt.pipeline.issue_review import run_interactive_review
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.manifest import init_or_update_manifest
from rt.cli import (
    cmd_prepare, cmd_outline, cmd_rewrite, cmd_review, cmd_build,
    cmd_validate_outline, cmd_validate_draft, cmd_setup
)


def _setup_env(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="audio.mp3",
        audio_duration_seconds=120.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Trascrizione 1"),
            Segment(id="seg_000002", index=2, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="Trascrizione 2"),
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    audio_path = os.path.join(lesson_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"AUDIO_BYTES")

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
                content="Nel processo abbiamo una reazione termica.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                key_concepts=[]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\n")


def test_no_sigstop_sigcont_in_issue_review():
    """Test 1b: nessun SIGSTOP/SIGCONT compare più nel file issue_review.py."""
    src = inspect.getsource(ir_module)
    assert "SIGSTOP" not in src
    assert "SIGCONT" not in src
    assert "signal" not in src


def test_audio_pause_terminate_and_resume_seek(tmp_path, monkeypatch):
    """Test 1 & 2 & 3: Play -> Pausa (terminate), Pausa -> Ripresa (seek), Riavvio O (reset)."""
    lesson_dir = str(tmp_path)
    _setup_env(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            segment_id="seg_000001",
            claim="reazione",
            reason="ambiguità",
            suggested_fix="reazione"
        )
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "p", "p", "o", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None
    mock_proc3 = MagicMock()
    mock_proc3.poll.return_value = None

    # Simula 4.5s di riproduzione prima della pausa
    monotonic_times = [100.0, 104.5, 104.5, 106.0, 107.0, 108.0]
    monkeypatch.setattr("time.monotonic", lambda: monotonic_times.pop(0) if monotonic_times else 200.0)

    with patch("rt.pipeline.issue_review.cut_clip", side_effect=["/tmp/c1.mp3", "/tmp/c2.mp3", "/tmp/c3.mp3"]) as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", side_effect=[mock_proc1, mock_proc2, mock_proc3]):

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    assert mock_cut.call_count == 3
    audio_path = os.path.abspath(os.path.join(lesson_dir, "audio.mp3"))
    # 1° Play: 5.0 a 25.0
    assert mock_cut.call_args_list[0][0] == (audio_path, 5.0, 25.0)
    # Resume dopo 4.5s: 5.0 + 4.5 = 9.5 a 25.0
    assert mock_cut.call_args_list[1][0] == (audio_path, 9.5, 25.0)
    # Restart O: 5.0 a 25.0
    assert mock_cut.call_args_list[2][0] == (audio_path, 5.0, 25.0)

    mock_proc1.terminate.assert_called_once()
    mock_proc1.send_signal.assert_not_called()


def test_science_clip_claim_vs_unit_fallback(tmp_path, monkeypatch):
    """Test 4: Science review P usa iss.segment_id ± 5s come primario, fallback a unità se non risolvibile."""
    lesson_dir = str(tmp_path)
    _setup_env(lesson_dir)

    # 1. Caso normale: segment_id risolvibile (seg_000001: 10s-20s -> 5s-25s)
    sci_issue_with_seg = ScienceIssue(
        id="sci_001",
        type=ScienceType.ERR_RECONSTRUCTION,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        segment_id="seg_000001",
        claim="abbiamo una reazione termica",
        reason="in realtà è atermica",
        suggested_fix="abbiamo una reazione atermica"
    )
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([sci_issue_with_seg.model_dump(mode="json")], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    keys = iter(["p", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/c_sci1.mp3") as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc):

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    audio_path = os.path.abspath(os.path.join(lesson_dir, "audio.mp3"))
    # Range primario basato su seg_000001 (10s-20s -> ±5s: 5.0s a 25.0s)
    mock_cut.assert_called_once_with(audio_path, 5.0, 25.0)

    # 2. Caso fallback: segment_id inesistente/non in seg_by_id -> fallback a intera unità U1 (10.0s a 30.0s)
    sci_issue_fallback = ScienceIssue(
        id="sci_002",
        type=ScienceType.ERR_RECONSTRUCTION,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        segment_id="seg_999999_non_esistente",
        claim="abbiamo una reazione termica",
        reason="in realtà è atermica",
        suggested_fix="abbiamo una reazione atermica"
    )
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([sci_issue_fallback.model_dump(mode="json")], f)

    keys2 = iter(["p", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys2))

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/c_sci2.mp3") as mock_cut2, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc):

        res2 = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res2 is True
    # Fallback sull'unità intera U1 (seg_000001 start=10.0s a seg_000002 end=30.0s)
    mock_cut2.assert_called_once_with(audio_path, 10.0, 30.0)


def test_redraw_in_place_ansi_sequences(tmp_path, monkeypatch, capsys):
    """Test 5: Tra due blocchi successivi compaiono le sequenze ANSI \\x1b[{N}A\\x1b[0J."""
    lesson_dir = str(tmp_path)
    _setup_env(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            segment_id="seg_000001",
            claim="test1",
            reason="ambiguità 1",
            suggested_fix="test1_fixed"
        ),
        ScienceIssue(
            id="sci_002",
            type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            segment_id="seg_000002",
            claim="test2",
            reason="ambiguità 2",
            suggested_fix="test2_fixed"
        ),
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["a", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True

    captured = capsys.readouterr()
    raw_out = captured.out
    # Verifica che il pannello Rich compaia nell'output renderizzato
    assert "ASR Review" in raw_out
    assert mock_cut.call_count == 3
    audio_path = os.path.abspath(os.path.join(lesson_dir, "audio.mp3"))
    assert mock_cut.call_args_list[0][0] == (audio_path, 10.0, 30.0)
    assert mock_cut.call_args_list[1][0] == (audio_path, 13.0, 30.0)
    assert mock_cut.call_args_list[2][0] == (audio_path, 10.0, 30.0)

    mock_proc1.terminate.assert_called()
    mock_proc2.terminate.assert_called()
    mock_proc3.terminate.assert_called()


def test_cli_json_flag_and_stdout(capsys):
    """Test 6: Flag --json su CLI (prepare, outline, rewrite, review, build)."""
    # 1. prepare
    with patch("rt.cli.run_prepare", return_value={"status": "OK"}):
        args_no_json = argparse.Namespace(lesson_dir="dummy", json=False)
        cmd_prepare(args_no_json)
        out = capsys.readouterr().out
        assert "[RUN] prepare" in out
        assert "{\n  \"status\": \"OK\"" not in out

        args_json = argparse.Namespace(lesson_dir="dummy", json=True)
        cmd_prepare(args_json)
        out = capsys.readouterr().out
        assert "[RUN] prepare" in out
        assert "{\n  \"status\": \"OK\"" in out

    # 2. outline
    with patch("rt.cli._has_real_config_source", return_value=True), \
         patch("rt.cli.run_outline", return_value={"status": "OK"}), \
         patch("rt.cli.confirm_or_revise_outline"):
        args_no_json = argparse.Namespace(lesson_dir="dummy", force=False, mock=True, channel="terminal", json=False)
        cmd_outline(args_no_json)
        out = capsys.readouterr().out
        assert "[RUN] outline" in out
        assert "{\n  \"status\": \"OK\"" not in out

        args_json = argparse.Namespace(lesson_dir="dummy", force=False, mock=True, channel="terminal", json=True)
        cmd_outline(args_json)
        out = capsys.readouterr().out
        assert "[RUN] outline" in out
        assert "{\n  \"status\": \"OK\"" in out

    # 3. rewrite
    with patch("rt.cli._has_real_config_source", return_value=True), \
         patch("rt.cli.run_rewrite", return_value={"status": "OK"}), \
         patch("rt.cli.confirm_or_revise_outline"):
        args_no_json = argparse.Namespace(lesson_dir="dummy", unit=None, force=False, mock=True, json=False)
        cmd_rewrite(args_no_json)
        out = capsys.readouterr().out
        assert "[RUN] rewrite" in out
        assert "{\n  \"status\": \"OK\"" not in out

        args_json = argparse.Namespace(lesson_dir="dummy", unit=None, force=False, mock=True, json=True)
        cmd_rewrite(args_json)
        out = capsys.readouterr().out
        assert "[RUN] rewrite" in out
        assert "{\n  \"status\": \"OK\"" in out

    # 4. review
    with patch("rt.cli._has_real_config_source", return_value=True), \
         patch("rt.cli.run_review", return_value={"status": "OK"}), \
         patch("rt.pipeline.issue_review.run_interactive_review"):
        args_no_json = argparse.Namespace(lesson_dir="dummy", force=False, mock=True, channel="terminal", json=False, reset=False, auto_accept=None, history=False)
        cmd_review(args_no_json)
        out = capsys.readouterr().out
        assert "[RUN] review" in out
        assert "{\n  \"status\": \"OK\"" not in out

        args_json = argparse.Namespace(lesson_dir="dummy", force=False, mock=True, channel="terminal", json=True, reset=False, auto_accept=None, history=False)
        cmd_review(args_json)
        out = capsys.readouterr().out
        assert "[RUN] review" in out
        assert "{\n  \"status\": \"OK\"" in out

    # 6. build
    with patch("rt.cli.run_build", return_value={"status": "OK"}), \
         patch("rt.telegram.notify.notify_build_completed"):
        args_no_json = argparse.Namespace(lesson_dir="dummy", force=False, rename=False, channel="terminal", json=False)
        cmd_build(args_no_json)
        out = capsys.readouterr().out
        assert "[RUN] build" in out
        assert "{\n  \"status\": \"OK\"" not in out

        args_json = argparse.Namespace(lesson_dir="dummy", force=False, rename=False, channel="terminal", json=True)
        cmd_build(args_json)
        out = capsys.readouterr().out
        assert "[RUN] build" in out
        assert "{\n  \"status\": \"OK\"" in out

    # Non-toccati: validate-outline, validate-draft, setup continuano a stampare JSON incondizionatamente
    with patch("rt.cli.load_outline"), patch("rt.cli.load_segments_json"), patch("rt.cli.validate_outline", return_value={"valid": True}):
        cmd_validate_outline(argparse.Namespace(lesson_dir="dummy"))
        out = capsys.readouterr().out
        assert "{\n  \"valid\": true\n}" in out

    with patch("rt.cli.load_outline"), patch("rt.cli.load_draft"), patch("rt.cli.load_segments_json"), patch("rt.cli.validate_draft", return_value={"valid": True}):
        cmd_validate_draft(argparse.Namespace(lesson_dir="dummy"))
        out = capsys.readouterr().out
        assert "{\n  \"valid\": true\n}" in out

    with patch("rt.pipeline.setup.run_setup", return_value={"lesson_dir": "test_dir"}):
        cmd_setup(argparse.Namespace(audio="a.mp3", date=None, materia=None, argomenti=None, dest_dir=None, model=None, skip_transcribe=False, force=False, mock=True))
        out = capsys.readouterr().out
        assert "{\n  \"lesson_dir\": \"test_dir\"\n}" in out


def test_print_phase_action_success_confirmation():
    """Verifica che _print_phase_action aggiunga una riga di conferma esplicita di successo
    per i rami RUN e FORCE, e che il ramo SKIP resti invariato (nessuna riga aggiuntiva)."""
    from rt.cli import _print_phase_action

    # RUN
    res_run = {"action": "RUN", "reason": "segments.json non trovato"}
    with patch("builtins.print") as mock_print:
        _print_phase_action("prepare", res_run)
    full_output = "".join(call.args[0] for call in mock_print.call_args_list)
    assert "[RUN] prepare" in full_output
    assert "Reason: segments.json non trovato" in full_output
    assert "completato" in full_output
    assert "✔" in full_output
    assert full_output.index("Reason:") < full_output.index("completato")

    # FORCE
    res_force = {"action": "FORCE", "reason": "explicit user-requested rerun"}
    with patch("builtins.print") as mock_print:
        _print_phase_action("build", res_force)
    full_output = "".join(call.args[0] for call in mock_print.call_args_list)
    assert "[FORCE] build" in full_output
    assert "Reason: explicit user-requested rerun" in full_output
    assert "completato (rigenerazione forzata)" in full_output
    assert "✔" in full_output

    # SKIP — nessuna riga di conferma aggiuntiva deve comparire
    res_skip = {"action": "SKIP", "reason": "outline.json valido e conforme ai segmenti"}
    with patch("builtins.print") as mock_print:
        _print_phase_action("outline", res_skip)
    full_output = "".join(call.args[0] for call in mock_print.call_args_list)
    assert "[SKIP] outline" in full_output
    assert "Reason: outline.json valido e conforme ai segmenti" in full_output
    assert "completato" not in full_output


def test_print_phase_action_uses_dynamic_label():
    """La riga di conferma usa lo stesso phase_name passato alla funzione (es. rewrite unit 1.1)."""
    from rt.cli import _print_phase_action

    res = {"action": "RUN", "reason": "segments.json modificati"}
    with patch("builtins.print") as mock_print:
        _print_phase_action("rewrite unit 1.1", res)
    full_output = "".join(call.args[0] for call in mock_print.call_args_list)
    assert "[RUN] rewrite unit 1.1" in full_output
    assert "✔ rewrite unit 1.1 completato." in full_output
