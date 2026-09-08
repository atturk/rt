"""
rt.core.manifest
Gestione del file manifest.json per la tracciabilità completa della lezione.
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any
from rt.core.models import Manifest


def get_manifest_path(lesson_dir: str) -> str:
    return os.path.join(lesson_dir, "manifest.json")


def load_manifest(lesson_dir: str) -> Optional[Manifest]:
    path = get_manifest_path(lesson_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Manifest.model_validate(data)
    except Exception:
        return None


def save_manifest(manifest: Manifest, lesson_dir: Optional[str] = None) -> None:
    """Scrive manifest.json in modo atomico. Passare `lesson_dir` (la posizione
    fisica reale, viva, della lezione) è fortemente consigliato: corregge
    automaticamente `manifest.lesson_dir` se la cartella è stata spostata a mano
    (mv, Finder) dopo l'ultima scrittura — altrimenti si scriverebbe nel vecchio
    percorso, ormai inesistente, facendo fallire il salvataggio."""
    target_dir = lesson_dir if lesson_dir is not None else manifest.lesson_dir
    if lesson_dir is not None:
        abs_dir = os.path.abspath(lesson_dir)
        if abs_dir != manifest.lesson_dir:
            manifest.lesson_dir = abs_dir
    path = get_manifest_path(target_dir)
    data = manifest.model_dump(mode="json")
    # Scrittura atomica
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def init_or_update_manifest(
    lesson_dir: str,
    lesson_id: str,
    date: str,
    subject: str,
    current_state: str,
    topics: Optional[str] = None,
    segment_count: int = 0,
    audio_file: Optional[str] = None,
    audio_duration_seconds: Optional[float] = None,
    model_info: Optional[Dict[str, Any]] = None,
    coverage_stats: Optional[Dict[str, Any]] = None,
    phase_records: Optional[Dict[str, Any]] = None
) -> Manifest:
    """Crea o aggiorna il manifest preservando i campi storici."""
    existing = load_manifest(lesson_dir)
    now_iso = datetime.now().isoformat()
    
    if existing:
        existing.lesson_id = lesson_id
        existing.lesson_dir = os.path.abspath(lesson_dir)
        existing.date = date
        existing.subject = subject
        existing.topics = topics
        existing.current_state = current_state
        existing.segment_count = segment_count if segment_count > 0 else existing.segment_count
        if audio_file:
            existing.audio_file = audio_file
        if audio_duration_seconds:
            existing.audio_duration_seconds = audio_duration_seconds
        if model_info:
            existing.model_info.update(model_info)
        if coverage_stats:
            existing.coverage_stats.update(coverage_stats)
        if phase_records:
            existing.phase_records.update(phase_records)
        existing.updated_at = now_iso
        save_manifest(existing, lesson_dir)
        return existing
    else:
        new_manifest = Manifest(
            schema_version="1.0",
            workflow_version="2.0.0",
            lesson_id=lesson_id,
            lesson_dir=os.path.abspath(lesson_dir),
            date=date,
            subject=subject,
            topics=topics,
            audio_file=audio_file,
            audio_duration_seconds=audio_duration_seconds,
            segment_count=segment_count,
            current_state=current_state,
            created_at=now_iso,
            updated_at=now_iso,
            model_info=model_info or {},
            coverage_stats=coverage_stats or {},
            phase_records=phase_records or {}
        )
        save_manifest(new_manifest, lesson_dir)
        return new_manifest
