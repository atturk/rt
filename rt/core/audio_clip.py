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
    raw_path = manifest.audio_file if manifest else None
    if not raw_path:
        # Lezioni importate con le fonti: il manifest può non avere l'audio, che sta in
        # info.yaml con il percorso dentro sources/<id>/.
        info_path = os.path.join(lesson_dir, "info.yaml")
        if fs.isfile(info_path):
            from rt.core.state import read_info_yaml
            try:
                raw_path = read_info_yaml(info_path).get("file_audio")
            except Exception:
                raw_path = None
    if not raw_path:
        return None
    raw_path = str(raw_path)
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

