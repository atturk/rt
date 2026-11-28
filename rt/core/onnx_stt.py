"""
rt.core.onnx_stt
Motore di trascrizione locale "parakeet": Parakeet TDT 0.6B v3 (multilingue, italiano
compreso) in formato ONNX tramite onnx-asr (quantizzato int8 per canale, solo MatMul).
Gira su Windows, Linux e macOS senza GPU; su Mac Apple Silicon resta consigliato
macparakeet, più veloce sul Neural Engine.

Il modello (~900 MB, CC-BY-4.0 NVIDIA) si scarica dagli asset della release GitHub
``stt-models-2`` in <cartella dati>/models/parakeet-v3-q8pc-rr/ la prima volta e poi
funziona offline. L'audio viene decodificato con ffmpeg a blocchi a 16 kHz mono s16le,
normalizzato con guadagno globale e trascritto in finestre fisse da 6 s con
sovrapposizione di 1,5 s e cucitura per parole.

L'uscita ha lo stesso formato di macparakeet-cli (millisecondi, wordTimestamps con
confidenza e wordRange per segmento), così il rilevamento statistico del rischio ASR
funziona anche con questo motore.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
MODEL_DIR_NAME = "parakeet-v3-q8pc-rr"
MODEL_LABEL = "Parakeet TDT 0.6B v3 (ONNX)"
QUANTIZATION = "q8pc"
LEGACY_MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
LEGACY_VAD_NAME = "silero"
# stt-models-1: pesi int8 a 8 bit, che sulle CPU x86 senza VNNI (Intel fino a Comet Lake, AMD Zen 2/3)
# saturano in onnxruntime e non riconoscono nulla. Si cancella dopo il download di stt-models-2.
LEGACY_Q8PC_DIR_NAME = "parakeet-v3-q8pc"
SAMPLE_RATE = 16_000

WINDOW_SECONDS = 6.0
OVERLAP_SECONDS = 1.5
DECODE_CHUNK_SECONDS = 60
MAX_SEGMENT_SECONDS = 30.0
SEGMENT_PAUSE_SECONDS = 0.8

MODEL_RELEASE_BASE_URL = "https://github.com/atturk/rt/releases/download/stt-models-2"

# File della release stt-models-2 (reduce_range=True: pesi a 7 bit, vanno anche senza VNNI; quantizzati dal fp32 di istupakov/parakeet-tdt-0.6b-v3-onnx,
# revisione 8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce, con onnx 1.23.2 + onnxruntime 1.31.0).
ENCODER_FILENAME = "encoder-model.q8pc.onnx"
ENCODER_URL = f"{MODEL_RELEASE_BASE_URL}/{ENCODER_FILENAME}"
ENCODER_BYTES = 881_498_240
ENCODER_SHA256 = "8fcd0c371e5e405c1a47895b991070409189c9a841b8adfe3749368f1b4dd691"

DECODER_FILENAME = "decoder_joint-model.q8pc.onnx"
DECODER_URL = f"{MODEL_RELEASE_BASE_URL}/{DECODER_FILENAME}"
DECODER_BYTES = 53_639_765
DECODER_SHA256 = "79fea486faf25489335f9bc17f2da0535fc2d38d47b5490acc42037e08c5a23a"

VOCAB_FILENAME = "vocab.txt"
VOCAB_URL = f"{MODEL_RELEASE_BASE_URL}/{VOCAB_FILENAME}"
VOCAB_BYTES = 93_939
VOCAB_SHA256 = "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d"

CONFIG_FILENAME = "config.json"
CONFIG_URL = f"{MODEL_RELEASE_BASE_URL}/{CONFIG_FILENAME}"
CONFIG_BYTES = 97
CONFIG_SHA256 = "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466"

_SENTENCE_END_RE = re.compile(r"[.!?…][\"'”»)\]]*$")
_WORD_STRIP_CHARS = ".,;:!?"

_lock = threading.Lock()
_loaded: Dict[str, Any] = {}


class OnnxSttUnavailable(RuntimeError):
    """Il motore non può girare qui (pacchetto mancante, modello non scaricabile)."""


def models_dir() -> str:
    from rt.core.paths import data_dir
    return os.environ.get("RT_STT_MODELS_DIR") or os.path.join(data_dir(), "models")


def _model_dir(name: str) -> str:
    return os.path.join(models_dir(), name)


def model_dir() -> str:
    return _model_dir(MODEL_DIR_NAME)


def _model_files() -> List[Tuple[str, str, int, str]]:
    """Elenco (filename, url, bytes, sha256) dei file del modello q8pc."""
    return [
        (ENCODER_FILENAME, ENCODER_URL, ENCODER_BYTES, ENCODER_SHA256),
        (DECODER_FILENAME, DECODER_URL, DECODER_BYTES, DECODER_SHA256),
        (VOCAB_FILENAME, VOCAB_URL, VOCAB_BYTES, VOCAB_SHA256),
        (CONFIG_FILENAME, CONFIG_URL, CONFIG_BYTES, CONFIG_SHA256),
    ]


def available() -> bool:
    """Il pacchetto onnx-asr è installato (il modello si scarica al primo uso)."""
    try:
        import onnx_asr  # noqa: F401
        return True
    except ImportError:
        return False


def model_ready() -> bool:
    return os.path.isdir(model_dir())


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cleanup_legacy_models() -> None:
    """Elimina il vecchio modello int8 e il VAD Silero non più usati, se presenti."""
    legacy_names = [LEGACY_VAD_NAME, LEGACY_Q8PC_DIR_NAME]
    if LEGACY_MODEL_NAME != MODEL_DIR_NAME:
        legacy_names.append(LEGACY_MODEL_NAME)
    for name in legacy_names:
        base = _model_dir(name)
        for path in (base, base + ".partial"):
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)


def _check_cancelled(cancel_token: Optional[Any]) -> None:
    if cancel_token is None:
        return
    if hasattr(cancel_token, "raise_if_cancelled"):
        cancel_token.raise_if_cancelled()
    elif getattr(cancel_token, "cancelled", False):
        raise RuntimeError("Trascrizione annullata")


def _format_eta(seconds: float) -> str:
    if seconds >= 90:
        mins = max(1, round(seconds / 60))
        return "circa 1 minuto" if mins == 1 else f"circa {mins} minuti"
    if seconds >= 10:
        secs = max(10, round(seconds / 10) * 10)
        return f"circa {secs} secondi"
    return "pochi secondi"


def _format_eta_short(seconds: float) -> str:
    if seconds >= 90:
        mins = max(1, round(seconds / 60))
        return f"circa {mins} min"
    if seconds >= 10:
        secs = max(10, round(seconds / 10) * 10)
        return f"circa {secs} s"
    return "pochi secondi"


class _DownloadProgressReporter:
    """Emette avanzamento in MB, percentuale e stima tempo rimanente (al massimo 1/s)."""

    def __init__(
        self,
        on_progress: Optional[Callable[[str], None]],
        total_bytes: int,
        initial_bytes: int,
        on_stats: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self._on_progress = on_progress
        self._on_stats = on_stats
        self._total = total_bytes
        self._initial = initial_bytes
        self._started = time.monotonic()
        self._last_emit = self._started - 1.0
        self._last_pct = -1

    def update(self, downloaded_bytes: int, *, force: bool = False) -> None:
        if (not self._on_progress and not self._on_stats) or self._total <= 0:
            return
        now = time.monotonic()
        pct = min(100, max(0, int(downloaded_bytes * 100 / self._total)))
        if not force:
            if now - self._last_emit < 1.0:
                return
            if pct == self._last_pct and now - self._last_emit < 5.0:
                return
        elif pct == self._last_pct:
            return
        self._last_emit = now
        self._last_pct = pct

        done_mb = round(downloaded_bytes / (1024 * 1024))
        total_mb = max(1, round(self._total / (1024 * 1024)))
        elapsed = now - self._started
        session_bytes = downloaded_bytes - self._initial
        remaining = max(0, self._total - downloaded_bytes)
        eta_seconds: Optional[float] = None
        eta_part = ""
        eta_short: Optional[str] = None
        if elapsed >= 2.0 and session_bytes > 0 and remaining > 0:
            speed = session_bytes / elapsed
            if speed > 0:
                eta_seconds = remaining / speed
                eta_part = f", {_format_eta(eta_seconds)}"
                eta_short = _format_eta_short(eta_seconds)
        if self._on_stats:
            self._on_stats({
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": self._total,
                "percent": pct,
                "eta_seconds": eta_seconds,
                "eta_label": eta_short,
            })
        if self._on_progress:
            self._on_progress(
                f"Scarico il modello di trascrizione: {pct}% ({done_mb} di {total_mb} MB{eta_part})"
            )


def _verify_and_promote(
    part_file: str,
    dest_file: str,
    expected_size: Optional[int],
    expected_sha256: Optional[str],
) -> None:
    actual_size = os.path.getsize(part_file)
    if expected_size is not None and actual_size != expected_size:
        if actual_size > expected_size:
            os.unlink(part_file)
        raise OSError(f"Dimensione inattesa per {os.path.basename(dest_file)}: {actual_size} != {expected_size}")
    if expected_sha256:
        actual_sha = _sha256_file(part_file)
        if actual_sha != expected_sha256.lower():
            os.unlink(part_file)
            raise OSError(f"Verifica SHA256 non riuscita per {os.path.basename(dest_file)}.")
    os.replace(part_file, dest_file)


def _download_file_resumable(
    url: str,
    dest_file: str,
    expected_size: Optional[int],
    expected_sha256: Optional[str] = None,
    *,
    on_chunk: Optional[Callable[[int], None]] = None,
    cancel_token: Optional[Any] = None,
) -> None:
    import requests

    if os.environ.get("RT_ONNX_OFFLINE") == "1" and not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise OSError("Download del modello ONNX disattivato nei test.")

    part_file = dest_file + ".part"
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    resume_from = os.path.getsize(part_file) if os.path.isfile(part_file) else 0
    if expected_size is not None and resume_from > expected_size:
        os.unlink(part_file)
        resume_from = 0
    if expected_size is not None and resume_from == expected_size and expected_size > 0:
        _verify_and_promote(part_file, dest_file, expected_size, expected_sha256)
        return

    headers: Dict[str, str] = {}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    with requests.get(url, headers=headers, stream=True, timeout=(15, 60), allow_redirects=True) as resp:
        if resp.status_code == 416 and resume_from > 0:
            if expected_sha256 and _sha256_file(part_file) == expected_sha256.lower():
                os.replace(part_file, dest_file)
                return
            os.unlink(part_file)
            if on_chunk:
                on_chunk(-resume_from)
            resume_from = 0
            with requests.get(url, stream=True, timeout=(15, 60), allow_redirects=True) as resp2:
                resp2.raise_for_status()
                _stream_response(
                    resp2, part_file, dest_file, expected_size, expected_sha256, 0, on_chunk, cancel_token,
                )
            return
        resp.raise_for_status()
        if resp.status_code == 206:
            content_range = resp.headers.get("Content-Range", "")
            if content_range and not content_range.startswith(f"bytes {resume_from}-"):
                if on_chunk:
                    on_chunk(-resume_from)
                resume_from = 0
        elif resume_from > 0:
            if on_chunk:
                on_chunk(-resume_from)
            resume_from = 0
        _stream_response(
            resp, part_file, dest_file, expected_size, expected_sha256, resume_from, on_chunk, cancel_token,
        )


def _stream_response(
    resp: Any,
    part_file: str,
    dest_file: str,
    expected_size: Optional[int],
    expected_sha256: Optional[str],
    resume_from: int,
    on_chunk: Optional[Callable[[int], None]],
    cancel_token: Optional[Any],
) -> None:
    mode = "ab" if resume_from > 0 else "wb"
    with open(part_file, mode) as stream:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            _check_cancelled(cancel_token)
            if not chunk:
                continue
            stream.write(chunk)
            if on_chunk:
                on_chunk(len(chunk))
    _verify_and_promote(part_file, dest_file, expected_size, expected_sha256)


def _download_resumable(
    name: str = MODEL_DIR_NAME,
    quantization: Optional[str] = QUANTIZATION,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    on_stats: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[Any] = None,
) -> str:
    """Scarica i file del modello q8pc con ripresa Range, verifica SHA256 e sostituzione atomica."""
    final = _model_dir(name)
    if os.path.isdir(final):
        _cleanup_legacy_models()
        return final
    partial = final + ".partial"
    os.makedirs(partial, exist_ok=True)
    try:
        files = _model_files()
        if not files:
            raise OSError(f"Nessun file configurato per il modello {name}")

        total_bytes = sum(size or 0 for _, _, size, _ in files)
        downloaded_bytes = 0
        pending: List[Tuple[str, str, Optional[int], Optional[str], str]] = []
        for rel_path, url, expected_size, expected_sha in files:
            dest_file = os.path.join(partial, rel_path)
            part_file = dest_file + ".part"
            if os.path.isfile(dest_file):
                size_ok = expected_size is None or os.path.getsize(dest_file) == expected_size
                sha_ok = not expected_sha or _sha256_file(dest_file) == expected_sha.lower()
                if size_ok and sha_ok:
                    downloaded_bytes += expected_size or os.path.getsize(dest_file)
                    continue
                os.unlink(dest_file)
            if os.path.isfile(part_file):
                part_size = os.path.getsize(part_file)
                if expected_size is not None and part_size == expected_size and expected_size > 0:
                    _verify_and_promote(part_file, dest_file, expected_size, expected_sha)
                    downloaded_bytes += expected_size
                    continue
                if expected_size is not None and part_size > expected_size:
                    os.unlink(part_file)
                else:
                    downloaded_bytes += part_size
            pending.append((rel_path, url, expected_size, expected_sha, dest_file))

        reporter = _DownloadProgressReporter(on_progress, total_bytes, downloaded_bytes, on_stats=on_stats)
        if pending and downloaded_bytes > 0:
            reporter.update(downloaded_bytes, force=True)

        def on_chunk(delta: int) -> None:
            nonlocal downloaded_bytes
            downloaded_bytes = max(0, downloaded_bytes + delta)
            reporter.update(downloaded_bytes)

        for _rel_path, url, expected_size, expected_sha, dest_file in pending:
            _download_file_resumable(
                url,
                dest_file,
                expected_size,
                expected_sha,
                on_chunk=on_chunk,
                cancel_token=cancel_token,
            )
        reporter.update(downloaded_bytes, force=True)
    except RuntimeError as exc:
        if "annullat" in str(exc).lower():
            raise
        raise OnnxSttUnavailable(
            f"Download del modello {name} non riuscito: controlla la connessione e riprova ({exc})."
        ) from None
    except Exception as exc:
        raise OnnxSttUnavailable(
            f"Download del modello {name} non riuscito: controlla la connessione e riprova ({exc})."
        ) from None
    os.replace(partial, final)
    _cleanup_legacy_models()
    return final


def clear_loaded() -> None:
    """Svuota il modello caricato in memoria (es. dopo l'eliminazione da Impostazioni)."""
    with _lock:
        _loaded.clear()


def _models(on_progress: Optional[Callable[[str], None]] = None, cancel_token: Optional[Any] = None):
    """ASR con timestamp, caricato una volta per processo con le opzioni predefinite."""
    with _lock:
        if "asr" in _loaded:
            return _loaded["asr"]
        try:
            import onnx_asr
        except ImportError:
            raise OnnxSttUnavailable("Motore Parakeet ONNX non installato (pacchetto onnx-asr).") from None
        if not model_ready() and on_progress:
            on_progress("Scarico il modello di trascrizione (circa 900 MB, solo la prima volta)...")
        from rt.core import components
        model_path = components.ensure_transcription_model(
            on_progress=on_progress,
            cancel_token=cancel_token,
        )
        model = onnx_asr.load_model(MODEL_NAME, model_path, quantization=QUANTIZATION)
        _loaded["asr"] = model.with_timestamps()
        return _loaded["asr"]


def ensure_model(on_progress: Optional[Callable[[str], None]] = None) -> None:
    """Scarica (se serve) e carica il modello; OnnxSttUnavailable se non si può."""
    _models(on_progress)


def _iter_pcm_chunks(
    audio_path: str,
    chunk_samples: int = DECODE_CHUNK_SECONDS * SAMPLE_RATE,
    cancel_token: Optional[Any] = None,
) -> Iterator[Any]:
    """Decodifica l'audio con ffmpeg in streaming a blocchi float32 a 16 kHz mono."""
    import numpy as np

    from rt.core.media_tools import require_ffmpeg

    cmd = [
        require_ffmpeg(),
        "-nostdin",
        "-v",
        "error",
        "-i",
        os.path.abspath(audio_path),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Impossibile leggere l'audio '{os.path.basename(audio_path)}': {exc}") from None

    chunk_bytes = max(2, int(chunk_samples) * 2)
    carry = b""
    assert proc.stdout is not None
    try:
        while True:
            _check_cancelled(cancel_token)
            raw = proc.stdout.read(chunk_bytes)
            if not raw:
                break
            data = carry + raw
            even_len = (len(data) // 2) * 2
            carry = data[even_len:]
            if even_len:
                samples = np.frombuffer(data[:even_len], dtype="<i2")
                yield samples.astype(np.float32) / 32768.0
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        returncode = proc.wait(timeout=60)
        if returncode != 0:
            err = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Impossibile leggere l'audio '{os.path.basename(audio_path)}': "
                f"{err or f'ffmpeg terminato con codice {returncode}'}"
            )
    except BaseException:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


def _decode(audio_path: str):
    """PCM float32 a 16 kHz mono, letto da ffmpeg."""
    import numpy as np

    chunks = list(_iter_pcm_chunks(audio_path))
    if not chunks:
        return np.empty(0, dtype=np.float32)
    if len(chunks) == 1:
        return chunks[0]
    return np.concatenate(chunks)


def _compute_gain(rms: float, peak: float) -> float:
    """Guadagno globale min(0.1 / rms, 4 / picco)."""
    rms_safe = rms if rms > 0.0 else 1e-6
    peak_safe = peak if peak > 0.0 else 1.0
    return min(0.1 / rms_safe, 4.0 / peak_safe)


def _measure_audio(
    audio_path: str,
    *,
    chunk_samples: int = DECODE_CHUNK_SECONDS * SAMPLE_RATE,
    cancel_token: Optional[Any] = None,
) -> Tuple[int, float, float]:
    """Primo passaggio in streaming: calcola campioni totali, RMS e picco senza tenere la waveform."""
    import numpy as np

    total_samples = 0
    sum_sq = 0.0
    peak = 0.0
    for chunk in _iter_pcm_chunks(audio_path, chunk_samples=chunk_samples, cancel_token=cancel_token):
        if len(chunk) == 0:
            continue
        chunk_f64 = chunk.astype(np.float64)
        sum_sq += float(np.dot(chunk_f64, chunk_f64))
        chunk_peak = float(np.max(np.abs(chunk)))
        if chunk_peak > peak:
            peak = chunk_peak
        total_samples += len(chunk)
    rms = math.sqrt(sum_sq / total_samples) if total_samples > 0 else 0.0
    return total_samples, rms, peak


def _iter_audio_windows(
    audio_path: str,
    win_samples: int,
    step_samples: int,
    gain: float,
    *,
    chunk_samples: int = DECODE_CHUNK_SECONDS * SAMPLE_RATE,
    min_samples: int = SAMPLE_RATE // 2,
    cancel_token: Optional[Any] = None,
) -> Iterator[Tuple[int, Any, bool]]:
    """Secondo passaggio in streaming: produce finestre normalizzate da 6 s con passo 4,5 s."""
    import numpy as np

    buf = np.empty(0, dtype=np.float32)
    start_sample = 0
    eof = False
    chunk_iter = iter(_iter_pcm_chunks(audio_path, chunk_samples=chunk_samples, cancel_token=cancel_token))

    while True:
        _check_cancelled(cancel_token)
        while not eof and len(buf) <= win_samples:
            try:
                nxt = next(chunk_iter)
                if len(nxt):
                    buf = np.concatenate([buf, nxt]) if len(buf) else nxt
            except StopIteration:
                eof = True
        if len(buf) < min_samples:
            break
        last = eof and len(buf) <= win_samples
        raw_win = buf[:win_samples]
        norm_win = np.clip(raw_win * gain, -1.0, 1.0).astype(np.float32)
        yield start_sample, norm_win, last
        if last:
            break
        buf = buf[step_samples:]
        start_sample += step_samples


def _extract_window_words(
    tokens: Sequence[str],
    timestamps: Sequence[float],
    logprobs: Optional[Sequence[float]],
    offset: float,
    window_end: float,
) -> List[Dict[str, Any]]:
    """Parole dai token SentencePiece: un token che inizia con spazio apre una parola."""
    words: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for i, token in enumerate(tokens or []):
        start = offset + (float(timestamps[i]) if timestamps and i < len(timestamps) else 0.0)
        prob = math.exp(logprobs[i]) if logprobs and i < len(logprobs) else None
        if current is None or token.startswith(" "):
            if current is not None:
                words.append(current)
            current = {
                "word": token.strip(),
                "start": start,
                "last_token_start": start,
                "probs": [],
                "window_end": window_end,
            }
        else:
            current["word"] += token
            current["last_token_start"] = start
        if prob is not None:
            current["probs"].append(prob)
    if current is not None:
        words.append(current)

    out: List[Dict[str, Any]] = []
    for word in words:
        if not word["word"]:
            continue
        probs = word.pop("probs")
        word["confidence"] = round(sum(probs) / len(probs), 4) if probs else None
        out.append(word)
    return out


def _clean_word_key(word: str) -> str:
    return word.lower().strip(_WORD_STRIP_CHARS)


def _stitch_window_words(
    kept: List[Dict[str, Any]],
    win_words: List[Dict[str, Any]],
    prev_cut: float,
    cut: float,
) -> None:
    """Cucitura per parole tra finestre sovrapposte (come onnx_finestre_riferimento.py)."""
    new = [w for w in win_words if prev_cut - 0.6 <= w["start"] < cut]
    while new and kept:
        tail = [_clean_word_key(w["word"]) for w in kept[-3:]]
        w0 = new[0]
        if w0["start"] < prev_cut or (
            _clean_word_key(w0["word"]) in tail and abs(w0["start"] - kept[-1]["start"]) < 1.5
        ):
            new.pop(0)
        else:
            break
    kept.extend(new)


def _build_segments(
    words: List[Dict[str, Any]],
    duration: float,
    *,
    max_segment_s: float = MAX_SEGMENT_SECONDS,
    pause_s: float = SEGMENT_PAUSE_SECONDS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Costruisce wordTimestamps e transcriptSegments (chiusura su ., !, ?, pausa > 0.8s o ~30s)."""
    if not words:
        return [], []

    word_timestamps: List[Dict[str, Any]] = []
    word_ends: List[float] = []
    for i, w in enumerate(words):
        last_tok = w.get("last_token_start", w["start"])
        if i + 1 < len(words):
            next_start = words[i + 1]["start"]
            gap = next_start - last_tok
            if gap <= pause_s:
                w_end = max(w["start"], next_start)
            else:
                w_end = min(next_start, max(w["start"] + 0.1, last_tok + 0.4))
        else:
            w_end = min(duration, max(w["start"] + 0.1, last_tok + 0.4))
            if w_end < w["start"]:
                w_end = w["start"]
        word_ends.append(w_end)
        word_timestamps.append({
            "word": w["word"],
            "startMs": round(w["start"] * 1000, 1),
            "endMs": round(w_end * 1000, 1),
            "confidence": w["confidence"],
        })

    segments: List[Dict[str, Any]] = []
    seg_start_idx = 0
    for i, w in enumerate(words):
        seg_start = words[seg_start_idx]["start"]
        is_last = i == len(words) - 1
        close = is_last or bool(_SENTENCE_END_RE.search(w["word"]))
        if not close and not is_last:
            next_w = words[i + 1]
            pause = next_w["start"] - w.get("last_token_start", w["start"])
            if pause > pause_s:
                close = True
            elif (word_ends[i + 1] - seg_start) > max_segment_s or (word_ends[i] - seg_start) >= max_segment_s:
                close = True
        if close:
            seg_words = words[seg_start_idx : i + 1]
            seg_end = max(seg_start + 0.1 if seg_start == word_ends[i] else word_ends[i], seg_start)
            confs = [sw["confidence"] for sw in seg_words if sw["confidence"] is not None]
            segments.append({
                "startMs": round(seg_start * 1000, 1),
                "endMs": round(seg_end * 1000, 1),
                "text": " ".join(sw["word"] for sw in seg_words),
                "confidence": round(sum(confs) / len(confs), 4) if confs else None,
                "wordRange": {"startIndex": seg_start_idx, "endIndexExclusive": i + 1},
            })
            seg_start_idx = i + 1

    return segments, word_timestamps


def transcribe_onnx(
    audio_path: str,
    on_percent: Optional[Callable[[int], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> Dict[str, Any]:
    """Trascrive un file audio e restituisce il formato interno RT (come macparakeet-cli)."""
    _check_cancelled(cancel_token)
    asr = _models(on_progress) if cancel_token is None else _models(on_progress, cancel_token=cancel_token)
    total_samples, rms, peak = _measure_audio(audio_path, cancel_token=cancel_token)
    duration = total_samples / SAMPLE_RATE
    if duration <= 0:
        raise RuntimeError(f"L'audio '{os.path.basename(audio_path)}' è vuoto.")

    gain = _compute_gain(rms, peak)
    win_samples = int(WINDOW_SECONDS * SAMPLE_RATE)
    ovl_samples = int(OVERLAP_SECONDS * SAMPLE_RATE)
    step_samples = win_samples - ovl_samples

    kept: List[Dict[str, Any]] = []
    prev_cut = 0.0
    last_percent = -1

    for start_sample, norm_win, is_last in _iter_audio_windows(
        audio_path, win_samples, step_samples, gain, cancel_token=cancel_token,
    ):
        _check_cancelled(cancel_token)
        res = asr.recognize(norm_win, sample_rate=SAMPLE_RATE)
        off = start_sample / SAMPLE_RATE
        win_end = off + len(norm_win) / SAMPLE_RATE
        cut = float("inf") if is_last else off + (WINDOW_SECONDS - OVERLAP_SECONDS) + OVERLAP_SECONDS / 2

        win_words = _extract_window_words(
            getattr(res, "tokens", None) or [],
            getattr(res, "timestamps", None) or [],
            getattr(res, "logprobs", None),
            off,
            win_end,
        )
        _stitch_window_words(kept, win_words, prev_cut, cut)
        prev_cut = cut

        processed_s = min(duration, win_end)
        percent = min(99, int(processed_s / duration * 100))
        if on_percent and percent != last_percent:
            on_percent(percent)
            last_percent = percent

    if not kept:
        raise RuntimeError(f"Nessuna voce riconosciuta in '{os.path.basename(audio_path)}'.")

    segments, words = _build_segments(kept, duration)
    if on_percent:
        on_percent(100)
    text = " ".join(s["text"] for s in segments)
    return {
        "rawTranscript": text,
        "text": text,
        "transcriptSegments": segments,
        "wordTimestamps": words,
        "model": MODEL_LABEL,
    }
