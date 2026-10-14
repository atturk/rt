"""
rt.pipeline.image_placement
Posizionamento delle immagini nel documento: quale immagine (hash in descriptions.json) va
sotto quale macro-sezione, e se mostrarle come carosello. Lo scrive 'rt add-images' sulla
bozza; lo leggono l'anteprima, l'export e il build, che così includono le stesse immagini.
Il file è un input del build (rt.core.idempotency.BUILD_INPUT_FILES): aggiungere immagini a
una lezione con il documento già creato lo rende non aggiornato.
"""
from rt.core.lesson_lock import lesson_locked

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from rt.core.idempotency import IMAGE_PLACEMENT_FILE
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


class DocumentImages(tuple):
    """Tupla compatibile (by_macro, carousel) arricchita con by_unit."""
    def __new__(cls, by_macro, carousel, by_unit=None):
        combined = {**by_macro, **(by_unit or {})}
        return super().__new__(cls, (combined, carousel))

    def __init__(self, by_macro, carousel, by_unit=None):
        self.by_macro = by_macro
        self.carousel = carousel
        self.by_unit = by_unit or {}
        self.macros = self.by_macro
        self.units = self.by_unit


def get_placement_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, IMAGE_PLACEMENT_FILE)


def load_image_placement(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """{"macros": {macro_id: [hash, ...]}, "units": {unit_id: [hash, ...]}, "carousel": bool}, oppure None se mai scritto."""
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
    units = data.get("units") if isinstance(data.get("units"), dict) else {}
    return {
        "macros": {str(k): [str(h) for h in (v or [])] for k, v in macros.items()},
        "units": {str(k): [str(h) for h in (v or [])] for k, v in units.items()},
        "carousel": bool(data.get("carousel")),
    }


@lesson_locked
def save_image_placement(lesson_dir: str, macros: Dict[str, List[str]], carousel: bool, units: Optional[Dict[str, List[str]]] = None) -> bool:
    """Scrive il posizionamento (atomico). True se è cambiato rispetto a prima."""
    units_dict = {str(k): list(v) for k, v in (units or {}).items() if v}
    data = {
        "macros": {str(k): list(v) for k, v in macros.items() if v},
        "units": units_dict,
        "carousel": bool(carousel),
    }
    previous = load_image_placement(lesson_dir)
    if previous == data:
        return False
    path = get_placement_path(lesson_dir)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    fs.replace(tmp_path, path)
    from rt.services.documents_service import request_documents
    request_documents(lesson_dir)
    return True


def images_for_document(lesson_dir: str, outline: Any) -> DocumentImages:
    """(images_by_macro, carousel) arricchito con .by_unit: solo immagini descritte
    e sezioni/subunità che esistono ancora nella scaletta."""
    placement = load_image_placement(lesson_dir)
    if not placement:
        return DocumentImages({}, False, {})
    from rt.pipeline.add_images import load_image_descriptions
    descriptions = load_image_descriptions(lesson_dir)
    macro_ids = {str(m.id) for m in getattr(outline, "macro_sections", [])}
    unit_ids = {str(u.id) for m in getattr(outline, "macro_sections", []) for u in getattr(m, "units", [])}

    by_macro: Dict[str, List[dict]] = {}
    for macro_id, hashes in placement["macros"].items():
        if macro_id not in macro_ids:
            continue
        images = [descriptions[h] for h in hashes if h in descriptions]
        if images:
            by_macro[macro_id] = images

    by_unit: Dict[str, List[dict]] = {}
    for unit_id, hashes in placement.get("units", {}).items():
        if unit_id not in unit_ids:
            continue
        images = [descriptions[h] for h in hashes if h in descriptions]
        if images:
            by_unit[unit_id] = images

    return DocumentImages(by_macro, placement["carousel"], by_unit)
