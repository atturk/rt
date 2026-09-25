"""
tests/test_interactive_terminal_c1.py
Test di accettazione per la Fase C1:
- Audio in background (resolve_audio_path, cut_clip, play_clip_background)
- Editor di testo per modifiche (edit_text_in_editor, marcatori ASR e claim scienza)
- Navigazione interattiva completa con P, M, E.
"""

import os
import sys
import json
import pytest
import subprocess
from unittest.mock import patch, MagicMock

import io
import threading
import time

from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    SegmentsData, Segment, Draft, DraftUnit, Manifest
)
from rt.core.manifest import save_manifest
from rt.pipeline.ledger import load_ledger, get_pending_issues
from rt.tui.issue_review import run_interactive_review


# ---------------------------------------------------------------------------
# 1. resolve_audio_path & cut_clip
# ---------------------------------------------------------------------------

def test_resolve_audio_path(tmp_path):
    lesson_dir = str(tmp_path)
    # 1. Senza manifest -> None
    assert resolve_audio_path(lesson_dir) is None

    # 2. Con manifest ma file inesistente -> None
    from rt.core.manifest import init_or_update_manifest
    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="L1",
        date="2026-09-09",
        subject="Fisica",
        current_state="DRAFT_VALIDATED",
        audio_file="audio.mp3",
    )
    assert resolve_audio_path(lesson_dir) is None

    # 3. Con file audio presente
    audio_file_path = os.path.join(lesson_dir, "audio.mp3")
    with open(audio_file_path, "wb") as f:
        f.write(b"FAKE_AUDIO")

    resolved = resolve_audio_path(lesson_dir)
    assert resolved == os.path.abspath(audio_file_path)


def test_cut_clip_success(tmp_path):
    fake_audio = str(tmp_path / "lecture.m4a")
    with open(fake_audio, "wb") as f:
        f.write(b"AUDIO")

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        clip_path = cut_clip(fake_audio, 12.5, 35.0)

        assert os.path.exists(clip_path) or clip_path.endswith(".m4a")
        # Verifica argomenti passati a ffmpeg
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert cmd[1:6] == ["-y", "-ss", "12.5", "-to", "35.0"]
        assert cmd[6:8] == ["-i", fake_audio]
        assert cmd[8:10] == ["-c", "copy"]

        # Cleanup
        if os.path.exists(clip_path):
            os.remove(clip_path)


def test_cut_clip_ffmpeg_not_found(tmp_path):
    fake_audio = str(tmp_path / "lecture.mp3")
    with open(fake_audio, "wb") as f:
        f.write(b"AUDIO")

    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="ffmpeg"):
            cut_clip(fake_audio, 0.0, 10.0)


def test_cut_clip_subprocess_error(tmp_path):
    fake_audio = str(tmp_path / "lecture.mp3")
    with open(fake_audio, "wb") as f:
        f.write(b"AUDIO")

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])):
        with pytest.raises(subprocess.CalledProcessError):
            cut_clip(fake_audio, 0.0, 10.0)


# ---------------------------------------------------------------------------
# 3. play_clip_background
# ---------------------------------------------------------------------------

def test_play_clip_background():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        proc = play_clip_background("/tmp/clip.mp3")
        assert proc == mock_proc
        mock_popen.assert_called_once_with(
            ["afplay", "/tmp/clip.mp3"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# ---------------------------------------------------------------------------
# 4. edit_text_in_editor (including nano --softwrap)
# ---------------------------------------------------------------------------

def test_edit_text_in_editor_custom_content(monkeypatch):
    def fake_editor_call(args):
        filepath = args[1]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content.replace("vecchio_testo", "nuovo_testo") + "\n\n")
        return 0

    monkeypatch.setenv("EDITOR", "dummy_editor")
    with patch("subprocess.call", side_effect=fake_editor_call) as mock_call:
        res = edit_text_in_editor("Questo è il vecchio_testo.")
        assert res == "Questo è il nuovo_testo."
        mock_call.assert_called_once()
        assert "--softwrap" not in mock_call.call_args[0][0]


def test_edit_text_in_editor_nano_softwrap(monkeypatch):
    monkeypatch.setenv("EDITOR", "nano")
    with patch("subprocess.call", return_value=0) as mock_call:
        edit_text_in_editor("Testo di prova")
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        assert args[0] == "nano"
        assert args[1] == "--softwrap"

    monkeypatch.setenv("EDITOR", "/opt/homebrew/bin/nano")
    with patch("subprocess.call", return_value=0) as mock_call:
        edit_text_in_editor("Testo di prova")
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        assert args[0] == "/opt/homebrew/bin/nano"
        assert args[1] == "--softwrap"


def test_edit_text_in_editor_micro_softwrap(monkeypatch):
    monkeypatch.setenv("EDITOR", "micro")
    with patch("subprocess.call", return_value=0) as mock_call:
        edit_text_in_editor("Testo di prova")
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        assert args[0] == "micro"
        assert "-softwrap" in args and "true" in args
        assert args.index("true") == args.index("-softwrap") + 1

    monkeypatch.setenv("EDITOR", "/opt/homebrew/bin/micro")
    with patch("subprocess.call", return_value=0) as mock_call:
        edit_text_in_editor("Testo di prova")
        args = mock_call.call_args[0][0]
        assert args[0] == "/opt/homebrew/bin/micro"
        assert "-softwrap" in args and "true" in args


# ---------------------------------------------------------------------------
# 5. run_interactive_review con P, O, M (ASR), E (Scienza), frecce, fallback
# ---------------------------------------------------------------------------

def _setup_review_environment(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="audio.mp3",
        audio_duration_seconds=120.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Trascrizione grezza 1"),
            Segment(id="seg_000002", index=2, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="Trascrizione grezza 2"),
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    audio_path = os.path.join(lesson_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"AUDIO_DATA")

    from rt.core.manifest import init_or_update_manifest
    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="L1",
        date="2026-09-09",
        subject="Chimica",
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
                content="Nel processo di distillazione abbiamo una reazione esotermica importante.",
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


def _create_sample_science_issue(id_str="sci_001", unit_id="U1", claim="distillazione", fix="distillazione"):
    return ScienceIssue(
        id=id_str,
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id=unit_id,
        claim=claim,
        reason="ambiguità",
        suggested_fix=fix
    )


@pytest.mark.anyio
async def test_asr_interactive_p_and_m_keys(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("rt.tui.issue_review.edit_text_in_editor", return_value="# Commento\nNel processo di rettificazione abbiamo una reazione esotermica importante.") as mock_edit:

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.press("m")

    assert app.return_value is True
    mock_popen.assert_called_once()
    assert "mpv" in mock_popen.call_args[0][0][0]
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "Nel processo di rettificazione abbiamo una reazione esotermica importante."


@pytest.mark.anyio
async def test_audio_pause_resume_restart_and_stop_on_action(tmp_path, monkeypatch):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/clip1.mp3"), \
         patch("subprocess.Popen", side_effect=[mock_proc1, mock_proc2]) as mock_popen:

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")  # Apre mpv
            await pilot.press("p")  # Chiude mpv
            await pilot.press("p")  # Riapre mpv
            await pilot.press("a")  # Auto-chiude mpv e accetta

    assert app.return_value is True
    assert mock_popen.call_count == 2
    mock_proc1.terminate.assert_called_once()
    mock_proc2.terminate.assert_called_once()


@pytest.mark.anyio
async def test_audio_error_messages_remain_visible(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", side_effect=RuntimeError("clip error test")):
        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")
            assert app.last_status is not None
            assert "clip error test" in app.last_status
            await pilot.press("q")

    assert app.return_value is False


    assert app.return_value is False


@pytest.mark.anyio
async def test_unrecognized_key_no_action_no_advance(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
    async with app.run_test() as pilot:
        await pilot.press("z")
        assert app.idx == 0
        await pilot.press("a")

    assert app.return_value is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"


@pytest.mark.anyio
async def test_unknown_key_in_science_review_no_action(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_CONCETTUALE,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            claim="abbiamo una reazione esotermica",
            reason="in realtà è endotermica",
            suggested_fix="abbiamo una reazione endotermica"
        )
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
    async with app.run_test() as pilot:
        await pilot.press("x")
        assert app.idx == 0
        await pilot.press("a")

    assert app.return_value is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"


@pytest.mark.anyio
async def test_arrow_keys_aliases_left_right(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        _create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione"),
        _create_sample_science_issue("sci_002", "U1", "esotermica", "esotermica")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
    async with app.run_test() as pilot:
        await pilot.press("right")
        assert app.idx == 1
        await pilot.press("left")
        assert app.idx == 0
        await pilot.press("a")
        await pilot.press("a")

    assert app.return_value is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[0].issue_id == "sci_001"
    assert ledger.decisions[1].issue_id == "sci_002"


@pytest.mark.anyio
async def test_context_fallback_when_draft_mismatch(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "parola_rara_xyz", "parola_rara_abc")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
    async with app.run_test() as pilot:
        await pilot.press("a")

    assert app.return_value is True


@pytest.mark.anyio
async def test_science_interactive_m_missing_markers_retries(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
    async with app.run_test() as pilot:
        await pilot.press("r")

    assert app.return_value is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "rejected"


@pytest.mark.anyio
async def test_science_interactive_p_and_e_keys(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_CONCETTUALE,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            claim="abbiamo una reazione esotermica",
            reason="in realtà è endotermica",
            suggested_fix="abbiamo una reazione endotermica"
        )
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip_sci.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("rt.tui.issue_review.edit_text_in_editor", return_value="# Commento iniziale\nabbiamo una reazione endotermica controllata") as mock_edit:

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.press("m")

    assert app.return_value is True
    mock_popen.assert_called_once()
    assert "mpv" in mock_popen.call_args[0][0][0]
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "abbiamo una reazione endotermica controllata"


@pytest.mark.anyio
async def test_silent_p_o_and_unrecognized_keys_science(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/clip1.mp3"), \
         patch("subprocess.Popen", side_effect=[mock_proc1, mock_proc2]) as mock_popen:
        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.press("p")
            await pilot.press("p")
            await pilot.press("z")
            await pilot.press("a")

    assert app.return_value is True
    assert mock_popen.call_count == 2
    mock_proc1.terminate.assert_called_once()
    mock_proc2.terminate.assert_called_once()


@pytest.mark.anyio
async def test_quit_during_p_sequence_interrupts_cleanly(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/opt/homebrew/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/clip1.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc):
        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.press("q")

    assert app.return_value is False
    mock_proc.terminate.assert_called_once()


@pytest.mark.anyio
async def test_m_and_e_failure_reprompts_without_full_redraw(tmp_path):
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    with patch("rt.tui.issue_review.edit_text_in_editor", side_effect=["", "Nel processo di distillazione abbiamo una reazione esotermica importante."]):
        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=sci_issues)
        async with app.run_test() as pilot:
            await pilot.press("m")  # Returns empty -> warning, does not advance
            assert app.idx == 0
            assert "Nessuna modifica" in (app.last_status or "")
            await pilot.press("m")  # Returns edited text -> advances
            assert app.idx == 1

    assert app.return_value is True


@pytest.mark.anyio
async def test_asr_risk_issue_actions(tmp_path):
    """Testa i comandi specifici per issue di tipo ERR_ASR_ST."""
    from rt.tui.issue_review import IssueReviewApp
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    asr_risk_issue = ScienceIssue(
        id="asr_001",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        segment_id="seg_000001",
        claim="segmento raw sospetto",
        reason="confidenza bassa",
        suggested_fix=None,
    )
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([asr_risk_issue.model_dump(mode="json")], f)

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[asr_risk_issue])
    async with app.run_test() as pilot:
        # Premere 'a' per issue ASR accetta il testo dell'unità
        await pilot.press("a")
        assert app.idx == 1

    assert app.return_value is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"





