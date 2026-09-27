"""Validate complete lesson archives before creating a new database lesson."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile

from rt.api.errors import ApiError
from rt.core.lesson_paths import lesson_path
from rt.db.engine import get_database
from rt.db.models import Lesson
from rt.db.repositories import LessonRepository
from rt.db.session import session_scope
from rt.services.lesson_service import lessons_root
from rt.storage import fs

MAX_FILES = 1000
MAX_BYTES = 2 * 1024 ** 3
MAX_RATIO = 200


def import_archive(archive: str) -> int:
    root = lessons_root()
    db = get_database()
    if not root or db is None:
        raise ApiError(409, "setup_required", "Configura la cartella dati prima di importare.")
    with zipfile.ZipFile(archive) as zipped:
        files = [item for item in zipped.infolist() if not item.is_dir()]
        if len(files) > MAX_FILES or sum(item.file_size for item in files) > MAX_BYTES:
            raise ApiError(413, "archive_too_large", "Archivio troppo grande.")
        names = [item.filename for item in files]
        if len(names) != len({n.casefold() for n in names}):
            raise ApiError(422, "invalid_archive", "L'archivio contiene nomi duplicati.")
        parts = [name.split("/") for name in names]
        if not parts or any(len(p) < 2 or any(s in ("", ".", "..") for s in p) or "\\" in name
                            or name.startswith("/") for name, p in zip(names, parts)):
            raise ApiError(422, "invalid_archive", "Percorsi non validi nell'archivio.")
        folder = parts[0][0]
        if any(p[0] != folder for p in parts) or folder.startswith(".") or folder.endswith(" "):
            raise ApiError(422, "invalid_archive", "L'archivio deve contenere una sola lezione.")
        if any(stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or
               (item.file_size and item.file_size > MAX_RATIO * max(1, item.compress_size)) for item in files):
            raise ApiError(422, "invalid_archive", "L'archivio contiene link, file cifrati o compressione sospetta.")
        manifest_name = f"{folder}/rt-export.json"
        if manifest_name not in names:
            raise ApiError(422, "invalid_archive", "Manca il manifesto di un export completo di RT.")
        manifest = json.loads(zipped.read(manifest_name))
        if manifest.get("format") != "rt-lesson" or manifest.get("version") != 1 or manifest.get("scope") != "all":
            raise ApiError(422, "invalid_archive", "Formato o versione dell'archivio non supportati.")
        rows = manifest.get("files")
        if not isinstance(rows, list) or len(rows) != len({row.get("path") for row in rows if isinstance(row, dict)}):
            raise ApiError(422, "invalid_archive", "Manifesto non valido.")
        declared = {f"{folder}/{row['path']}": row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)}
        extras = set(names) - set(declared) - {manifest_name}
        if extras - {f"{folder}/LEGGIMI - anteprima.txt"} and not all("(anteprima)" in n for n in extras):
            raise ApiError(422, "invalid_archive", "File non dichiarati nel manifesto.")
        if not declared or not f"{folder}/info.yaml" in declared or set(declared) - set(names):
            raise ApiError(422, "invalid_archive", "Archivio incompleto: manca info.yaml o un file dichiarato.")

        target = os.path.join(os.path.realpath(root), folder)
        with session_scope(db) as session:
            if LessonRepository(session).get_by_path(target) or os.path.lexists(target):
                raise ApiError(409, "duplicate_lesson", f"La lezione {folder} esiste già.")
        os.makedirs(root, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rt-import-", dir=root) as staging:
            for name, row in declared.items():
                item = zipped.getinfo(name)
                if item.file_size != row.get("size") or item.file_size > MAX_BYTES:
                    raise ApiError(422, "invalid_archive", "Dimensione del file incoerente.")
                rel = name[len(folder) + 1:]
                destination = os.path.join(staging, *rel.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                digest = hashlib.sha256()
                with zipped.open(item) as source, open(destination, "wb") as output:
                    while chunk := source.read(1 << 20):
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != row.get("sha256"):
                    raise ApiError(422, "invalid_archive", "Checksum dei file non corrispondente.")
            # Copy into DB storage only after every entry has passed validation.
            target = fs.create_db_lesson(target)
            try:
                for name in declared:
                    rel = name[len(folder) + 1:]
                    fs.copy2(os.path.join(staging, *rel.split("/")), lesson_path(target, rel))
            except BaseException:
                from rt.services.lesson_delete_service import delete_lesson
                with session_scope(db) as session:
                    created = LessonRepository(session).get_by_path(target)
                    lesson_id = created.id
                delete_lesson(lesson_id, target)
                raise
        with session_scope(db) as session:
            lesson = LessonRepository(session).get_by_path(target)
            return lesson.id
