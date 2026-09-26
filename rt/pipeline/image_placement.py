"""
rt.pipeline.image_placement
Posizionamento delle immagini nel documento: quale immagine (hash in descriptions.json) va
sotto quale macro-sezione, e se mostrarle come carosello. Lo scrive 'rt add-images' sulla
bozza; lo leggono l'anteprima, l'export e il build, che così includono le stesse immagini.
Il file è un input del build (rt.core.idempotency.BUILD_INPUT_FILES): aggiungere immagini a
una lezione con il documento già creato lo rende non aggiornato.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from rt.core.idempotency import IMAGE_PLACEMENT_FILE
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


def get_placement_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, IMAGE_PLACEMENT_FILE)


def load_image_placement(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """{"macros": {macro_id: [hash, ...]}, "carousel": bool}, oppure None se mai scritto."""
    path = get_placement_path(lesson_dir)
    if not fs.isfile(path):
        return None
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    macros = data.get("macros") if isinstance(data.get("macros"), dict) else {}
    return {"macros": {str(k): [str(h) for h in (v or [])] for k, v in macros.items()},
            "carousel": bool(data.get("carousel"))}


def save_image_placement(lesson_dir: str, macros: Dict[str, List[str]], carousel: bool) -> bool:
    """Scrive il posizionamento (atomico). True se è cambiato rispetto a prima."""
    data = {"macros": {str(k): list(v) for k, v in macros.items() if v}, "carousel": bool(carousel)}
    previous = load_image_placement(lesson_dir)
    if previous == data:
        return False
    path = get_placement_path(lesson_dir)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    fs.replace(tmp_path, path)
    return True


def images_for_document(lesson_dir: str, outline: Any) -> Tuple[Dict[str, List[dict]], bool]:
    """(images_by_macro, carousel) per render_rielaborato_md: solo immagini descritte e
    macro-sezioni che esistono ancora nella scaletta."""
    placement = load_image_placement(lesson_dir)
    if not placement:
        return {}, False
    from rt.pipeline.add_images import load_image_descriptions
    descriptions = load_image_descriptions(lesson_dir)
    macro_ids = {str(m.id) for m in getattr(outline, "macro_sections", [])}
    by_macro: Dict[str, List[dict]] = {}
    for macro_id, hashes in placement["macros"].items():
        if macro_id not in macro_ids:
            continue
        images = [descriptions[h] for h in hashes if h in descriptions]
        if images:
            by_macro[macro_id] = images
    return by_macro, placement["carousel"]
