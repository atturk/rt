"""Motore Parakeet ONNX: formato di uscita uguale a macparakeet-cli, scelta del motore."""
from types import SimpleNamespace

import numpy as np
import pytest

from rt.core import onnx_stt
from rt.core.config import default_engine


class FakeAsr:
    def __init__(self, results):
        self.results = results

    def recognize(self, waveform, sample_rate):
        assert sample_rate == 16_000
        return iter(self.results)


def _seg(start, end, text, tokens, stamps, probs):
    return SimpleNamespace(start=start, end=end, text=text, tokens=tokens, timestamps=stamps,
                           logprobs=[float(np.log(p)) for p in probs])


def test_words_and_segments_have_macparakeet_shape(monkeypatch):
    results = [
        _seg(1.0, 3.0, "Ciao a tutti", [" Ci", "ao", " a", " tutti"], [0.0, 0.2, 0.6, 1.0], [0.9, 0.7, 0.99, 0.8]),
        _seg(4.0, 4.5, "", [], [], []),
        _seg(5.0, 6.0, "Bene.", [" Bene", "."], [0.1, 0.5], [0.5, 1.0]),
    ]
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None: FakeAsr(results))
    monkeypatch.setattr(onnx_stt, "_decode", lambda path: np.zeros(16_000 * 6, dtype=np.float32))
    seen = []
    data = onnx_stt.transcribe_onnx("lezione.m4a", on_percent=seen.append)

    assert data["text"] == "Ciao a tutti Bene."
    first, second = data["transcriptSegments"]
    assert (first["startMs"], first["endMs"], first["wordRange"]) == (1000.0, 3000.0, {"startIndex": 0, "endIndexExclusive": 3})
    assert second["wordRange"] == {"startIndex": 3, "endIndexExclusive": 4}
    words = data["wordTimestamps"]
    assert [w["word"] for w in words] == ["Ciao", "a", "tutti", "Bene."]
    assert words[0] == {"word": "Ciao", "startMs": 1000.0, "endMs": 1600.0, "confidence": 0.8}
    assert words[2]["endMs"] == 3000.0  # l'ultima parola finisce col segmento
    assert first["confidence"] == round((0.8 + 0.99 + 0.8) / 3, 4)
    assert seen[-1] == 100 and seen == sorted(seen)


def test_no_speech_is_an_error(monkeypatch):
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None: FakeAsr([_seg(0, 1, " ", [], [], [])]))
    monkeypatch.setattr(onnx_stt, "_decode", lambda path: np.zeros(16_000, dtype=np.float32))
    with pytest.raises(RuntimeError, match="Nessuna voce"):
        onnx_stt.transcribe_onnx("muto.wav")


def test_partial_download_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_STT_MODELS_DIR", str(tmp_path))

    def broken(name, path, **kw):
        (tmp_path / f"{name}.partial").mkdir()
        raise OSError("rete giù")

    with pytest.raises(onnx_stt.OnnxSttUnavailable, match="connessione"):
        onnx_stt._download(broken, "silero", None)
    assert not (tmp_path / "silero").exists() and not (tmp_path / "silero.partial").exists()

    def ok(name, path, **kw):
        (tmp_path / f"{name}.partial").mkdir()

    assert onnx_stt._download(ok, "silero", None) == str(tmp_path / "silero")


def test_default_engine_per_system(monkeypatch):
    monkeypatch.delenv("RT_DEFAULT_STT_ENGINE", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    assert default_engine() == "parakeet"
    monkeypatch.setattr("sys.platform", "darwin")
    assert default_engine() == "macparakeet"


def test_parakeet_engine_runs_on_any_worker(monkeypatch, tmp_path):
    from rt.services import jobs
    from rt.services.pipeline_service import transcription_unavailable_reason
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "general.yaml").write_text("transcription:\n  engine: parakeet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert transcription_unavailable_reason() is None
    assert jobs.detect_stt_capability("auto") == "parakeet"
