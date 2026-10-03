"""Modifica i metadati mantenendo ID, media e storico della lezione."""
import os
import re
from typing import Any, Dict

from sqlalchemy import select

from rt.core.lesson_paths import lesson_path
from rt.core.manifest import load_manifest, save_manifest
from rt.core.process_lock import LessonBusy, lesson_work_lock
from rt.core.state import read_info_yaml, update_info_yaml
from rt.db.models import Job, Lesson
from rt.db.session import session_scope
from rt.db.sync import relocate_path_keyed_rows, suspend_dual_write, sync_lesson
from rt.services.errors import Conflict, NotFound
from rt.services.lesson_service import _require_db, clear_summary_cache, lesson_detail, lessons_root
from rt.storage import fs


def update_metadata(lesson_id: int, lesson_dir: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """La transazione impedisce ai job di partire durante la rinomina; il flock copre la CLI."""
    try:
        with lesson_work_lock(lesson_dir):
            current = _update_locked(lesson_id, lesson_dir, updates)
    except LessonBusy:
        raise Conflict("lesson_busy", "La lezione è in lavorazione.") from None
    clear_summary_cache()
    return lesson_detail(lesson_id, current)


def _update_locked(lesson_id: int, lesson_dir: str, updates: Dict[str, Any]) -> str:
    db = _require_db()
    current = lesson_dir
    backups = {}
    moved = False
    folder = False
    try:
        with session_scope(db) as session, suspend_dual_write():
            row = session.get(Lesson, lesson_id)
            if row is None or row.path != os.path.realpath(lesson_dir):
                raise NotFound("lesson_not_found", "Lezione non trovata.")
            busy = session.scalar(select(Job).where(Job.lesson_path == row.path,
                Job.state.in_(["queued", "running", "waiting_for_decision"])).limit(1))
            if busy:
                raise Conflict("lesson_busy", "La lezione ha un job attivo o in attesa.", {"job_id": busy.id})
            from rt.services.document_edit_lease import is_being_edited, DocumentBeingEdited
            if is_being_edited(session, lesson_id):
                raise DocumentBeingEdited()
            folder = row.storage == fs.STORAGE_FOLDER
            if folder:
                from rt.services.lesson_delete_service import _safe_child
                root = lessons_root()
                if not root or not _safe_child(lesson_dir, os.path.realpath(root)):
                    raise Conflict("unsafe_lesson_path", "La cartella non è nella radice delle lezioni.")
            info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
            changed = {k: v for k, v in updates.items() if info.get(k, "") != v}
            if not changed:
                return lesson_dir
            info.update(changed)
            safe = lambda value: re.sub(r'\s+', ' ', re.sub(r'[/\\:*?"<>|]', ' ', value)).strip().rstrip('.')
            name = f"[{info.get('data') or '0000-00-00'}] {safe(info.get('materia') or 'MATERIA')} - {safe(info.get('titolo') or 'Lezione')}"
            target = os.path.join(os.path.dirname(row.path), name)
            if target != row.path and (os.path.lexists(target) or session.scalar(select(Lesson.id).where(Lesson.path == target))):
                raise Conflict("lesson_name_conflict", "Esiste già una lezione con questo nome.")
            for filename in ("info.yaml", "manifest.json"):
                path = lesson_path(lesson_dir, filename)
                if fs.isfile(path):
                    with fs.open(path, "rb") as stream:
                        backups[filename] = stream.read()
            if target != row.path:
                old = row.path
                if folder:
                    os.rename(old, target)
                    row.path, row.folder_name = target, name
                    relocate_path_keyed_rows(session, old, target)
                else:
                    fs.rename(old, target)
                moved, current = True, target
            # Il titolo del documento segue quello scelto dall'utente anche al prossimo build.
            if 'titolo' in changed:
                changed['titolo_personalizzato'] = 'true'
            changed['metadati_modificati'] = 'true'
            update_info_yaml(lesson_path(current, "info.yaml"), changed)
            manifest = load_manifest(current)
            if manifest:
                manifest.date, manifest.subject = info.get('data', ''), info.get('materia', '')
                save_manifest(manifest, current)
            sync_lesson(session, current)
    except BaseException:
        # Per lo storage DB il rollback ripristina tutto; per le cartelle ripristiniamo i file.
        if folder:
            if moved:
                os.rename(current, lesson_dir)
            for filename, content in backups.items():
                with fs.open(lesson_path(lesson_dir, filename), 'wb') as stream:
                    stream.write(content)
        fs.forget(current)
        fs.forget(lesson_dir)
        raise
    fs.forget(lesson_dir)
    fs.forget(current)
    return current
