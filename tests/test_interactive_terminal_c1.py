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

import io
import threading
import time

from rt.core.keyboard import read_single_key, UNKNOWN_KEY, raw_mode
from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
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
    with patch("builtins.input", return_value="\x1b[D"):
        res = read_single_key()
        assert res == "LEFT"
    with patch("builtins.input", return_value="\x1b[C"):
        res = read_single_key()
        assert res == "RIGHT"
    with patch("builtins.input", return_value="\x1b[Z"):
        res = read_single_key()
        assert res == UNKNOWN_KEY
    with patch("builtins.input", return_value="\x1b[A"):
        res = read_single_key()
        assert res == "UP"


def test_raw_mode_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    mock_fd = 0
    monkeypatch.setattr(sys.stdin, "fileno", lambda: mock_fd)
    mock_termios.tcgetattr.return_value = ["dummy_attrs"]

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with raw_mode() as is_raw:
            assert is_raw is True
            mock_tty.setcbreak.assert_called_once_with(mock_fd)
            mock_termios.tcsetattr.assert_not_called()
        mock_termios.tcsetattr.assert_called_once_with(mock_fd, mock_termios.TCSADRAIN, ["dummy_attrs"])


def test_raw_mode_not_atty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    mock_termios = MagicMock()
    mock_tty = MagicMock()

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with raw_mode() as is_raw:
            assert is_raw is False
            mock_tty.setraw.assert_not_called()
            mock_termios.tcgetattr.assert_not_called()
            mock_termios.tcsetattr.assert_not_called()


def test_read_single_key_already_raw(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    mock_fd = 0
    monkeypatch.setattr(sys.stdin, "fileno", lambda: mock_fd)

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        # Normal char: os.read returns b"a"
        with patch("rt.core.keyboard.os.read", return_value=b"a"):
            res = read_single_key(already_raw=True)
            assert res == "a"
            mock_tty.setraw.assert_not_called()
            mock_termios.tcsetattr.assert_not_called()
            mock_termios.tcgetattr.assert_not_called()

        # Test arrows when already_raw=True
        with patch("select.select", return_value=([mock_fd], [], [])), \
             patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"[", b"D"]):
            res = read_single_key(already_raw=True)
            assert res == "LEFT"
            mock_tty.setraw.assert_not_called()
            mock_termios.tcsetattr.assert_not_called()

        # Test UNKNOWN_KEY when already_raw=True
        with patch("select.select", return_value=([], [], [])), \
             patch("rt.core.keyboard.os.read", return_value=b"\x1b"):
            res = read_single_key(already_raw=True)
            assert res == UNKNOWN_KEY
            mock_tty.setraw.assert_not_called()
            mock_termios.tcsetattr.assert_not_called()


def test_read_single_key_raw_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    mock_fd = 0
    monkeypatch.setattr(sys.stdin, "fileno", lambda: mock_fd)

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with patch("rt.core.keyboard.os.read", return_value=b"p"):
            res = read_single_key()
            assert res == "p"
            mock_tty.setcbreak.assert_called_once_with(mock_fd)
            mock_termios.tcsetattr.assert_called_once()


def test_read_single_key_raw_tty_arrows_and_esc(monkeypatch):
    mock_fd = 0
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: mock_fd)
    mock_termios = MagicMock()
    mock_tty = MagicMock()

    # 1. Left arrow: \x1b[D
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", return_value=([mock_fd], [], [])), \
         patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"[", b"D"]):
        res = read_single_key()
        assert res == "LEFT"

    # 2. Right arrow: \x1b[C
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", return_value=([mock_fd], [], [])), \
         patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"[", b"C"]):
        res = read_single_key()
        assert res == "RIGHT"

    # 3. Standalone ESC: select timeout ([], [], []) -> UNKNOWN_KEY (NOT "")
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", return_value=([], [], [])), \
         patch("rt.core.keyboard.os.read", return_value=b"\x1b"):
        res = read_single_key()
        assert res == UNKNOWN_KEY
        assert res != ""

    # 4. ESC + non-bracket -> UNKNOWN_KEY
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", return_value=([mock_fd], [], [])), \
         patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"O"]):
        res = read_single_key()
        assert res == UNKNOWN_KEY

    # 5. ESC + [ + non-arrow -> UNKNOWN_KEY
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", return_value=([mock_fd], [], [])), \
         patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"[", b"Z"]):
        res = read_single_key()
        assert res == UNKNOWN_KEY

    # 6. ESC + [ + timeout on 3rd char -> UNKNOWN_KEY
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}), \
         patch("select.select", side_effect=[([mock_fd], [], []), ([], [], [])]), \
         patch("rt.core.keyboard.os.read", side_effect=[b"\x1b", b"["]):
        res = read_single_key()
        assert res == UNKNOWN_KEY


def test_read_single_key_pipe_timing(monkeypatch):
    """
    Test di read_single_key con un vero os.pipe() e thread con ritardi controllati,
    verificando la corretta interpretazione temporale delle sequenze ANSI e dei timeout.
    """
    mock_termios = MagicMock()
    mock_tty = MagicMock()

    def _read_from_pipe_with_writer(write_action):
        r_fd, w_fd = os.pipe()
        pipe_in = io.open(r_fd, "r", encoding="utf-8")
        monkeypatch.setattr(sys, "stdin", pipe_in)
        monkeypatch.setattr(pipe_in, "isatty", lambda: True)

        def _writer():
            try:
                write_action(w_fd)
            finally:
                os.close(w_fd)

        t = threading.Thread(target=_writer)
        t.daemon = True
        t.start()

        try:
            with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
                res = read_single_key()
        finally:
            t.join(timeout=1.0)
            pipe_in.close()

        return res

    # 1. Freccia Sinistra (\x1b[D) con ritardo di 20ms tra un byte e l'altro (entro i 150ms)
    def write_left_arrow(w_fd):
        os.write(w_fd, b"\x1b")
        time.sleep(0.02)
        os.write(w_fd, b"[")
        time.sleep(0.02)
        os.write(w_fd, b"D")

    assert _read_from_pipe_with_writer(write_left_arrow) == "LEFT"

    # 2. Freccia Destra (\x1b[C) con ritardo di 20ms tra un byte e l'altro
    def write_right_arrow(w_fd):
        os.write(w_fd, b"\x1b")
        time.sleep(0.02)
        os.write(w_fd, b"[")
        time.sleep(0.02)
        os.write(w_fd, b"C")

    assert _read_from_pipe_with_writer(write_right_arrow) == "RIGHT"

    # 3. Solo ESC arrivato, nessun byte successivo -> timeout 150ms -> UNKNOWN_KEY (NON "")
    def write_only_esc(w_fd):
        os.write(w_fd, b"\x1b")
        time.sleep(0.25)

    res_esc = _read_from_pipe_with_writer(write_only_esc)
    assert res_esc == UNKNOWN_KEY
    assert res_esc != ""

    # 4. ESC + [ arrivati, terzo byte mai arrivato -> timeout 150ms -> UNKNOWN_KEY
    def write_esc_bracket_incomplete(w_fd):
        os.write(w_fd, b"\x1b[")
        time.sleep(0.25)

    res_incomplete = _read_from_pipe_with_writer(write_esc_bracket_incomplete)
    assert res_incomplete == UNKNOWN_KEY
    assert res_incomplete != ""

    # 5. Invio premuto (\n o \r) -> ""
    def write_enter(w_fd):
        os.write(w_fd, b"\n")

    assert _read_from_pipe_with_writer(write_enter) == ""


def test_read_single_key_ctrl_c(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
        with patch("rt.core.keyboard.os.read", return_value=b"\x03"):
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
        type=ScienceType.ERR_RECONSTRUCTION,
        severity=ScienceSeverity.HIGH,
        unit_id=unit_id,
        claim=claim,
        reason="ambiguità",
        suggested_fix=fix
    )


def test_asr_interactive_p_and_m_keys(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "e"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/test_clip.mp3") as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc) as mock_play, \
         patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="# Commento\nNel processo di rettificazione abbiamo una reazione esotermica importante.") as mock_edit:

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    mock_cut.assert_called_once_with(os.path.abspath(os.path.join(lesson_dir, "audio.mp3")), 10.0, 30.0)
    mock_play.assert_called_once_with("/tmp/test_clip.mp3")
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "Nel processo di rettificazione abbiamo una reazione esotermica importante."


def test_audio_pause_resume_restart_and_stop_on_action(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Sequenza: P (avvia) -> P (pausa terminate) -> P (riprendi con seek) -> O (riavvia da capo) -> A (accetta e ferma audio)
    keys = iter(["p", "p", "p", "o", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None
    mock_proc3 = MagicMock()
    mock_proc3.poll.return_value = None

    monotonic_times = [100.0, 103.0, 103.0, 104.0, 105.0, 106.0]
    monkeypatch.setattr("time.monotonic", lambda: monotonic_times.pop(0) if monotonic_times else 200.0)

    with patch("rt.pipeline.issue_review.cut_clip", side_effect=["/tmp/clip1.mp3", "/tmp/clip2.mp3", "/tmp/clip3.mp3"]) as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", side_effect=[mock_proc1, mock_proc2, mock_proc3]) as mock_play:

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    assert mock_cut.call_count == 3
    audio_path = os.path.abspath(os.path.join(lesson_dir, "audio.mp3"))
    assert mock_cut.call_args_list[0][0] == (audio_path, 10.0, 30.0)
    assert mock_cut.call_args_list[1][0] == (audio_path, 13.0, 30.0)
    assert mock_cut.call_args_list[2][0] == (audio_path, 10.0, 30.0)

    mock_proc1.terminate.assert_called()
    mock_proc2.terminate.assert_called()
    mock_proc3.terminate.assert_called()

    captured = capsys.readouterr()
    assert "Riproduzione audio in corso" not in captured.out
    assert "In pausa" not in captured.out
    assert "Ripreso" not in captured.out


def test_audio_error_messages_remain_visible(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "q"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    with patch("rt.pipeline.issue_review.cut_clip", side_effect=RuntimeError("ffmpeg error test")):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is False
    captured = capsys.readouterr()
    assert "SCIENCE REVIEW" in captured.out or "Science Review" in captured.out


def test_unrecognized_key_no_action_no_advance(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    assert UNKNOWN_KEY != ""
    keys = iter(["z", UNKNOWN_KEY, "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"


def test_unknown_key_in_science_review_no_action(tmp_path, monkeypatch):
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
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter([UNKNOWN_KEY, "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "accepted"


def test_arrow_keys_aliases_left_right(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        _create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione"),
        _create_sample_science_issue("sci_002", "U1", "esotermica", "esotermica")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["RIGHT", "LEFT", "a", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[0].issue_id == "sci_001"
    assert ledger.decisions[1].issue_id == "sci_002"


def test_context_fallback_when_draft_mismatch(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "parola_rara_xyz", "parola_rara_abc")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    keys = iter(["a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True


def test_science_interactive_m_missing_markers_retries(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["m"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    with patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="Nel processo di distillazione abbiamo una reazione esotermica importante."):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "rejected"


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
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "e"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/test_clip_sci.mp3") as mock_cut, \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc) as mock_play, \
         patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="# Commento iniziale\nabbiamo una reazione endotermica controllata") as mock_edit:

        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    mock_cut.assert_called_once_with(os.path.abspath(os.path.join(lesson_dir, "audio.mp3")), 10.0, 30.0)
    mock_play.assert_called_once_with("/tmp/test_clip_sci.mp3")
    mock_edit.assert_called_once()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].decision == "edited"
    assert ledger.decisions[0].resolved_text == "abbiamo una reazione endotermica controllata"


def test_run_interactive_review_uses_raw_mode_once(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [
        _create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione"),
        _create_sample_science_issue("sci_002", "U1", "reazione", "reazione")
    ]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    raw_mode_enter_count = 0
    raw_mode_exit_count = 0

    import contextlib
    @contextlib.contextmanager
    def mock_raw_mode():
        nonlocal raw_mode_enter_count, raw_mode_exit_count
        raw_mode_enter_count += 1
        try:
            yield True
        finally:
            raw_mode_exit_count += 1

    monkeypatch.setattr("rt.pipeline.issue_review.raw_mode", mock_raw_mode)

    calls_already_raw = []
    keys = iter(["a", "a"])
    def mock_read_key(already_raw=False):
        calls_already_raw.append(already_raw)
        return next(keys)

    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", mock_read_key)

    res = run_interactive_review(lesson_dir, "science", channel="terminal")
    assert res is True
    assert raw_mode_enter_count == 1
    assert raw_mode_exit_count == 1
    assert calls_already_raw == [True, True]


def test_silent_p_o_and_unrecognized_keys_science(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "p", "p", "o", "z", UNKNOWN_KEY, "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", side_effect=["/tmp/clip1.mp3", "/tmp/clip2.mp3"]), \
         patch("rt.pipeline.issue_review.play_clip_background", side_effect=[mock_proc1, mock_proc2]):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    out = capsys.readouterr().out
    assert "Azione [" in out
    assert "✔ Correzione scientifica applicata." in out


def test_quit_during_p_sequence_interrupts_cleanly(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["p", "p", "q"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("rt.pipeline.issue_review.cut_clip", return_value="/tmp/clip1.mp3"), \
         patch("rt.pipeline.issue_review.play_clip_background", return_value=mock_proc):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is False
    mock_proc.terminate.assert_called()
    out = capsys.readouterr().out
    assert "⏹ Revisione interrotta. I progressi finora sono stati salvati." in out
    assert "Azione [" in out


def test_m_and_e_failure_reprompts_without_full_redraw(tmp_path, monkeypatch, capsys):
    lesson_dir = str(tmp_path)
    _setup_review_environment(lesson_dir)

    sci_issues = [_create_sample_science_issue("sci_001", "U1", "distillazione", "distillazione")]
    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump([iss.model_dump(mode="json") for iss in sci_issues], f)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    keys = iter(["m", "m", "a"])
    monkeypatch.setattr("rt.pipeline.issue_review.read_single_key", lambda *a, **kw: next(keys))

    with patch("rt.pipeline.issue_review.edit_text_in_editor", side_effect=["Nel processo di distillazione abbiamo una reazione esotermica importante.", ""]):
        res = run_interactive_review(lesson_dir, "science", channel="terminal")

    assert res is True
    out = capsys.readouterr().out
    assert "Azione [" in out
    assert "✔ Formulazione originale mantenuta." in out



