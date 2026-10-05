"""Regression: multiple clips must share one real playback and STT time line."""

import json
import shutil
import subprocess

import pytest

from rt.pipeline.setup import merge_audio_for_transcription


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_merge_preserves_order_and_trailing_silence(tmp_path):
    sources = []
    for index, (duration, frequency, ext) in enumerate([(0.4, 440, "wav"), (0.6, 880, "mp3")]):
        path = tmp_path / f"source{index}.{ext}"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:duration={duration}", "-y", str(path)], check=True)
        sources.append(str(path))
    output = tmp_path / "combined.m4a"
    merge_audio_for_transcription(sources, str(output))
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "json", str(output)], capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    assert 0.98 <= duration <= 1.05



@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg non disponibile")
def test_single_wav_conversion_produces_playable_mono_aac(tmp_path):
    """La conversione usa gli stessi parametri del merge con un vero ffmpeg."""
    from rt.pipeline.setup import run_setup
    from rt.core.state import read_info_yaml
    source = tmp_path / "lezione.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", "-ac", "2", "-y", str(source)], check=True)
    original = source.read_bytes()
    result = run_setup(str(source), date="2026-10-05", materia="BIOCHIMICA",
                       dest_dir=str(tmp_path / "lessons"), skip_transcribe=True, interactive=False)
    from pathlib import Path
    lesson = Path(result["lesson_dir"])
    audio_name = read_info_yaml(str(lesson / "info.yaml"))["file_audio"]
    assert audio_name == "lezione.m4a"
    assert not (lesson / source.name).exists()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_name,sample_rate,channels", "-of", "json", str(lesson / audio_name)],
                           capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream == {"codec_name": "aac", "sample_rate": "48000", "channels": 1}
    assert source.read_bytes() == original
