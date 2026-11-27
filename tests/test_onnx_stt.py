"""Motore Parakeet ONNX: formato di uscita uguale a macparakeet-cli, scelta del motore."""
from types import SimpleNamespace

import numpy as np
import pytest

from rt.core import onnx_stt
from rt.core.config import TranscriptionConfig, default_engine, effective_engine


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


def test_effective_engine_macparakeet_fallback(monkeypatch):
    from rt.pipeline import setup

    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "parakeet"

    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "/opt/homebrew/bin/macparakeet-cli")
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"

    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"

    assert effective_engine(TranscriptionConfig(engine="custom")) == "custom"
    assert effective_engine(TranscriptionConfig(engine="parakeet")) == "parakeet"

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"


def test_mac_without_macparakeet_uses_parakeet_fallback(monkeypatch, tmp_path):
    from rt.pipeline import setup
    from rt.services import jobs
    from rt.services.pipeline_service import transcription_unavailable_reason

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "general.yaml").write_text("transcription:\n  engine: macparakeet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "darwin")

    # Mac con binario -> macparakeet
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "/opt/homebrew/bin/macparakeet-cli")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert jobs.detect_stt_capability("auto") == "macparakeet"
    assert transcription_unavailable_reason() is None

    # Mac senza binario + ONNX -> fallback a parakeet, setup non solleva
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    assert jobs.detect_stt_capability("auto") == "parakeet"
    assert transcription_unavailable_reason() is None

    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"fake-audio")
    called = []

    def fake_transcribe_onnx(path, on_percent=None, on_progress=None):
        called.append(path)
        return {
            "rawTranscript": "Lezione di prova.",
            "text": "Lezione di prova.",
            "transcriptSegments": [{"startMs": 0.0, "endMs": 1000.0, "text": "Lezione di prova.", "confidence": 0.9}],
            "wordTimestamps": [],
            "model": onnx_stt.MODEL_LABEL,
        }

    monkeypatch.setattr(onnx_stt, "transcribe_onnx", fake_transcribe_onnx)
    res = setup.run_setup(
        audio=str(audio),
        date="2026-10-10",
        materia="FISIOLOGIA",
        dest_dir=str(tmp_path / "lezioni"),
        interactive=False,
    )
    assert len(called) == 1
    assert res["lesson_dir"]

    # Mac senza binario e senza ONNX -> motivo non disponibile + SetupError come oggi
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    assert transcription_unavailable_reason() is not None
    with pytest.raises(setup.SetupError, match="macparakeet-cli non trovato"):
        setup.run_setup(
            audio=str(audio),
            date="2026-10-11",
            materia="FISIOLOGIA",
            dest_dir=str(tmp_path / "lezioni"),
            interactive=False,
        )


def test_resumable_download_uses_part_and_range_and_reports_eta(tmp_path, monkeypatch):
    import requests

    monkeypatch.setenv("RT_STT_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(onnx_stt, "_model_patterns", lambda name, q, vad=False: ("fake/repo", ["*.bin"]))

    files_data = {
        "encoder.bin": b"A" * 1000,
        "vocab.txt": b"B" * 200,
    }
    monkeypatch.setattr(
        onnx_stt,
        "_list_repo_files",
        lambda repo_id, patterns: [(k, len(v)) for k, v in files_data.items()],
    )
    monkeypatch.setattr("huggingface_hub.hf_hub_url", lambda repo_id, filename: f"https://example.test/{filename}")

    # Pre-popoliamo un .part interrotto a 400 byte per encoder.bin
    partial_dir = tmp_path / f"{onnx_stt.MODEL_NAME}.partial"
    partial_dir.mkdir(parents=True)
    (partial_dir / "encoder.bin.part").write_bytes(files_data["encoder.bin"][:400])

    seen_headers = []

    class FakeResp:
        def __init__(self, status_code, body, content_range=""):
            self.status_code = status_code
            self._body = body
            self.headers = {"Content-Range": content_range} if content_range else {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")

        def iter_content(self, chunk_size=65536):
            for i in range(0, len(self._body), 200):
                yield self._body[i : i + 200]

    def fake_get(url, headers=None, stream=True, timeout=None, allow_redirects=True):
        fname = url.rsplit("/", 1)[-1]
        seen_headers.append((fname, dict(headers or {})))
        if fname == "encoder.bin":
            rng = (headers or {}).get("Range")
            assert rng == "bytes=400-"
            return FakeResp(206, files_data[fname][400:], content_range="bytes 400-999/1000")
        return FakeResp(200, files_data[fname])

    monkeypatch.setattr(requests, "get", fake_get)

    # Verifica anche rate-limit a 1/s e formato ETA
    clock = [100.0]
    monkeypatch.setattr(onnx_stt.time, "monotonic", lambda: clock[0])

    progress_msgs = []
    # Avanziamo il clock ad ogni chunk simulato tramite wrapper
    orig_stream = onnx_stt._stream_response

    def ticking_stream(resp, part_file, dest_file, expected_size, resume_from, on_chunk, cancel_token):
        def wrapped_chunk(n):
            clock[0] += 1.0
            on_chunk(n)
        return orig_stream(resp, part_file, dest_file, expected_size, resume_from, wrapped_chunk, cancel_token)

    monkeypatch.setattr(onnx_stt, "_stream_response", ticking_stream)

    final = onnx_stt._download_resumable(onnx_stt.MODEL_NAME, onnx_stt.QUANTIZATION, on_progress=progress_msgs.append)
    assert final == str(tmp_path / onnx_stt.MODEL_NAME)
    assert (tmp_path / onnx_stt.MODEL_NAME / "encoder.bin").read_bytes() == files_data["encoder.bin"]
    assert (tmp_path / onnx_stt.MODEL_NAME / "vocab.txt").read_bytes() == files_data["vocab.txt"]
    assert not (tmp_path / f"{onnx_stt.MODEL_NAME}.partial").exists()
    assert ("encoder.bin", {"Range": "bytes=400-"}) in seen_headers
    assert any("Scarico il modello di trascrizione:" in m and "%" in m and "MB" in m for m in progress_msgs)
    assert any("100%" in m for m in progress_msgs)
    assert any("pochi secondi" in m or "circa" in m for m in progress_msgs)


def test_resumable_download_keeps_part_on_network_failure(tmp_path, monkeypatch):
    import requests

    monkeypatch.setenv("RT_STT_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(onnx_stt, "_model_patterns", lambda name, q, vad=False: ("fake/repo", ["*.bin"]))
    monkeypatch.setattr(onnx_stt, "_list_repo_files", lambda repo_id, patterns: [("encoder.bin", 1000)])
    monkeypatch.setattr("huggingface_hub.hf_hub_url", lambda repo_id, filename: f"https://example.test/{filename}")

    class FailingResp:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=65536):
            yield b"X" * 350
            raise requests.ConnectionError("rete assente")

    monkeypatch.setattr(requests, "get", lambda *a, **kw: FailingResp())
    with pytest.raises(onnx_stt.OnnxSttUnavailable, match="connessione"):
        onnx_stt._download_resumable(onnx_stt.MODEL_NAME, onnx_stt.QUANTIZATION)

    part = tmp_path / f"{onnx_stt.MODEL_NAME}.partial" / "encoder.bin.part"
    assert part.is_file() and part.stat().st_size == 350
    assert not (tmp_path / onnx_stt.MODEL_NAME).exists()
