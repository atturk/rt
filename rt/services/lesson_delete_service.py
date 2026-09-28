"""Delete a lesson with a validated path and a durable filesystem quarantine."""

import contextlib
import fcntl
import json
import os
import shutil
import uuid

from sqlalchemy import select

from rt.api.errors import ApiError
from rt.db.engine import get_database
from rt.db.models import Job, Lesson, LessonFile, RecallSession, Setting, StateDocument, TelegramCommand
from rt.db.session import session_scope
from rt.services.lesson_service import lessons_root
from rt.storage import fs


def _safe_child(path: str, root: str) -> bool:
    return (not os.path.islink(path) and os.path.realpath(os.path.dirname(path)) == root
            and os.path.dirname(os.path.abspath(path)) == root and os.path.basename(path) not in ("", ".", ".."))


def purge_lesson_records(session, row: Lesson) -> None:
    """Toglie le righe legate alla lezione per percorso o per chiave (job conclusi, sessioni
    di recall, comandi Telegram, istruzioni aggiuntive, lease di modifica, documenti di
    stato): senza questo una lezione ricreata con lo stesso nome le erediterebbe."""
    from sqlalchemy import delete, or_
    from rt.services.document_edit_lease import _key as lease_key
    from rt.services.prompt_settings import extra_keys
    path = row.path
    for model in (RecallSession, TelegramCommand):
        session.execute(delete(model).where(model.lesson_path == path))
    for job in session.scalars(select(Job).where(Job.lesson_path == path)):
        session.delete(job)  # JobEvent in cascata anche senza foreign key attive
    keys = [lease_key(row.id), *extra_keys(path)]
    session.execute(delete(Setting).where(Setting.key.in_(keys)))
    session.execute(delete(StateDocument).where(or_(StateDocument.key == path,
                                                    StateDocument.key.startswith(path + os.sep))))


@contextlib.contextmanager
def _journal_lock(db, wait: bool = True):
    """Serializza cancellazione e recupero: senza, un recupero concorrente (GET /lessons)
    vedeva il journal prima del commit e rimetteva a posto la cartella appena cancellata.
    Restituisce False se wait=False e una cancellazione è in corso."""
    folder = os.path.join(fs.data_dir(db), "pending-deletions")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    with open(os.path.join(folder, ".lock"), "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def delete_lesson(lesson_id: int, lesson_dir: str) -> None:
    """Quarantine a folder before commit; remove its files only after the DB deletion."""
    db = get_database()
    root = lessons_root()
    if db is None:
        raise ApiError(503, "database_unavailable", "Database non disponibile.")
    with _journal_lock(db):
        _delete_locked(db, root, lesson_id, lesson_dir)
        _recover_locked(db)


def _delete_locked(db, root, lesson_id: int, lesson_dir: str) -> None:
    with session_scope(db) as session:
        row = session.get(Lesson, lesson_id)
        if row is None or row.path != os.path.realpath(lesson_dir):
            raise ApiError(404, "lesson_not_found", "Lezione non trovata.")
        if row.storage == "folder" and (not root or not _safe_child(lesson_dir, os.path.realpath(root))):
            raise ApiError(409, "unsafe_lesson_path", "La lezione non è una cartella diretta della radice configurata.")
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
            purge_lesson_records(session, row)
            session.delete(row)
        except BaseException:
            if staged and os.path.isdir(staged):
                os.replace(staged, lesson_dir)
            os.unlink(journal)
            raise
    fs.forget(lesson_dir)


def recover_pending_deletions(db=None) -> None:
    """Finish a committed deletion or restore a folder if its transaction rolled back.
    If a deletion is running right now it finishes its own journal, so there's nothing to do."""
    db = db or get_database()
    if db is None or not os.path.isdir(os.path.join(fs.data_dir(db), "pending-deletions")):
        return
    with _journal_lock(db, wait=False) as locked:
        if locked:
            _recover_locked(db)


def _recover_locked(db) -> None:
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
