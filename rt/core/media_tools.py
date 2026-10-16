"""
rt.core.media_tools
Dove trovare ffmpeg: nel PATH (Homebrew, apt, installazione a mano) oppure, se manca, il
binario che il pacchetto imageio-ffmpeg porta con sé per macOS, Windows e Linux (usato
dall'installer, così l'utente non deve installare nulla). ffprobe non c'è sempre: la durata
si legge anche dall'intestazione che stampa ffmpeg.
"""
import re
import shutil
import subprocess
from typing import Optional


def ffmpeg_path() -> Optional[str]:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if not path:
        raise FileNotFoundError("ffmpeg non trovato: installalo (o reinstalla RT) e riprova.")
    return path


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def audio_duration(path: str, timeout: int = 60) -> float:
    """Durata in secondi; ValueError se il file non ha una durata valida."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                                capture_output=True, text=True, check=True, timeout=timeout)
        duration = float(result.stdout.strip())
    else:
        result = subprocess.run([require_ffmpeg(), "-hide_banner", "-nostdin", "-i", path],
                                capture_output=True, text=True, timeout=timeout)
        match = _DURATION.search(result.stderr or "")
        if not match:
            raise ValueError("Audio senza durata valida")
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0:
        raise ValueError("Audio senza durata valida")
    return duration
