"""
rt.storage.migrate
Migrazione una tantum delle lezioni "cartella" nel database (rt db migrate-storage).

Per ogni lezione:
1. copia ogni file nel DB (testi e metadati in lesson_files, media nella cartella media/);
   i nomi perdono il prefisso _state/ (se lo stesso file esiste sia alla radice sia in
   _state/ vince la radice, come fa lesson_path);
2. verifica file per file (sha256 e dimensione) che la copia sia identica;
3. solo se la verifica passa segna la lezione come storage "db", sposta le chiavi dello
   stato Telegram da <lezione>/_state/x a <lezione>/x e sposta la cartella originale nella
   cartella di backup (mai cancellata). Se la verifica fallisce la copia viene annullata e
   la lezione resta com'era.

Prima di toccare qualunque lezione il file del database viene copiato nella stessa cartella
di backup. Con dry_run=True non scrive nulla e restituisce solo il piano.
"""
import datetime
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from rt.storage import fs

SKIPPED_NAMES = {".DS_Store", "Thumbs.db", ".rt.lock", ".rt.job.lock"}
SKIPPED_SUFFIXES = (".tmp", ".migrated", ".lock")


@dataclass
class LessonPlan:
    lesson_dir: str
    files: Dict[str, str] = field(default_factory=dict)  # nome nel DB -> percorso reale
    skipped: List[str] = field(default_factory=list)
    text_bytes: int = 0
    media_bytes: int = 0


@dataclass
class MigrationReport:
    dry_run: bool
    backup_dir: Optional[str] = None
    database_backup: Optional[str] = None
    plans: List[LessonPlan] = field(default_factory=list)
    migrated: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _skip(name: str) -> bool:
    return name in SKIPPED_NAMES or name.endswith(SKIPPED_SUFFIXES)


def plan_lesson(lesson_dir: str) -> LessonPlan:
    plan = LessonPlan(lesson_dir=lesson_dir)
    state_files: Dict[str, str] = {}
    for base, dirs, names in os.walk(lesson_dir):
        dirs.sort()
        for name in sorted(names):
            real = os.path.join(base, name)
            rel = os.path.relpath(real, lesson_dir).replace(os.sep, "/")
            if _skip(name) or os.path.islink(real):
                plan.skipped.append(rel)
                continue
            if rel.startswith(fs.LEGACY_STATE_PREFIX):
                state_files[rel[len(fs.LEGACY_STATE_PREFIX):]] = real
            else:
                plan.files[rel] = real
    for name, real in state_files.items():
        if name in plan.files:
            plan.skipped.append(fs.LEGACY_STATE_PREFIX + name + " (esiste già alla radice)")
        else:
            plan.files[name] = real
    for name, real in plan.files.items():
        size = os.path.getsize(real)
        if fs.is_media_name(name):
            plan.media_bytes += size
        else:
            plan.text_bytes += size
    return plan


def folder_lessons(db, lessons_root: Optional[str]) -> List[str]:
    """Lezioni ancora in cartella: quelle di lessons_root più quelle note al DB."""
    from sqlalchemy import select
    from rt.core.lesson_index import scan_lessons
    from rt.db.models import Lesson
    from rt.db.repositories import normalize_lesson_path
    from rt.db.session import session_scope
    found: List[str] = []
    if lessons_root and os.path.isdir(lessons_root):
        found = [normalize_lesson_path(e.lesson_dir) for e in scan_lessons(lessons_root)
                 if os.path.isdir(e.lesson_dir)]
    with session_scope(db) as s:
        for path in s.scalars(select(Lesson.path).where(Lesson.storage != fs.STORAGE_DB)):
            is_lesson = any(os.path.isfile(os.path.join(path, *p)) for p in (("info.yaml",), ("_state", "info.yaml")))
            if path not in found and is_lesson:
                found.append(path)
    return [p for p in found if not fs.is_db_lesson(p)]


def backup_database(db, backup_dir: str) -> Optional[str]:
    """Copia coerente del file SQLite (API di backup di sqlite3). None per altri backend."""
    import sqlite3
    from rt.db.engine import sqlite_file
    path = sqlite_file(db.url)
    if not path or not os.path.isfile(path):
        return None
    target = os.path.join(backup_dir, os.path.basename(path))
    src = sqlite3.connect(path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def _import_files(db, lesson_id: int, lesson_path: str, plan: LessonPlan) -> List[str]:
    """Copia i file nel DB e restituisce gli errori di verifica (lista vuota = tutto ok)."""
    targets = {name: fs.DbTarget(db, lesson_id, lesson_path, name) for name in plan.files}
    for name, real in plan.files.items():
        if fs.is_media_name(name):
            fs._register_media_file(targets[name], real, move=False)
        else:
            with open(real, "rb") as f:
                fs._store(targets[name], f.read())
    errors = []
    stored = {row["name"]: row for row in _rows(db, lesson_id)}
    for name, real in plan.files.items():
        row = stored.get(name)
        if row is None:
            errors.append(f"{name}: non copiato")
            continue
        if row["sha256"] != fs.sha256(real) or row["size"] != os.path.getsize(real):
            errors.append(f"{name}: copia diversa dall'originale")
        if row["media_path"] and not os.path.isfile(os.path.join(fs.media_dir(db), row["media_path"])):
            errors.append(f"{name}: media mancante in {fs.media_dir(db)}")
    return errors


def _rows(db, lesson_id: int) -> List[Dict[str, object]]:
    from sqlalchemy import select
    from rt.db.models import LessonFile
    from rt.db.session import session_scope
    with session_scope(db) as s:
        return [{"name": r.name, "sha256": r.sha256, "size": r.size, "media_path": r.media_path}
                for r in s.scalars(select(LessonFile).where(LessonFile.lesson_id == lesson_id))]


def _discard_import(db, lesson_id: int) -> None:
    from sqlalchemy import select
    from rt.db.models import LessonFile
    from rt.db.session import session_scope
    media = []
    with session_scope(db) as s:
        for row in s.scalars(select(LessonFile).where(LessonFile.lesson_id == lesson_id)):
            if row.media_path:
                media.append(os.path.join(fs.media_dir(db), row.media_path))
            s.delete(row)
    for path in media:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _rekey_state_documents(session, lesson_path: str) -> None:
    from sqlalchemy import select
    from rt.db.models import StateDocument
    prefix = os.path.join(lesson_path, "_state") + os.sep
    for doc in list(session.scalars(select(StateDocument).where(StateDocument.key.startswith(prefix, autoescape=True)))):
        new_key = os.path.join(lesson_path, doc.key[len(prefix):])
        if session.get(StateDocument, new_key) is None:
            session.add(StateDocument(key=new_key, payload=doc.payload))
        session.delete(doc)


def migrate_lesson(db, lesson_dir: str, backup_dir: str) -> List[str]:
    """Migra una lezione; restituisce gli errori (lista vuota = migrata)."""
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    from rt.db.sync import sync_lesson
    plan = plan_lesson(lesson_dir)
    with session_scope(db) as s:
        lesson = LessonRepository(s).get_by_path(lesson_dir) or sync_lesson(s, lesson_dir)
        if lesson is None:
            return ["info.yaml mancante: non è una lezione"]
        lesson_id, lesson_path = lesson.id, lesson.path
    _discard_import(db, lesson_id)  # residui di un tentativo interrotto
    try:
        errors = _import_files(db, lesson_id, lesson_path, plan)
    except Exception as exc:
        errors = [f"copia interrotta: {exc}"]
    if errors:
        _discard_import(db, lesson_id)
        return errors
    from rt.db.models import Lesson
    with session_scope(db) as s:
        s.get(Lesson, lesson_id).storage = fs.STORAGE_DB
        _rekey_state_documents(s, lesson_path)
    fs.forget(lesson_path)
    target = os.path.join(backup_dir, os.path.basename(lesson_path))
    try:
        os.makedirs(backup_dir, exist_ok=True)
        shutil.move(lesson_dir, target)
    except OSError as exc:
        return [f"migrata nel database, ma la cartella originale non è stata spostata nel backup ({exc}): "
                "RT ora la ignora, puoi spostarla a mano"]
    return []


def migrate_storage(
    lessons_root: Optional[str],
    dry_run: bool = False,
    backup_root: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> MigrationReport:
    from rt.db.engine import get_database
    db = get_database(create=True)
    if db is None:
        raise RuntimeError("Il database è spento (RT_DATABASE_URL=off): impossibile migrare le lezioni.")
    say = on_progress or (lambda _msg: None)
    root = os.path.abspath(os.path.expanduser(lessons_root)) if lessons_root else None
    report = MigrationReport(dry_run=dry_run)
    report.plans = [plan_lesson(d) for d in folder_lessons(db, root)]
    if dry_run or not report.plans:
        return report
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report.backup_dir = os.path.join(backup_root or os.path.join(fs.data_dir(db), "backups"), f"migrazione-{stamp}")
    os.makedirs(report.backup_dir, exist_ok=True)
    report.database_backup = backup_database(db, report.backup_dir)
    lessons_backup = os.path.join(report.backup_dir, "lezioni")
    for plan in report.plans:
        name = os.path.basename(plan.lesson_dir)
        say(f"→ {name}: {len(plan.files)} file")
        errors = migrate_lesson(db, plan.lesson_dir, lessons_backup)
        if errors and not fs.is_db_lesson(plan.lesson_dir):
            report.errors.extend(f"{name}: {e}" for e in errors)
            continue
        report.migrated.append(plan.lesson_dir)
        report.errors.extend(f"{name}: {e}" for e in errors)
    return report
