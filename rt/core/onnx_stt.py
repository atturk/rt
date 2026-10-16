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
from typing import Any, Callable, Dict, List, Optional

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


def _models(on_progress: Optional[Callable[[str], None]] = None):
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
        model_path = _download(onnx_asr.load_model, MODEL_NAME, QUANTIZATION)
        vad_path = _download(onnx_asr.load_vad, VAD_NAME, None)
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
                    on_progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Trascrive un file audio e restituisce il formato interno RT (come macparakeet-cli)."""
    asr = _models(on_progress)
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
