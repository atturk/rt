"""
rt.core.onnx_stt
Motore di trascrizione locale "parakeet": Parakeet TDT 0.6B v3 (multilingue, italiano
compreso) in formato ONNX tramite onnx-asr. Gira su Windows, Linux e macOS senza GPU; su Mac
resta consigliato macparakeet, più veloce sul Neural Engine.

Il modello (circa 670 MB, quantizzato int8) e il VAD Silero si scaricano da Hugging Face la
prima volta in <cartella dati>/models/ e poi funzionano offline. L'audio viene decodificato
con ffmpeg a 16 kHz mono, diviso in frasi dal VAD e trascritto a blocchi.

L'uscita ha lo stesso formato di macparakeet-cli (millisecondi, wordTimestamps con
confidenza e wordRange per segmento), così il rilevamento statistico del rischio ASR
funziona anche con questo motore.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
MODEL_LABEL = "Parakeet TDT 0.6B v3 (ONNX)"
QUANTIZATION = "int8"
VAD_NAME = "silero"
SAMPLE_RATE = 16_000

_lock = threading.Lock()
_loaded: Dict[str, Any] = {}


class OnnxSttUnavailable(RuntimeError):
    """Il motore non può girare qui (pacchetto mancante, modello non scaricabile)."""


def models_dir() -> str:
    from rt.core.paths import data_dir
    return os.environ.get("RT_STT_MODELS_DIR") or os.path.join(data_dir(), "models")


def _model_dir(name: str) -> str:
    return os.path.join(models_dir(), name)


def available() -> bool:
    """Il pacchetto onnx-asr è installato (il modello si scarica al primo uso)."""
    try:
        import onnx_asr  # noqa: F401
        return True
    except ImportError:
        return False


def model_ready() -> bool:
    return os.path.isdir(_model_dir(MODEL_NAME)) and os.path.isdir(_model_dir(VAD_NAME))


def _format_eta(seconds: float) -> str:
    if seconds >= 90:
        mins = max(1, round(seconds / 60))
        return "circa 1 minuto" if mins == 1 else f"circa {mins} minuti"
    if seconds >= 10:
        secs = max(10, round(seconds / 10) * 10)
        return f"circa {secs} secondi"
    return "pochi secondi"


class _DownloadProgressReporter:
    """Emette avanzamento in MB, percentuale e stima tempo rimanente (al massimo 1/s)."""

    def __init__(self, on_progress: Optional[Callable[[str], None]], total_bytes: int, initial_bytes: int):
        self._on_progress = on_progress
        self._total = total_bytes
        self._initial = initial_bytes
        self._started = time.monotonic()
        self._last_emit = self._started - 1.0
        self._last_pct = -1

    def update(self, downloaded_bytes: int, *, force: bool = False) -> None:
        if not self._on_progress or self._total <= 0:
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
        eta_part = ""
        if elapsed >= 2.0 and session_bytes > 0 and remaining > 0:
            speed = session_bytes / elapsed
            if speed > 0:
                eta_part = f", {_format_eta(remaining / speed)}"
        self._on_progress(
            f"Scarico il modello di trascrizione: {pct}% ({done_mb} di {total_mb} MB{eta_part})"
        )


def _model_patterns(name: str, quantization: Optional[str], *, vad: bool = False) -> Tuple[str, List[str]]:
    from onnx_asr.loader import create_asr_resolver, create_vad_resolver

    resolver = (
        create_vad_resolver(name, offline=True)
        if vad
        else create_asr_resolver(name, offline=True)
    )
    if not resolver.repo_id:
        raise OnnxSttUnavailable(f"Repository non trovato per il modello {name}.")
    files = list(resolver.model_type._get_model_files(quantization).values())
    files = [
        *files,
        *(f.removeprefix("**/") for f in files if f.startswith("**/")),
    ]
    patterns = [
        "config.json",
        "config.yaml",
        *files,
        *(str(Path(f).with_suffix(".onnx?data")) for f in files if Path(f).suffix == ".onnx"),
    ]
    return resolver.repo_id, patterns


def _list_repo_files(repo_id: str, patterns: List[str]) -> List[Tuple[str, Optional[int]]]:
    from huggingface_hub import HfApi
    from huggingface_hub.hf_api import RepoFile
    from huggingface_hub.utils import filter_repo_objects

    api = HfApi()
    entries = {
        f.path: f.size
        for f in api.list_repo_tree(repo_id, recursive=True)
        if isinstance(f, RepoFile)
    }
    matched = list(filter_repo_objects(items=entries.keys(), allow_patterns=patterns))
    return [(path, entries[path]) for path in matched]


def _download_file_resumable(
    url: str,
    dest_file: str,
    expected_size: Optional[int],
    *,
    on_chunk: Optional[Callable[[int], None]] = None,
    cancel_token: Optional[Any] = None,
) -> None:
    import requests

    part_file = dest_file + ".part"
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    resume_from = os.path.getsize(part_file) if os.path.isfile(part_file) else 0
    if expected_size is not None and resume_from > expected_size:
        os.unlink(part_file)
        resume_from = 0
    if expected_size is not None and resume_from == expected_size and expected_size > 0:
        os.replace(part_file, dest_file)
        return

    headers: Dict[str, str] = {}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    with requests.get(url, headers=headers, stream=True, timeout=(15, 60), allow_redirects=True) as resp:
        if resp.status_code == 416 and resume_from > 0:
            os.unlink(part_file)
            if on_chunk:
                on_chunk(-resume_from)
            resume_from = 0
            resp2 = requests.get(url, stream=True, timeout=(15, 60), allow_redirects=True)
            resp2.raise_for_status()
            return _stream_response(resp2, part_file, dest_file, expected_size, 0, on_chunk, cancel_token)
        resp.raise_for_status()
        if resp.status_code == 206:
            content_range = resp.headers.get("Content-Range", "")
            if content_range and not content_range.startswith(f"bytes {resume_from}-"):
                # Server returned an unexpected range; restart safely from 0.
                if on_chunk:
                    on_chunk(-resume_from)
                resume_from = 0
        elif resume_from > 0:
            # Server ignored Range and sent 200 OK from byte 0.
            if on_chunk:
                on_chunk(-resume_from)
            resume_from = 0
        _stream_response(resp, part_file, dest_file, expected_size, resume_from, on_chunk, cancel_token)


def _stream_response(
    resp: Any,
    part_file: str,
    dest_file: str,
    expected_size: Optional[int],
    resume_from: int,
    on_chunk: Optional[Callable[[int], None]],
    cancel_token: Optional[Any],
) -> None:
    mode = "ab" if resume_from > 0 else "wb"
    with open(part_file, mode) as stream:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                raise RuntimeError("Trascrizione annullata")
            if not chunk:
                continue
            stream.write(chunk)
            if on_chunk:
                on_chunk(len(chunk))
    actual_size = os.path.getsize(part_file)
    if expected_size is not None and actual_size != expected_size:
        if actual_size > expected_size:
            os.unlink(part_file)
        raise OSError(f"Dimensione inattesa per {os.path.basename(dest_file)}: {actual_size} != {expected_size}")
    os.replace(part_file, dest_file)


def _download_resumable(
    name: str,
    quantization: Optional[str],
    *,
    vad: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> str:
    """Scarica il modello da Hugging Face con file .part riprendibili e verifica della dimensione."""
    final = _model_dir(name)
    if os.path.isdir(final):
        return final
    partial = final + ".partial"
    os.makedirs(partial, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_url

        repo_id, patterns = _model_patterns(name, quantization, vad=vad)
        repo_files = _list_repo_files(repo_id, patterns)
        if not repo_files:
            raise OSError(f"Nessun file trovato in {repo_id}")

        total_bytes = sum(size or 0 for _, size in repo_files)
        downloaded_bytes = 0
        pending: List[Tuple[str, Optional[int], str]] = []
        for rel_path, expected_size in repo_files:
            dest_file = os.path.join(partial, rel_path)
            part_file = dest_file + ".part"
            if os.path.isfile(dest_file) and (expected_size is None or os.path.getsize(dest_file) == expected_size):
                downloaded_bytes += expected_size or os.path.getsize(dest_file)
                continue
            if os.path.isfile(dest_file):
                os.unlink(dest_file)
            if os.path.isfile(part_file):
                part_size = os.path.getsize(part_file)
                if expected_size is not None and part_size == expected_size and expected_size > 0:
                    os.replace(part_file, dest_file)
                    downloaded_bytes += expected_size
                    continue
                if expected_size is not None and part_size > expected_size:
                    os.unlink(part_file)
                else:
                    downloaded_bytes += part_size
            pending.append((rel_path, expected_size, dest_file))

        reporter = _DownloadProgressReporter(on_progress, total_bytes, downloaded_bytes)
        if pending and downloaded_bytes > 0:
            reporter.update(downloaded_bytes, force=True)

        def on_chunk(delta: int) -> None:
            nonlocal downloaded_bytes
            downloaded_bytes = max(0, downloaded_bytes + delta)
            reporter.update(downloaded_bytes)

        for rel_path, expected_size, dest_file in pending:
            url = hf_hub_url(repo_id, filename=rel_path)
            _download_file_resumable(
                url,
                dest_file,
                expected_size,
                on_chunk=on_chunk,
                cancel_token=cancel_token,
            )
        reporter.update(downloaded_bytes, force=True)
    except RuntimeError as exc:
        if "annullata" in str(exc).lower():
            raise
        raise OnnxSttUnavailable(
            f"Download del modello {name} non riuscito: controlla la connessione e riprova ({exc})."
        ) from None
    except Exception as exc:
        raise OnnxSttUnavailable(
            f"Download del modello {name} non riuscito: controlla la connessione e riprova ({exc})."
        ) from None
    os.replace(partial, final)
    return final


def _download(load, name: str, quantization: Optional[str]) -> str:
    """Scarica in una cartella temporanea e la rinomina solo a download finito: onnx-asr
    considera completa (e usa offline) qualunque cartella esistente."""
    final = _model_dir(name)
    if os.path.isdir(final):
        return final
    partial = final + ".partial"
    shutil.rmtree(partial, ignore_errors=True)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    try:
        if quantization:
            load(name, partial, quantization=quantization)
        else:
            load(name, partial)
    except Exception as exc:
        shutil.rmtree(partial, ignore_errors=True)
        raise OnnxSttUnavailable(
            f"Download del modello {name} non riuscito: controlla la connessione e riprova ({exc})."
        ) from None
    os.replace(partial, final)
    return final


def _models(on_progress: Optional[Callable[[str], None]] = None, cancel_token: Optional[Any] = None):
    """ASR con VAD e timestamp, caricato una volta per processo."""
    with _lock:
        if "asr" in _loaded:
            return _loaded["asr"]
        try:
            import onnx_asr
        except ImportError:
            raise OnnxSttUnavailable("Motore Parakeet ONNX non installato (pacchetto onnx-asr).") from None
        if not model_ready() and on_progress:
            on_progress("Scarico il modello di trascrizione (circa 700 MB, solo la prima volta)...")
        model_path = _download_resumable(
            MODEL_NAME, QUANTIZATION, on_progress=on_progress, cancel_token=cancel_token
        )
        vad_path = _download_resumable(VAD_NAME, None, vad=True, cancel_token=cancel_token)
        model = onnx_asr.load_model(MODEL_NAME, model_path, quantization=QUANTIZATION)
        vad = onnx_asr.load_vad(VAD_NAME, vad_path)
        _loaded["asr"] = model.with_vad(vad, batch_size=4, max_speech_duration_s=25).with_timestamps()
        return _loaded["asr"]


def ensure_model(on_progress: Optional[Callable[[str], None]] = None) -> None:
    """Scarica (se serve) e carica il modello; OnnxSttUnavailable se non si può."""
    _models(on_progress)


def _decode(audio_path: str):
    """PCM float32 a 16 kHz mono, letto da ffmpeg."""
    import numpy as np

    from rt.core.media_tools import require_ffmpeg
    try:
        result = subprocess.run(
            [require_ffmpeg(), "-nostdin", "-v", "error", "-i", os.path.abspath(audio_path),
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
            capture_output=True, check=True, timeout=3600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Impossibile leggere l'audio '{os.path.basename(audio_path)}': {exc}") from None
    samples = np.frombuffer(result.stdout[: len(result.stdout) // 2 * 2], dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def _words(tokens: List[str], timestamps: List[float], logprobs: Optional[List[float]],
           offset: float, end: float) -> List[Dict[str, Any]]:
    """Parole dai token SentencePiece: un token che inizia con uno spazio apre una parola.
    La confidenza della parola è la probabilità media dei suoi token."""
    words: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for i, token in enumerate(tokens):
        start = offset + (timestamps[i] if i < len(timestamps) else 0.0)
        prob = math.exp(logprobs[i]) if logprobs and i < len(logprobs) else None
        if current is None or token.startswith(" "):
            if current is not None:
                words.append(current)
            current = {"word": token.strip(), "start": start, "probs": []}
        else:
            current["word"] += token
        if prob is not None:
            current["probs"].append(prob)
    if current is not None:
        words.append(current)
    out = []
    for i, word in enumerate(words):
        if not word["word"]:
            continue
        stop = words[i + 1]["start"] if i + 1 < len(words) else end
        probs = word.pop("probs")
        out.append({"word": word["word"], "startMs": round(word["start"] * 1000, 1),
                    "endMs": round(max(stop, word["start"]) * 1000, 1),
                    "confidence": round(sum(probs) / len(probs), 4) if probs else None})
    return out


def transcribe_onnx(audio_path: str, on_percent: Optional[Callable[[int], None]] = None,
                    on_progress: Optional[Callable[[str], None]] = None,
                    cancel_token: Optional[Any] = None) -> Dict[str, Any]:
    """Trascrive un file audio e restituisce il formato interno RT (come macparakeet-cli)."""
    asr = _models(on_progress) if cancel_token is None else _models(on_progress, cancel_token=cancel_token)
    waveform = _decode(audio_path)
    duration = len(waveform) / SAMPLE_RATE
    if duration <= 0:
        raise RuntimeError(f"L'audio '{os.path.basename(audio_path)}' è vuoto.")
    segments: List[Dict[str, Any]] = []
    words: List[Dict[str, Any]] = []
    last_percent = -1
    for result in asr.recognize(waveform, sample_rate=SAMPLE_RATE):
        text = (result.text or "").strip()
        if text:
            seg_words = _words(result.tokens or [], result.timestamps or [], result.logprobs,
                               float(result.start), float(result.end))
            confidences = [w["confidence"] for w in seg_words if w["confidence"] is not None]
            segment = {"startMs": round(float(result.start) * 1000, 1), "endMs": round(float(result.end) * 1000, 1),
                       "text": text, "confidence": round(sum(confidences) / len(confidences), 4) if confidences else None}
            if seg_words:
                segment["wordRange"] = {"startIndex": len(words), "endIndexExclusive": len(words) + len(seg_words)}
                words.extend(seg_words)
            segments.append(segment)
        percent = min(99, int(float(result.end) / duration * 100))
        if on_percent and percent != last_percent:
            on_percent(percent)
            last_percent = percent
    if not segments:
        raise RuntimeError(f"Nessuna voce riconosciuta in '{os.path.basename(audio_path)}'.")
    if on_percent:
        on_percent(100)
    text = " ".join(s["text"] for s in segments)
    return {"rawTranscript": text, "text": text, "transcriptSegments": segments, "wordTimestamps": words,
            "model": MODEL_LABEL}
