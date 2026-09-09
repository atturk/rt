"""
rt.core.audio_clip
Gestione ritaglio e riproduzione audio in background durante la revisione interattiva.
"""

import os
import shutil
import tempfile
import subprocess
from typing import Optional
from rt.core.manifest import load_manifest


def resolve_audio_path(lesson_dir: str) -> Optional[str]:
    """
    Legge manifest.json ('audio_file') e ritorna il percorso assoluto del file audio
    se presente ed esistente, altrimenti None.
    """
    manifest = load_manifest(lesson_dir)
    if not manifest or not manifest.audio_file:
        return None

    raw_path = manifest.audio_file
    candidates = [
        raw_path if os.path.isabs(raw_path) else None,
        os.path.join(lesson_dir, raw_path),
        os.path.join(lesson_dir, os.path.basename(raw_path)),
    ]

    for cand in candidates:
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)

    return None


def cut_clip(audio_path: str, start_seconds: float, end_seconds: float) -> str:
    """
    Ritaglia un segmento audio usando ffmpeg e lo salva in un file temporaneo di sistema.
    Ritorna il percorso del file temporaneo creato.
    Solleva FileNotFoundError se ffmpeg non è nel PATH, o subprocess.CalledProcessError se il comando fallisce.
    """
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError("Il comando 'ffmpeg' non è presente nel PATH di sistema.")

    _, ext = os.path.splitext(audio_path)
    if not ext:
        ext = ".mp3"

    tmp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_seconds),
        "-to",
        str(end_seconds),
        "-i",
        audio_path,
        "-c",
        "copy",
        tmp_path,
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise e

    return tmp_path


def play_clip_background(clip_path: str) -> subprocess.Popen:
    """
    Avvia la riproduzione in background del clip audio tramite afplay (non bloccante).
    Ritorna l'oggetto subprocess.Popen corrispondente.
    """
    return subprocess.Popen(
        ["afplay", clip_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
