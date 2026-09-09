"""
tests/test_interactive_terminal_c1.py
Test di accettazione per la Fase C1:
- Tasti rapidi (read_single_key)
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

from rt.core.keyboard import read_single_key
from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor
from rt.core.models import (
    ASRIssue, ASRLevel, ScienceIssue, ScienceType, ScienceSeverity,
    SegmentsData, Segment, Draft, DraftUnit, Manifest
)
from rt.core.manifest import save_manifest
from rt.pipeline.ledger import load_ledger, get_pending_issues
from rt.pipeline.issue_review import run_interactive_review


# ---------------------------------------------------------------------------
# 1. read_single_key
# ---------------------------------------------------------------------------

def test_read_single_key_fallback_when_not_atty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with patch("builtins.input", return_value="a"):
        res = read_single_key()
        assert res == "a"


def test_read_single_key_raw_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    mock_fd = 0
    monkeypatch.setattr(sys.stdin, "fileno", lambda: mock_fd)

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with patch.object(sys.stdin, "read", return_value="p"):
            res = read_single_key()
            assert res == "p"
            mock_tty.setraw.assert_called_once_with(mock_fd)
            mock_termios.tcsetattr.assert_called_once()


def test_read_single_key_ctrl_c(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with patch.object(sys.stdin, "read", return_value="\x03"):
            with pytest.raises(KeyboardInterrupt):
                read_single_key()


# ---------------------------------------------------------------------------
# 2. resolve_audio_path & cut_clip
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
# 4. edit_text_in_editor
# ---------------------------------------------------------------------------

def test_edit_text_in_editor_custom_content(monkeypatch):
    def fake_editor_call(args):
        # args[1] è il file temporaneo
        filepath = args[1]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # Sovrascrive il file con una modifica
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content.replace("vecchio_testo", "nuovo_testo") + "\n\n")
        return 0

    monkeypatch.setenv("EDITOR", "dummy_editor")
    with patch("subprocess.call", side_effect=fake_editor_call) as mock_call:
        res = edit_text_in_editor("Questo è il vecchio_testo.")
        assert res == "Questo è il nuovo_testo."
        mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# 5. run_interactive_review con P, M (ASR) ed E (Scienza)
# ---------------------------------------------------------------------------

def _setup_review_environment(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    # segments.json
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

    # audio file
    audio_path = os.path.join(lesson_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"AUDIO_DATA")

    # manifest
    from rt.core.manifest import init_or_update_manifest
    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="L1",
        date="2026-09-09",
        subject="Chimica",
        current_state="DRAFT_VALIDATED",
        audio_file="audio.mp3",
    )

    # draft.json
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


def test_asr_interactive_p_and_m_keys(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    asr_issues = [
        ASRIssue(
            id="asr_001",
            segment_id="seg_000001",
            source_text="distillazione",
            candidate="distillazione",
            confidence=0.75,
            level=ASRLevel.YELLOW,
            reason="ambiguità fonetica"
        )
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Sequenza di tasti:
    # 1. 'p' -> ascolto audio (intervallo 10-5=5s a 20+5=25s), non avanza
    # 2. 'm' -> modifica via editor, estrae »correzione_manuale«
    keys = iter(["p", "m"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/test_clip.mp3") as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc) as mock_play, \
         patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="# Commento\nNel processo di »rettificazione« abbiamo una reazione.") as mock_edit:

        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    # Verifica che cut_clip sia stato chiamato con il margine di 5s
    mock_cut.assert_called_once_with(os.path.abspath(os.path.join(lesson_dir, "audio.mp3")), 5.0, 25.0)
    mock_play.assert_called_once_with("/tmp/test_clip.mp3")
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "rettificazione"


def test_asr_interactive_m_missing_markers_retries(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    asr_issues = [
        ASRIssue(
            id="asr_001",
            segment_id="seg_000001",
            source_text="distillazione",
            candidate="distillazione",
            confidence=0.75,
            level=ASRLevel.YELLOW,
            reason="ambiguità fonetica"
        )
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in asr_issues], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # 1. 'm' -> l'utente cancella i marcatori »« -> stampa warning e ripresenta
    # 2. 'a' -> accetta normalmente
    keys = iter(["m", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda: next(keys))

    with patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="Testo senza marcatori"):
        res = run_interactive_review(lesson_dir, "asr", channel="terminal")

    assert res is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[0].resolved_text == "distillazione"


def test_science_interactive_p_and_e_keys(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        ScienceIssue(
            id="sci_001",
            type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.HIGH,
            unit_id="U1",
            claim="abbiamo una reazione esotermica",
            reason="in realtà è endotermica",
            suggested_fix="abbiamo una reazione endotermica"
        )
    ]
    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # 1. 'p' -> ascolto audio dell'intera unità U1 (10s a 30s)
    # 2. 'e' -> modifica via editor
    keys = iter(["p", "e"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/test_clip_sci.mp3") as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc) as mock_play, \
         patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="# Commento iniziale\nabbiamo una reazione endotermica controllata") as mock_edit:

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    # Scienza taglia l'intervallo dell'unità U1: seg_000001 (10s) a seg_000002 (30s) senza margini aggiuntivi
    mock_cut.assert_called_once_with(os.path.abspath(os.path.join(lesson_dir, "audio.mp3")), 10.0, 30.0)
    mock_play.assert_called_once_with("/tmp/test_clip_sci.mp3")
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "abbiamo una reazione endotermica controllata"
