"""Integrità del database e dei media usati dalle lezioni correnti."""

import hashlib
import os

from sqlalchemy import select

from rt.db.models import Lesson, LessonFile
from rt.db.session import read_scope
from rt.storage import fs


def check_database(db) -> list[str]:
    """Restituisce problemi DB/media; non importa né modifica dati."""
    issues: list[str] = []
    if db.engine.dialect.name == "sqlite":
        with db.engine.connect() as connection:
            result = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if result != "ok":
            issues.append(f"Integrità SQLite: {result}")
        if foreign_keys:
            issues.append(f"Integrità relazionale SQLite: {len(foreign_keys)} riferimenti esterni non validi.")

    media_root = os.path.realpath(fs.media_dir(db))
    referenced: set[str] = set()
    with read_scope(db) as session:
        lessons = list(session.scalars(select(Lesson).order_by(Lesson.id)))
        files = list(session.scalars(select(LessonFile).order_by(LessonFile.lesson_id, LessonFile.name)))
        lesson_names = {lesson.id: lesson.folder_name for lesson in lessons}
        folder_count = sum(lesson.storage != fs.STORAGE_DB for lesson in lessons)
        if folder_count:
            issues.append(f"{folder_count} lezioni usano ancora lo storage a cartelle; convertile con 'rt db migrate-storage'.")
        for row in files:
            label = f"{lesson_names.get(row.lesson_id, row.lesson_id)}/{row.name}"
            if bool(row.content is not None) == bool(row.media_path):
                issues.append(f"{label}: deve contenere dati testuali oppure un riferimento media.")
                continue
            if row.media_path is None:
                if len(row.content or b"") != row.size:
                    issues.append(f"{label}: dimensione del contenuto incoerente.")
                digest = hashlib.sha256(row.content or b"").hexdigest()
                if row.sha256 and digest != row.sha256:
                    issues.append(f"{label}: checksum del contenuto incoerente.")
                continue

            relative = row.media_path
            target = os.path.realpath(os.path.join(media_root, relative))
            if (os.path.isabs(relative) or target != media_root and not target.startswith(media_root + os.sep)):
                issues.append(f"{label}: percorso media non valido.")
                continue
            referenced.add(target)
            try:
                if os.path.getsize(target) != row.size:
                    issues.append(f"{label}: dimensione media incoerente.")
                    continue
                digest = hashlib.sha256()
                with open(target, "rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if row.sha256 and digest.hexdigest() != row.sha256:
                    issues.append(f"{label}: checksum media incoerente.")
            except OSError:
                issues.append(f"{label}: file media mancante.")

    if os.path.isdir(media_root):
        for current, _, names in os.walk(media_root):
            for name in names:
                path = os.path.realpath(os.path.join(current, name))
                if path not in referenced:
                    issues.append(f"Media orfano non referenziato: {os.path.relpath(path, media_root)}")
    return issues
