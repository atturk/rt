"""
rt.services.audio_service
Audio della lezione per il browser (RT4-F2): una copia riproducibile quando il file non lo è
(AAC ADTS salvato come .m4a, che Safari e Chrome rifiutano) e la forma d'onda per il player.

Entrambe finiscono in <cartella dati>/cache/ con un nome che dipende da percorso, dimensione
e data del file, quindi si rigenerano da sole se l'audio cambia. Servono ffmpeg; senza, l'audio
resta quello originale e la forma d'onda è vuota.
"""
import array
import hashlib
import json
import os
import subprocess
import sys
import threading
from typing import Dict, List, Optional

WAVEFORM_BARS = 300
_computing: Dict[str, threading.Thread] = {}
_lock = threading.Lock()


def _cache_dir(kind: str) -> str:
    from rt.storage import fs
    path = os.path.join(fs.data_dir(), "cache", kind)
    os.makedirs(path, exist_ok=True)
    return path


def _key(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.realpath(path)}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _is_mp4(path: str) -> bool:
    with open(path, "rb") as handle:
        return handle.read(8)[4:8] == b"ftyp"


def playable_audio(path: str) -> str:
    """Il file da inviare al browser: l'originale, o un remux MP4 per un .m4a in AAC ADTS."""
    if os.path.splitext(path)[1].lower() != ".m4a" or _is_mp4(path):
        return path
    target = os.path.join(_cache_dir("audio"), _key(path) + ".m4a")
    if os.path.isfile(target):
        return target
    temporary = target + ".tmp.m4a"
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path, "-c:a", "copy",
                        "-movflags", "+faststart", temporary], check=True, capture_output=True, timeout=300)
        os.replace(temporary, target)
        return target
    except (OSError, subprocess.SubprocessError):
        return path
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def levels_from_samples(samples: "array.array", bars: int = WAVEFORM_BARS) -> List[int]:
    """Livelli 3-72 (RMS per barra, normalizzati tra il 10° e il 90° percentile)."""
    n = len(samples)
    if n == 0:
        return []
    bars = min(bars, n)
    levels = []
    for b in range(bars):
        chunk = samples[b * n // bars:(b + 1) * n // bars]
        levels.append((sum(v * v for v in chunk) / max(1, len(chunk))) ** 0.5)
    ordered = sorted(levels)
    quiet = _percentile(ordered, 0.10)
    loud = max(_percentile(ordered, 0.90), quiet + 1.0)
    return [int(3 + 69 * min(1.0, max(0.0, (lv - quiet) / (loud - quiet)))) for lv in levels]


def compute_waveform(path: str) -> List[int]:
    try:
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", "200",
                                 "-f", "s16le", "pipe:1"], capture_output=True, check=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return []
    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return levels_from_samples(samples)


def waveform(path: str) -> Optional[List[int]]:
    """Livelli della forma d'onda, o None se il calcolo è appena partito in background."""
    target = os.path.join(_cache_dir("waveform"), _key(path) + ".json")
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as f:
            return json.load(f)

    def _run() -> None:
        peaks = compute_waveform(path)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(peaks, f)
        os.replace(tmp, target)
        with _lock:
            _computing.pop(target, None)

    with _lock:
        if target not in _computing:
            thread = threading.Thread(target=_run, name="rt-waveform", daemon=True)
            _computing[target] = thread
            thread.start()
    return None
