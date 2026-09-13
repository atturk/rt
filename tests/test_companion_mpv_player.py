"""
Test per Task 75: companion audio player (mpv) per la review scientifica.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity, Draft, DraftUnit, SegmentsData, Segment
)
from rt.pipeline.issue_review import IssueReviewApp
from rt.core.audio_clip import (
    get_terminal_bounds,
    calculate_mpv_geometry,
    load_last_mpv_geometry,
    save_last_mpv_geometry,
    get_or_create_unit_clip,
)


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    # manifest
    manifest_data = {
        "schema_version": "1.0",
        "workflow_version": "2.0.0",
        "lesson_id": "test_lesson",
        "lesson_dir": os.path.abspath(lesson_dir),
        "date": "2026-09-13",
        "subject": "Fisica",
        "current_state": "DRAFT_VALIDATED",
        "audio_file": "audio.mp3",
        "created_at": "2026-09-13T10:00:00",
        "updated_at": "2026-09-13T10:00:00",
    }
    with open(os.path.join(lesson_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest_data, f)

    # dummy audio
    with open(os.path.join(lesson_dir, "audio.mp3"), "wb") as f:
        f.write(b"AUDIO")

    # segments.json
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="audio.mp3",
        total_duration=60.0,
        segment_count=2,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="Part 1"),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Part 2"),
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
                title="Cinematica",
                content="La velocità è la derivata della posizione rispetto al tempo.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                key_concepts=[],
            )
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)


def test_calculate_mpv_geometry_from_terminal_bounds(tmp_path):
    with patch("rt.core.audio_clip.get_terminal_bounds", return_value=(100, 50, 900, 750)), \
         patch("rt.core.audio_clip.get_mpv_last_position_path", return_value=str(tmp_path / "pos.json")):
        geom = calculate_mpv_geometry()
        # Larghezza 480, altezza calcolata, posizionata a x2=900, y1=50
        assert geom.endswith("+900+50")
        assert "480x" in geom

        # Verifica che sia stata salvata nel file di fallback
        assert load_last_mpv_geometry() == geom


def test_calculate_mpv_geometry_fallback(tmp_path):
    pos_file = str(tmp_path / "pos.json")
    with patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_mpv_last_position_path", return_value=pos_file):
        # Senza file salvato -> default
        assert calculate_mpv_geometry() == "+800+50"

        # Con file salvato -> legge da file
        save_last_mpv_geometry("500x400+1000+100")
        assert calculate_mpv_geometry() == "500x400+1000+100"


def test_unit_clip_caching(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    draft = Draft.model_validate(json.load(open(os.path.join(lesson_dir, "draft.json"))))
    unit = draft.units[0]
    segments = SegmentsData.model_validate(json.load(open(os.path.join(lesson_dir, "segments.json")))).segments

    with patch("rt.core.audio_clip.cut_clip", return_value=str(tmp_path / "temp.mp3")) as mock_cut:
        # Crea dummy temp file da muovere
        with open(str(tmp_path / "temp.mp3"), "wb") as f:
            f.write(b"CLIP")

        clip1 = get_or_create_unit_clip(lesson_dir, unit, segments)
        assert os.path.isfile(clip1)
        assert mock_cut.call_count == 1

        # Seconda chiamata -> riusa la cache, non chiama cut_clip
        clip2 = get_or_create_unit_clip(lesson_dir, unit, segments)
        assert clip1 == clip2
        assert mock_cut.call_count == 1


@pytest.mark.anyio
async def test_mpv_player_launch_and_toggle(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    iss = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="velocità è la derivata",
        reason="ok",
        suggested_fix="ok",
    )

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/usr/local/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen:

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss])
        async with app.run_test() as pilot:
            # 1° P: lancia mpv
            await pilot.press("p")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "mpv"
            assert any(a.startswith("--input-ipc-server=") for a in args)
            assert any(a.startswith("--geometry=") for a in args)
            assert "/tmp/test_clip.mp3" in args

            # 2° P: chiude mpv
            await pilot.press("p")
            mock_proc.terminate.assert_called_once()


@pytest.mark.anyio
async def test_mpv_player_autoclose_on_actions(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    iss1 = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )
    iss2 = ScienceIssue(
        id="sci_2",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 2",
        reason="reason 2",
        suggested_fix="fix 2",
    )

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/usr/local/bin/mpv"), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc):

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss1, iss2])
        async with app.run_test() as pilot:
            await pilot.press("p")  # Apre mpv
            # Premere 'a' (accetta) auto-chiude mpv
            await pilot.press("a")
            mock_proc.terminate.assert_called_once()


@pytest.mark.anyio
async def test_mpv_player_not_closed_on_edit(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    iss = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("shutil.which", return_value="/usr/local/bin/mpv"), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip.mp3"), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("rt.pipeline.issue_review.edit_text_in_editor", return_value="Testo modificato"):

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss])
        async with app.run_test() as pilot:
            await pilot.press("p")  # Apre mpv
            await pilot.press("m")  # Modifica testo (non deve chiudere mpv)
            mock_proc.terminate.assert_not_called()


@pytest.mark.anyio
async def test_mpv_player_external_close_detection(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    iss = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )

    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None

    with patch("shutil.which", return_value="/usr/local/bin/mpv"), \
         patch("rt.core.audio_clip.get_terminal_bounds", return_value=None), \
         patch("rt.core.audio_clip.get_or_create_unit_clip", return_value="/tmp/test_clip.mp3"), \
         patch("subprocess.Popen", side_effect=[mock_proc1, mock_proc2]) as mock_popen:

        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss])
        async with app.run_test() as pilot:
            await pilot.press("p")  # Apre mpv 1
            assert mock_popen.call_count == 1

            # Simula chiusura esterna di mpv (Cmd+Q)
            mock_proc1.poll.return_value = 0
            app._check_audio_proc()

            # Premendo P di nuovo deve riaprire il player anziché terminare il vecchio
            await pilot.press("p")
            assert mock_popen.call_count == 2
            mock_proc1.terminate.assert_not_called()


@pytest.mark.anyio
async def test_mpv_not_installed_error_message(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    iss = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_DOCENTE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )

    with patch("shutil.which", return_value=None):
        app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss])
        async with app.run_test() as pilot:
            await pilot.press("p")
            assert "Installa mpv con 'brew install mpv'" in (app.last_status or "")
