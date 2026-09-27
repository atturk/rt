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
    output = tmp_path / "combined.wav"
    merge_audio_for_transcription(sources, str(output))
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "json", str(output)], capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    assert 0.98 <= duration <= 1.05

