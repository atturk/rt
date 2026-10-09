"""
rt.pipeline.document_edits
Modifiche fatte a mano all'anteprima del documento (RT4-FA3) che non stanno nella bozza:
titoli di sezioni e unità, timecode spostati e unità il cui testo è già stato scritto
dall'utente con le decisioni della revisione dentro.

Il file (document_edits.json) è un input del build quando esiste
(rt.core.idempotency.DOCUMENT_EDITS_FILE): una modifica rende il documento da ricreare.

Formato:
    {"macros": {"1": {"title": "..."}},
     "units": {"1.1": {"title": "...", "start_segment_id": "seg_000012", "edited": true}}}
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional, Set

from rt.core.idempotency import DOCUMENT_EDITS_FILE
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


def get_document_edits_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, DOCUMENT_EDITS_FILE)


def load_document_edits(lesson_dir: str) -> Dict[str, Any]:
    """Modifiche salvate ({"macros": {}, "units": {}} se non ce ne sono)."""
    empty: Dict[str, Any] = {"macros": {}, "units": {}}
    path = get_document_edits_path(lesson_dir)
    if not fs.isfile(path):
        return empty
    try:
        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "macros": {str(k): dict(v) for k, v in (data.get("macros") or {}).items() if isinstance(v, dict)},
        "units": {str(k): dict(v) for k, v in (data.get("units") or {}).items() if isinstance(v, dict)},
    }


def save_document_edits(lesson_dir: str, edits: Dict[str, Any]) -> bool:
    """Scrive le modifiche (atomico) togliendo le voci vuote. True se il file è cambiato."""
    clean = {
        "macros": {k: v for k, v in (edits.get("macros") or {}).items() if v},
        "units": {k: v for k, v in (edits.get("units") or {}).items() if v},
    }
    path = get_document_edits_path(lesson_dir)
    if not clean["macros"] and not clean["units"]:
        if fs.isfile(path):
            fs.remove(path)
            return True
        return False
    if load_document_edits(lesson_dir) == clean and fs.isfile(path):
        return False
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2, sort_keys=True)
    fs.replace(tmp_path, path)
    return True


def edited_unit_dates(lesson_dir: str) -> Dict[str, str]:
    """Date delle modifiche manuali; i file storici usano la propria data."""
    edits = load_document_edits(lesson_dir)
    path = get_document_edits_path(lesson_dir)
    fallback = datetime.fromtimestamp(fs.getmtime(path)).isoformat() if fs.isfile(path) else ""
    return {uid: entry.get("edited_at") or fallback
            for uid, entry in edits["units"].items() if entry.get("edited")}


def edited_unit_ids(lesson_dir: str) -> Set[str]:
    """Unità il cui testo nella bozza è quello scritto dall'utente nell'anteprima, con le
    decisioni della revisione già dentro: non si riapplicano."""
    return {uid for uid, v in load_document_edits(lesson_dir)["units"].items() if v.get("edited")}


def unit_title(edits: Dict[str, Any], unit_id: str, default: str) -> str:
    return (edits.get("units", {}).get(str(unit_id)) or {}).get("title") or default


def macro_title(edits: Dict[str, Any], macro_id: str, default: str) -> str:
    return (edits.get("macros", {}).get(str(macro_id)) or {}).get("title") or default


def unit_start_segment(edits: Dict[str, Any], unit_id: str, default: str) -> str:
    return (edits.get("units", {}).get(str(unit_id)) or {}).get("start_segment_id") or default


def optional_edits(lesson_dir: Optional[str]) -> Dict[str, Any]:
    return load_document_edits(lesson_dir) if lesson_dir else {"macros": {}, "units": {}}
