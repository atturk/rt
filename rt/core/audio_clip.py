"""
rt.core.audio_clip
Gestione ritaglio e riproduzione audio in background durante la revisione interattiva.
"""

import os
import json
import shutil
import tempfile
import subprocess
from typing import Optional, List, Tuple
from rt.core.manifest import load_manifest
from rt.storage import fs


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
        if cand and fs.isfile(cand):
            # percorso reale (per le lezioni nel DB: il file nella cartella media)
            return fs.real_path(os.path.abspath(cand))

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
        if fs.exists(tmp_path):
            try:
                fs.remove(tmp_path)
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


def get_terminal_bounds() -> Optional[Tuple[int, int, int, int]]:
    """Rileva le coordinate (x1, y1, x2, y2) della finestra attiva di Terminal.app via AppleScript."""
    try:
        script = 'tell application "Terminal" to get bounds of front window'
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout.strip():
            parts = [int(p.strip()) for p in res.stdout.strip().split(",")]
            if len(parts) == 4:
                return (parts[0], parts[1], parts[2], parts[3])
    except Exception:
        pass
    return None


def get_mpv_last_position_path() -> str:
    return os.path.expanduser("~/.rt/mpv_last_position.json")


def load_last_mpv_geometry() -> str:
    path = get_mpv_last_position_path()
    if fs.isfile(path):
        try:
            with fs.open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "geometry" in data and data["geometry"]:
                return data["geometry"]
        except Exception:
            pass
    return "+800+50"


def save_last_mpv_geometry(geometry: str) -> None:
    path = get_mpv_last_position_path()
    try:
        fs.makedirs(os.path.dirname(path), exist_ok=True)
        with fs.open(path, "w", encoding="utf-8") as f:
            json.dump({"geometry": geometry}, f)
    except Exception:
        pass


def calculate_mpv_geometry() -> str:
    bounds = get_terminal_bounds()
    if bounds:
        x1, y1, x2, y2 = bounds
        h = max(320, min(y2 - y1, 540))
        geom = f"480x{h}+{x2}+{y1}"
        save_last_mpv_geometry(geom)
        return geom
    return load_last_mpv_geometry()


def get_or_create_unit_clip(lesson_dir: str, unit, segments: List) -> Optional[str]:
    from rt.core.lesson_paths import lesson_path
    audio_path = resolve_audio_path(lesson_dir)
    if not audio_path:
        return None
    clips_dir = lesson_path(lesson_dir, "recall_audio_clips")
    fs.makedirs(clips_dir, exist_ok=True)
    ext = os.path.splitext(audio_path)[1] or ".mp3"
    clip_path = os.path.join(clips_dir, f"{unit.unit_id}{ext}")
    if not fs.isfile(clip_path):
        start_s, end_s = resolve_unit_time_range(unit, segments)
        tmp_clip = cut_clip(audio_path, start_s, end_s)
        fs.move(tmp_clip, clip_path)
    return fs.real_path(clip_path)


def resolve_unit_time_range(unit, segments: List) -> Tuple[float, float]:
    """Risolve l'intervallo temporale (start_s, end_s) di una DraftUnit nel file audio della lezione."""
    start_seg = next((s for s in segments if s.id == unit.start_segment_id), None)
    end_seg = next((s for s in segments if s.id == unit.end_segment_id), None)
    if not start_seg or not end_seg:
        raise ValueError(f"Segmenti per l'unità '{unit.unit_id}' non trovati (start: {unit.start_segment_id}, end: {unit.end_segment_id}).")
    return (float(start_seg.start_seconds), float(end_seg.end_seconds))
