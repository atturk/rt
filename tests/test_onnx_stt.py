"""Motore Parakeet ONNX: finestre fisse, normalizzazione, cucitura parole, download con SHA256."""
import hashlib
import io
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pytest

from rt.core import onnx_stt
from rt.core.config import TranscriptionConfig, default_engine, effective_engine


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("RT_DATA_DIR", str(data_dir))
    monkeypatch.delenv("RT_STT_MODELS_DIR", raising=False)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    onnx_stt.clear_loaded()
    yield tmp_path, data_dir
    onnx_stt.clear_loaded()


class WindowedFakeAsr:
    """Simula asr.recognize(waveform, sample_rate) finestra per finestra."""

    def __init__(self, per_window):
        self.per_window = list(per_window)
        self.calls = []

    def recognize(self, waveform, sample_rate):
        assert sample_rate == 16_000
        assert waveform.dtype == np.float32
        idx = len(self.calls)
        self.calls.append(waveform.copy())
        return self.per_window[idx]


def _res(tokens, stamps, probs=None):
    if probs is None:
        probs = [0.9] * len(tokens)
    return SimpleNamespace(
        text="".join(tokens).strip(),
        tokens=tokens,
        timestamps=stamps,
        logprobs=[float(np.log(p)) for p in probs],
    )


def _mock_streaming_wave(monkeypatch, wave_arr, chunk_samples=16_000):
    def fake_iter(audio_path, chunk_samples=chunk_samples, cancel_token=None):
        for start in range(0, len(wave_arr), chunk_samples):
            onnx_stt._check_cancelled(cancel_token)
            yield wave_arr[start : start + chunk_samples]

    monkeypatch.setattr(onnx_stt, "_iter_pcm_chunks", fake_iter)


def test_words_and_segments_have_macparakeet_shape(monkeypatch):
    wave_arr = np.full(16_000 * 6, 0.05, dtype=np.float32)
    _mock_streaming_wave(monkeypatch, wave_arr)
    asr = WindowedFakeAsr([
        _res(
            [" Ci", "ao", " a", " tutti", " Bene", "."],
            [1.0, 1.2, 1.6, 2.0, 5.0, 5.4],
            [0.9, 0.7, 0.99, 0.8, 0.5, 1.0],
        )
    ])
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None, cancel_token=None: asr)

    seen = []
    data = onnx_stt.transcribe_onnx("lezione.m4a", on_percent=seen.append)

    assert data["text"] == "Ciao a tutti Bene."
    assert data["rawTranscript"] == "Ciao a tutti Bene."
    assert data["model"] == onnx_stt.MODEL_LABEL
    first, second = data["transcriptSegments"]
    assert first["wordRange"] == {"startIndex": 0, "endIndexExclusive": 3}
    assert first["startMs"] == 1000.0
    assert first["endMs"] == 2400.0  # chiuso prima della pausa > 0.8s
    assert second["wordRange"] == {"startIndex": 3, "endIndexExclusive": 4}
    assert second["text"] == "Bene."
    words = data["wordTimestamps"]
    assert [w["word"] for w in words] == ["Ciao", "a", "tutti", "Bene."]
    assert words[0] == {"word": "Ciao", "startMs": 1000.0, "endMs": 1600.0, "confidence": 0.8}
    assert first["confidence"] == round((0.8 + 0.99 + 0.8) / 3, 4)
    assert seen[-1] == 100 and seen == sorted(seen)


def test_segments_close_on_punctuation_pause_and_30s_limit():
    # 1) Punteggiatura finale (. ! ?) chiude, la virgola no
    words_punct = [
        {"word": "uno,", "start": 0.0, "last_token_start": 0.0, "confidence": 0.9},
        {"word": "due.", "start": 0.3, "last_token_start": 0.3, "confidence": 0.9},
        {"word": "tre!", "start": 0.6, "last_token_start": 0.6, "confidence": 0.9},
        {"word": "quattro?", "start": 0.9, "last_token_start": 0.9, "confidence": 0.9},
    ]
    segs, _ = onnx_stt._build_segments(words_punct, duration=2.0)
    assert [s["text"] for s in segs] == ["uno, due.", "tre!", "quattro?"]

    # 2) Pausa > 0.8 s chiude il segmento
    words_pause = [
        {"word": "prima", "start": 0.0, "last_token_start": 0.0, "confidence": 0.9},
        {"word": "parte", "start": 0.4, "last_token_start": 0.4, "confidence": 0.9},
        {"word": "dopo", "start": 1.5, "last_token_start": 1.5, "confidence": 0.9},  # gap 1.1s > 0.8s
    ]
    segs_p, _ = onnx_stt._build_segments(words_pause, duration=3.0)
    assert [s["text"] for s in segs_p] == ["prima parte", "dopo"]

    # 3) Durata massima ~30 s senza punteggiatura né pause > 0.8 s
    words_long = [
        {"word": f"w{i}", "start": i * 0.5, "last_token_start": i * 0.5, "confidence": 0.9}
        for i in range(80)  # 40 s totali
    ]
    segs_l, _ = onnx_stt._build_segments(words_long, duration=40.5)
    assert len(segs_l) == 2
    assert (segs_l[0]["endMs"] - segs_l[0]["startMs"]) <= 30_000.0
    assert segs_l[0]["wordRange"]["endIndexExclusive"] == segs_l[1]["wordRange"]["startIndex"]


def test_word_stitching_across_windows_avoids_duplicates_and_losses(monkeypatch):
    # Audio da 11 s -> 3 finestre: [0..6], [4.5..10.5], [9.0..11.0]
    # Tagli: cut0 = 5.25s, cut1 = 9.75s, cut2 = inf
    wave_arr = np.full(16_000 * 11, 0.05, dtype=np.float32)
    _mock_streaming_wave(monkeypatch, wave_arr)

    asr = WindowedFakeAsr([
        # Finestra 0 (off=0.0, cut=5.25): "uno due tre quattro" (4.8s = quattro), "cinque" a 5.3s (>5.25 -> scartato qui)
        _res(
            [" uno", " due", " tre", " quattro,", " cinque"],
            [1.0, 2.0, 4.4, 4.8, 5.3],
        ),
        # Finestra 1 (off=4.5, prev_cut=5.25, cut=9.75):
        # "tre" (4.7) e "quattro" (5.26, punteggiatura diversa ma nelle ultime 3 entro 1.5s) -> scartate!
        # "cinque" (5.32) -> tenuta! "sei" (9.2) e "sette" (9.6) -> tenute! "otto" (9.9 > 9.75) -> scartato qui!
        _res(
            [" tre", " quattro", " cinque", " sei", " sette", " otto"],
            [0.2, 0.76, 0.82, 4.7, 5.1, 5.4],
        ),
        # Finestra 2 (off=9.0, prev_cut=9.75, cut=inf):
        # "sette" (9.76 >= 9.75 ma ripete ultime 3 entro 1.5s) -> scartata!
        # "otto" (9.80) e "nove." (10.2) -> tenute!
        _res(
            [" sei", " sette", " otto", " nove."],
            [0.2, 0.76, 0.80, 1.2],
        ),
    ])
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None, cancel_token=None: asr)

    data = onnx_stt.transcribe_onnx("lezione.m4a")
    assert [w["word"] for w in data["wordTimestamps"]] == [
        "uno", "due", "tre", "quattro,", "cinque", "sei", "sette", "otto", "nove.",
    ]
    assert data["text"] == "uno due tre quattro, cinque sei sette otto nove."


def test_normalization_gain_is_limited_by_peak_and_clips(monkeypatch):
    # 1) Segnale basso senza picchi: rms = 0.006, picco = 0.006 -> 0.1/0.006 = 16.67 (< 4/0.006)
    assert onnx_stt._compute_gain(0.006, 0.006) == pytest.approx(0.1 / 0.006)

    # 2) Segnale basso con un picco forte (0.8): guadagno limitato da 4 / picco = 5.0 (non 16.67)
    wave_arr = np.full(16_000 * 2, 0.006, dtype=np.float32)
    wave_arr[100] = 0.8
    wave_arr[101] = -0.8
    _mock_streaming_wave(monkeypatch, wave_arr, chunk_samples=4_000)

    asr = WindowedFakeAsr([_res([" Ciao."], [0.5])])
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None, cancel_token=None: asr)

    onnx_stt.transcribe_onnx("picco.wav")
    assert len(asr.calls) == 1
    passed = asr.calls[0]
    assert passed.dtype == np.float32
    assert np.max(passed) <= 1.0 and np.min(passed) >= -1.0
    # Picco 0.8 * ~5.0 -> clippato a +1.0 / -1.0, campioni da 0.006 -> ~0.03
    assert passed[100] == pytest.approx(1.0)
    assert passed[101] == pytest.approx(-1.0)
    assert passed[0] == pytest.approx(0.006 * 5.0, rel=0.05)


def test_chunked_decode_matches_full_decode(tmp_path, monkeypatch):
    # Crea un WAV sintetico 16 kHz mono s16le con 2.5 s di campioni non banali
    sr = 16_000
    n_samples = int(sr * 2.5)
    t = np.arange(n_samples, dtype=np.float32)
    expected_i16 = (np.sin(2 * np.pi * 440.0 * t / sr) * 12000).astype("<i2")
    raw_pcm = expected_i16.tobytes()

    wav_path = tmp_path / "sintetico.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(raw_pcm)

    # Finto ffmpeg che restituisce il PCM del wav a blocchi dispari (es. 777 byte alla volta)
    class FakeStdout:
        def __init__(self, data, step=777):
            self._buf = io.BytesIO(data)
            self._step = step

        def read(self, n):
            return self._buf.read(min(n, self._step))

        def close(self):
            self._buf.close()

    class FakeProc:
        def __init__(self, data):
            self.stdout = FakeStdout(data)
            self.stderr = io.BytesIO(b"")
            self._rc = 0

        def poll(self):
            return self._rc

        def wait(self, timeout=None):
            return self._rc

    monkeypatch.setattr("rt.core.media_tools.require_ffmpeg", lambda: "fake-ffmpeg")
    monkeypatch.setattr(onnx_stt.subprocess, "Popen", lambda *a, **kw: FakeProc(raw_pcm))

    full = onnx_stt._decode(str(wav_path))
    chunked = list(onnx_stt._iter_pcm_chunks(str(wav_path), chunk_samples=1_000))
    rebuilt = np.concatenate(chunked)

    assert len(full) == n_samples
    assert len(rebuilt) == n_samples
    assert np.allclose(rebuilt, full)
    assert np.allclose(rebuilt, expected_i16.astype(np.float32) / 32768.0)


def test_no_speech_is_an_error(monkeypatch):
    wave_arr = np.zeros(16_000, dtype=np.float32)
    _mock_streaming_wave(monkeypatch, wave_arr)
    asr = WindowedFakeAsr([_res([], [])])
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None, cancel_token=None: asr)
    with pytest.raises(RuntimeError, match="Nessuna voce"):
        onnx_stt.transcribe_onnx("muto.wav")


def test_cancel_between_windows(monkeypatch):
    from rt.services.context import CancelToken, RunCancelled

    wave_arr = np.full(16_000 * 11, 0.05, dtype=np.float32)
    _mock_streaming_wave(monkeypatch, wave_arr)
    token = CancelToken()

    class CancellingAsr:
        def __init__(self):
            self.count = 0

        def recognize(self, waveform, sample_rate):
            self.count += 1
            token.cancel()
            return _res([" uno"], [0.5])

    asr = CancellingAsr()
    monkeypatch.setattr(onnx_stt, "_models", lambda on_progress=None, cancel_token=None: asr)

    with pytest.raises(RunCancelled):
        onnx_stt.transcribe_onnx("lezione.m4a", cancel_token=token)
    assert asr.count == 1


def _serve_files(files_map: dict[str, bytes]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.lstrip("/")
            payload = files_map.get(name)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                start = int(rng.removeprefix("bytes=").split("-", 1)[0] or "0")
                chunk = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_download_verifies_sha256_resumes_part_and_cleans_legacy(isolated_env, monkeypatch):
    _tmp, data_dir = isolated_env
    models_root = data_dir / "models"

    # Pre-popola vecchio modello int8 e VAD Silero
    legacy_int8 = models_root / onnx_stt.LEGACY_MODEL_NAME
    legacy_vad = models_root / onnx_stt.LEGACY_VAD_NAME
    legacy_int8.mkdir(parents=True)
    legacy_vad.mkdir(parents=True)
    (legacy_int8 / "encoder-model.int8.onnx").write_bytes(b"old-int8")
    (legacy_vad / "silero_vad.onnx").write_bytes(b"old-vad")

    files_data = {
        onnx_stt.ENCODER_FILENAME: b"E" * 1200,
        onnx_stt.DECODER_FILENAME: b"D" * 600,
        onnx_stt.VOCAB_FILENAME: b"<blk> 0\n a 1\n",
        onnx_stt.CONFIG_FILENAME: b'{"model_type": "nemo-conformer-tdt"}\n',
    }
    shas = {k: hashlib.sha256(v).hexdigest() for k, v in files_data.items()}

    srv, base_url = _serve_files(files_data)
    try:
        # 1) SHA256 sbagliato -> errore OnnxSttUnavailable e nessun modello promosso
        monkeypatch.setattr(
            onnx_stt,
            "_model_files",
            lambda: [
                (k, f"{base_url}/{k}", len(v), "0" * 64 if k == onnx_stt.ENCODER_FILENAME else shas[k])
                for k, v in files_data.items()
            ],
        )
        with pytest.raises(onnx_stt.OnnxSttUnavailable, match="SHA256"):
            onnx_stt._download_resumable()
        assert not (models_root / onnx_stt.MODEL_DIR_NAME).exists()
        assert not (models_root / f"{onnx_stt.MODEL_DIR_NAME}.partial" / f"{onnx_stt.ENCODER_FILENAME}.part").exists()
        # Finché il nuovo download fallisce, il vecchio non viene toccato
        assert legacy_int8.exists() and legacy_vad.exists()

        # 2) SHA256 giusti + ripresa da .part -> Range 206, promozione atomica, pulizia legacy
        partial_dir = models_root / f"{onnx_stt.MODEL_DIR_NAME}.partial"
        partial_dir.mkdir(parents=True, exist_ok=True)
        (partial_dir / f"{onnx_stt.ENCODER_FILENAME}.part").write_bytes(files_data[onnx_stt.ENCODER_FILENAME][:400])

        monkeypatch.setattr(
            onnx_stt,
            "_model_files",
            lambda: [(k, f"{base_url}/{k}", len(v), shas[k]) for k, v in files_data.items()],
        )
        progress_msgs = []
        final = onnx_stt._download_resumable(on_progress=progress_msgs.append)
        assert final == str(models_root / onnx_stt.MODEL_DIR_NAME)
        for fname, content in files_data.items():
            assert (models_root / onnx_stt.MODEL_DIR_NAME / fname).read_bytes() == content
        assert not partial_dir.exists()
        assert not legacy_int8.exists()
        assert not legacy_vad.exists()
        assert any("100%" in m for m in progress_msgs)
    finally:
        srv.shutdown()
        srv.server_close()


def test_resumable_download_keeps_part_on_network_failure(isolated_env, monkeypatch):
    import requests

    _tmp, data_dir = isolated_env
    models_root = data_dir / "models"
    monkeypatch.setattr(
        onnx_stt,
        "_model_files",
        lambda: [(onnx_stt.ENCODER_FILENAME, "http://127.0.0.1:1/encoder.onnx", 1000, "a" * 64)],
    )

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
        onnx_stt._download_resumable()

    part = models_root / f"{onnx_stt.MODEL_DIR_NAME}.partial" / f"{onnx_stt.ENCODER_FILENAME}.part"
    assert part.is_file() and part.stat().st_size == 350
    assert not (models_root / onnx_stt.MODEL_DIR_NAME).exists()


def test_models_loaded_once_with_q8pc_default_options_and_no_vad(isolated_env, monkeypatch):
    import onnx_asr

    _tmp, data_dir = isolated_env
    model_path = str(data_dir / "models" / onnx_stt.MODEL_DIR_NAME)
    monkeypatch.setattr(onnx_stt, "_download_resumable", lambda *a, **kw: model_path)
    _mock_streaming_wave(monkeypatch, np.full(16_000 * 2, 0.05, dtype=np.float32))

    loads = []

    class FakeModel:
        def with_vad(self, *a, **kw):
            raise AssertionError("Il VAD Silero non deve più essere usato")

        def with_timestamps(self):
            return WindowedFakeAsr([_res([" Ciao"], [0.1])] * 2)

    def fake_load_model(name, path, **kw):
        loads.append((name, path, kw))
        return FakeModel()

    monkeypatch.setattr(onnx_asr, "load_model", fake_load_model)
    monkeypatch.setattr(onnx_asr, "load_vad", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no vad")))

    onnx_stt.ensure_model()
    onnx_stt.transcribe_onnx("a.m4a")
    onnx_stt.transcribe_onnx("b.m4a")
    assert loads == [(onnx_stt.MODEL_NAME, model_path, {"quantization": "q8pc"})]


def test_default_engine_per_system(monkeypatch, tmp_path):
    from rt.core.config import load_config

    monkeypatch.delenv("RT_DEFAULT_STT_ENGINE", raising=False)
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr("sys.platform", "win32")
    assert default_engine() == "parakeet"
    monkeypatch.setattr("sys.platform", "darwin")
    assert default_engine() == "macparakeet"

    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    assert default_engine() == "macparakeet"

    # Chi ha già salvato transcription.engine in config lo tiene
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "general.yaml").write_text("transcription:\n  engine: macparakeet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_config().transcription.engine == "macparakeet"


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

    # Su Apple Silicon non ricade più su ONNX: il job scarica macparakeet
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"

    # Su Mac Intel senza binario ricade su Parakeet ONNX se disponibile
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: False)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "parakeet"

    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"

    assert effective_engine(TranscriptionConfig(engine="custom")) == "custom"
    assert effective_engine(TranscriptionConfig(engine="parakeet")) == "parakeet"

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert effective_engine(TranscriptionConfig(engine="macparakeet")) == "macparakeet"


def test_mac_without_macparakeet_uses_parakeet_fallback(monkeypatch, isolated_env):
    from rt.core import components
    from rt.pipeline import setup
    from rt.services import jobs
    from rt.services.pipeline_service import transcription_unavailable_reason

    tmp_path, _data_dir = isolated_env
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "general.yaml").write_text("transcription:\n  engine: macparakeet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "darwin")

    # Mac Apple Silicon con binario -> macparakeet
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "/opt/homebrew/bin/macparakeet-cli")
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    assert jobs.detect_stt_capability("auto") == "macparakeet"
    assert transcription_unavailable_reason() is None

    # Mac Apple Silicon senza binario -> resta macparakeet e il setup scarica il componente
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    assert jobs.detect_stt_capability("auto") == "macparakeet"
    assert transcription_unavailable_reason() is None

    downloaded = []
    fake_bin = tmp_path / "bin" / "macparakeet-cli"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(components, "ensure_macparakeet", lambda **kw: downloaded.append(kw) or str(fake_bin))

    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"fake-audio")

    def fake_spinner(cmd, label, **kw):
        out_dir = cmd[cmd.index("--output-dir") + 1]
        import json
        with open(f"{out_dir}/out.json", "w", encoding="utf-8") as f:
            json.dump({"transcriptSegments": [{"startMs": 0.0, "endMs": 1000.0, "text": "Lezione Apple Silicon."}], "wordTimestamps": []}, f)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(setup, "_run_transcribe_with_spinner", fake_spinner)
    res_mac = setup.run_setup(
        audio=str(audio),
        date="2026-10-09",
        materia="FISIOLOGIA",
        dest_dir=str(tmp_path / "lezioni_mac"),
        interactive=False,
    )
    assert len(downloaded) == 1
    assert res_mac["lesson_dir"]

    # Mac Intel senza binario + ONNX -> fallback a parakeet, setup non solleva
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: False)
    assert jobs.detect_stt_capability("auto") == "parakeet"
    assert transcription_unavailable_reason() is None

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

    # Mac Intel senza binario e senza ONNX -> motivo non disponibile + SetupError prima di creare la lezione
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    assert transcription_unavailable_reason() is not None
    lessons_dir = tmp_path / "lezioni_vuote"
    audio_unavail = tmp_path / "lezione_unavail.m4a"
    audio_unavail.write_bytes(b"fake-audio-unavail")
    with pytest.raises(setup.SetupError, match="macparakeet-cli non trovato"):
        setup.run_setup(
            audio=str(audio_unavail),
            date="2026-10-11",
            materia="FISIOLOGIA",
            dest_dir=str(lessons_dir),
            interactive=False,
        )
    assert not lessons_dir.exists()

    # Audio già trascritto in archivio -> riusato anche senza binario/ONNX
    from rt.core import archive
    from rt.core.idempotency import compute_file_sha256

    cached_audio = tmp_path / "cached.m4a"
    cached_audio.write_bytes(b"cached-audio")
    archive.register_file(str(cached_audio), nome="cached.m4a", tipo="audio")
    sha = compute_file_sha256(str(cached_audio))
    archive.store_transcript(
        sha,
        "macparakeet",
        {
            "duration": 1.0,
            "segments": [{"id": "s1", "start_seconds": 0.0, "end_seconds": 1.0, "text_raw": "Già trascritto."}],
        },
    )
    cached_res = setup.run_setup(
        audio=str(cached_audio),
        date="2026-10-12",
        materia="FISIOLOGIA",
        dest_dir=str(lessons_dir),
        interactive=False,
    )
    assert cached_res["status"] == "setup_completato"
