"""
rt.core.audio_clip
Percorso del file audio di una lezione, letto dal manifest.
"""

import os
from typing import Optional
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

