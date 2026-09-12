"""
Test per Task 35: MacParakeet transcribe deadlock fix, --output-dir, --no-diarize, escape virgola e confidence per-parola.
"""

import os
import json
import subprocess
import threading
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.setup import clean_input_path, run_setup
from rt.core.segments import parse_segments_from_json


def test_clean_input_path_escaped_comma():
    raw = r"/Users/foo/ANATOMIA I\, 6 maggio.m4a"
    cleaned = clean_input_path(raw)
    assert cleaned == "/Users/foo/ANATOMIA I, 6 maggio.m4a"


def test_transcribe_cmd_contains_output_dir_and_no_diarize(tmp_path):
    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_audio.m4a")
    with open(audio_file, "wb") as f:
        f.write(b"fake audio data")

    calls = []

    def fake_transcribe(cmd, label):
        calls.append(cmd)
        # Trova output-dir e scrivi un file json
        if "--output-dir" in cmd:
            out_dir = cmd[cmd.index("--output-dir") + 1]
            os.makedirs(out_dir, exist_ok=True)
            out_json = os.path.join(out_dir, "test_audio.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump({
                    "rawTranscript": "Test",
                    "transcriptSegments": [{"id": "s1", "startMs": 0, "endMs": 1000, "text": "Test"}]
                }, f)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/macparakeet-cli"):
        with patch("rt.pipeline.setup._run_transcribe_with_spinner", side_effect=fake_transcribe):
            run_setup(
                audio=audio_file,
                date="2026-09-12",
                materia="TEST",
                argomenti="Test",
                dest_dir=dest_dir,
                interactive=False
            )

    assert len(calls) == 1
    cmd = calls[0]
    assert "--output-dir" in cmd
    assert "--no-diarize" in cmd


def test_transcribe_large_word_timestamps_no_deadlock(tmp_path):
    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "large_lecture.m4a")
    with open(audio_file, "wb") as f:
        f.write(b"fake large audio data")

    # Genera 10.000 entry per wordTimestamps (~500KB di JSON)
    words = []
    for i in range(10000):
        words.append({
            "word": f"word_{i}",
            "startMs": i * 500,
            "endMs": (i + 1) * 500,
            "confidence": 0.95,
            "speakerId": 0
        })

    payload = {
        "rawTranscript": " ".join([w["word"] for w in words]),
        "transcriptSegments": [
            {
                "id": "seg_1",
                "startMs": 0,
                "endMs": 5000000,
                "text": "Large transcription",
                "wordRange": {"startIndex": 0, "endIndexExclusive": 10000}
            }
        ],
        "wordTimestamps": words
    }

    def fake_transcribe(cmd, label):
        if "--output-dir" in cmd:
            out_dir = cmd[cmd.index("--output-dir") + 1]
            os.makedirs(out_dir, exist_ok=True)
            out_json = os.path.join(out_dir, "large_lecture.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result_container = []

    def run_target():
        with patch("shutil.which", return_value="/usr/local/bin/macparakeet-cli"):
            with patch("rt.pipeline.setup._run_transcribe_with_spinner", side_effect=fake_transcribe):
                res = run_setup(
                    audio=audio_file,
                    date="2026-09-12",
                    materia="TEST",
                    argomenti="Large",
                    dest_dir=dest_dir,
                    interactive=False
                )
                result_container.append(res)

    t = threading.Thread(target=run_target)
    t.start()
    t.join(timeout=10.0)
    assert not t.is_alive(), "Il thread di trascrizione non ha completato entro 10 secondi (possibile deadlock)"
    assert len(result_container) == 1
    lesson_dir = result_container[0]["lesson_dir"]
    raw_json_path = os.path.join(lesson_dir, "trascritto grezzo.json")
    with open(raw_json_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "wordTimestamps" in saved_data
    assert len(saved_data["wordTimestamps"]) == 10000


def test_parse_segments_from_json_aggregated_confidence(tmp_path):
    json_path = os.path.join(tmp_path, "test_conf.json")
    payload = {
        "transcriptSegments": [
            {
                "id": "s1",
                "startMs": 0,
                "endMs": 1000,
                "text": "ciao mondo",
                "wordRange": {"startIndex": 0, "endIndexExclusive": 2}
            },
            {
                "id": "s2",
                "startMs": 1000,
                "endMs": 2000,
                "text": "senza word range"
            }
        ],
        "wordTimestamps": [
            {"word": "ciao", "confidence": 0.8},
            {"word": "mondo", "confidence": 0.9}
        ]
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    segments = parse_segments_from_json(json_path)
    assert len(segments) == 2
    assert segments[0].confidence == pytest.approx(0.85)
    assert segments[1].confidence is None
