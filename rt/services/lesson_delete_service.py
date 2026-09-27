"""Delete a lesson with a validated path and a durable filesystem quarantine."""

import json
import os
import shutil
import uuid

from sqlalchemy import select

from rt.api.errors import ApiError
from rt.db.engine import get_database
from rt.db.models import Job, Lesson, LessonFile
from rt.db.session import session_scope
from rt.services.lesson_service import lessons_root
from rt.storage import fs


def _safe_child(path: str, root: str) -> bool:
    return (not os.path.islink(path) and os.path.realpath(os.path.dirname(path)) == root
            and os.path.dirname(os.path.abspath(path)) == root and os.path.basename(path) not in ("", ".", ".."))


def delete_lesson(lesson_id: int, lesson_dir: str) -> None:
    """Quarantine a folder before commit; remove its files only after the DB deletion."""
    db = get_database()
    root = lessons_root()
    if db is None or not root or not _safe_child(lesson_dir, os.path.realpath(root)):
        raise ApiError(409, "unsafe_lesson_path", "La lezione non è una cartella diretta della radice configurata.")

    with session_scope(db) as session:
        row = session.get(Lesson, lesson_id)
        if row is None or row.path != os.path.realpath(lesson_dir):
            raise ApiError(404, "lesson_not_found", "Lezione non trovata.")
        if session.scalar(select(Job.id).where(Job.lesson_path == row.path, Job.state.in_(
                ["queued", "running", "waiting_for_decision"])).limit(1)):
            raise ApiError(409, "lesson_busy", "La lezione ha job ancora attivi o in attesa.")
        media = [item for item in session.scalars(select(LessonFile.media_path).where(
            LessonFile.lesson_id == lesson_id, LessonFile.media_path.is_not(None)))]
        media_root = os.path.realpath(fs.media_dir(db))
        for rel in media:
            if os.path.isabs(rel) or not os.path.realpath(os.path.join(media_root, rel)).startswith(media_root + os.sep):
                raise ApiError(409, "unsafe_media_path", "Il percorso di un file media non è valido.")
            if session.scalar(select(LessonFile.id).where(LessonFile.media_path == rel,
                    LessonFile.lesson_id != lesson_id).limit(1)):
                raise ApiError(409, "shared_media", "Un file media è condiviso con un'altra lezione.")

        # A local journal survives a crash between the SQLite commit and physical cleanup.
        journal_dir = os.path.join(fs.data_dir(db), "pending-deletions")
        os.makedirs(journal_dir, mode=0o700, exist_ok=True)
        journal = os.path.join(journal_dir, f"{lesson_id}-{uuid.uuid4().hex}.json")
        staged = None
        if row.storage == "folder":
            if not os.path.isdir(lesson_dir):
                raise ApiError(404, "lesson_not_found", "Cartella della lezione non trovata.")
            staged = os.path.join(os.path.dirname(lesson_dir), f".rt-deleting-{lesson_id}-{uuid.uuid4().hex}")
        with open(journal, "x", encoding="utf-8") as stream:
            json.dump({"lesson_id": lesson_id, "original": lesson_dir, "staged": staged,
                       "media": media, "media_root": media_root}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if staged:
                os.replace(lesson_dir, staged)
            # Explicit deletes also work with older SQLite schemas lacking foreign keys.
            session.delete(row)
        except BaseException:
            if staged and os.path.isdir(staged):
                os.replace(staged, lesson_dir)
            os.unlink(journal)
            raise
    fs.forget(lesson_dir)
    recover_pending_deletions(db)


def recover_pending_deletions(db=None) -> None:
    """Finish a committed deletion or restore a folder if its transaction rolled back."""
    db = db or get_database()
    if db is None:
        return
    folder = os.path.join(fs.data_dir(db), "pending-deletions")
    if not os.path.isdir(folder):
        return
    for filename in os.listdir(folder):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(folder, filename)
        with open(path, encoding="utf-8") as stream:
            entry = json.load(stream)
        with session_scope(db) as session:
            exists = session.get(Lesson, entry["lesson_id"]) is not None
        staged = entry["staged"]
        if exists:
            if staged and os.path.isdir(staged) and not os.path.lexists(entry["original"]):
                os.replace(staged, entry["original"])
        else:
            if staged and os.path.isdir(staged):
                shutil.rmtree(staged)
            root = os.path.realpath(fs.media_dir(db))
            if entry["media_root"] != root:
                continue
            for rel in entry["media"]:
                full = os.path.realpath(os.path.join(root, rel))
                if not os.path.isabs(rel) and full.startswith(root + os.sep):
                    try:
                        os.unlink(full)
                    except FileNotFoundError:
                        pass
        os.unlink(path)
