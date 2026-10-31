"""Valida gli archivi completi delle lezioni e gli ZIP di gruppo prima dell'importazione."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from typing import BinaryIO, List, Optional, Union

from rt.services.errors import Conflict, Invalid, TooLarge
from rt.core.lesson_paths import lesson_path
from rt.db.engine import get_database
from rt.db.models import Lesson
from rt.db.repositories import LessonRepository
from rt.db.session import session_scope
from rt.services.lesson_service import lessons_root, work_dir
from rt.storage import fs
from rt.storage.export import PREVIEW_README, PREVIEW_SUFFIX

MAX_FILES = 1000
MAX_BYTES = 2 * 1024 ** 3
MAX_RATIO = 200


def _checked_files(zipped: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    """Controlli comuni agli archivi di lezione e ai contenitori di più ZIP."""
    files = [item for item in zipped.infolist() if not item.is_dir()]
    if len(files) > MAX_FILES or sum(item.file_size for item in files) > MAX_BYTES:
        raise TooLarge("archive_too_large", "Archivio troppo grande.")
    names = [item.filename for item in files]
    if len(names) != len({n.casefold() for n in names}):
        raise Invalid("invalid_archive", "L'archivio contiene nomi duplicati.")
    if any(any(s in ("", ".", "..") for s in name.split("/")) or "\\" in name or name.startswith("/")
           for name in names):
        raise Invalid("invalid_archive", "Percorsi non validi nell'archivio.")
    if any(stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or
           (item.file_size and item.file_size > MAX_RATIO * max(1, item.compress_size)) for item in files):
        raise Invalid("invalid_archive", "L'archivio contiene link, file cifrati o compressione sospetta.")
    return files


def group_archive_members(archive: str) -> Optional[List[str]]:
    """I nomi delle lezioni se l'archivio contiene solo ZIP; altrimenti è un export singolo.

    Si leggono solo i metadati: il worker apre una lezione alla volta, senza estrarre il
    gruppo intero né usare i nomi dell'archivio come percorsi sul disco.
    """
    with zipfile.ZipFile(archive) as zipped:
        files = [item for item in zipped.infolist() if not item.is_dir()]
        if not files or not all(item.filename.lower().endswith(".zip") for item in files):
            return None
        return [item.filename for item in _checked_files(zipped)]


def import_group_member(archive: str, member: str, **choice) -> int:
    """Ogni ZIP interno passa dall'importatore normale, inclusi manifesto e checksum."""
    with zipfile.ZipFile(archive) as zipped, tempfile.TemporaryFile() as temporary:
        with zipped.open(member) as source:
            shutil.copyfileobj(source, temporary, length=1 << 20)
        temporary.seek(0)
        return import_archive(temporary, **choice)


EXISTING_ACTIONS = ("ask", "replace", "keep")


class LessonAlreadyPresent(Conflict):
    """Nell'archivio c'è una lezione che l'utente ha già (stessa data, materia e ora):
    l'importazione si ferma e chiede se rimpiazzarla, tenerle entrambe o saltarla."""

    def __init__(self, existing: dict, incoming: dict, can_keep_both: bool):
        from datetime import date as calendar_date
        try:
            day = calendar_date.fromisoformat(existing["data"]).strftime("%d/%m/%Y")
        except ValueError:
            day = existing["data"]
        when = f"del {day}" + (f" alle {existing['ora']}" if existing.get("ora") else "")
        super().__init__("lesson_already_present",
                         f"Hai già una lezione di {existing['materia']} {when}: «{existing['titolo']}».",
                         {"existing": existing, "incoming": incoming, "can_keep_both": can_keep_both})


def _iso_day(value) -> str:
    from rt.pipeline.setup import parse_flexible_date
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parse_flexible_date(text)
    except Exception:  # noqa: BLE001 - una data illeggibile non identifica nessuna lezione
        return ""


def _identity(info: dict) -> dict:
    from rt.services.calendar_service import normalize_subject, normalize_time
    return {"data": _iso_day(info.get("data")), "materia": normalize_subject(info.get("materia")),
            "ora": normalize_time(str(info.get("ora") or "")),
            "titolo": str(info.get("titolo") or ""), "argomenti": str(info.get("argomenti") or "")}


def _archive_info(zipped: zipfile.ZipFile, name: str) -> dict:
    import yaml
    try:
        info = yaml.safe_load(zipped.read(name).decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        raise Invalid("invalid_archive", "info.yaml dell'archivio illeggibile.")
    return info if isinstance(info, dict) else {}


def _same_lesson(session, target: str, incoming: dict) -> Optional[dict]:
    """La lezione già presente che corrisponde a quella dell'archivio: prima quella con lo
    stesso nome di cartella, poi una con stessa data e materia e, se entrambe hanno l'ora,
    la stessa ora. Argomenti e fonti non contano: due studenti alla stessa lezione li
    scrivono diversi, ma la lezione è la stessa."""
    from sqlalchemy import select
    from rt.core.state import read_info_yaml
    same_folder = LessonRepository(session).get_by_path(target)
    candidates = [same_folder] if same_folder is not None else []
    if incoming["data"] and incoming["materia"]:
        candidates += [row for row in session.scalars(select(Lesson).order_by(Lesson.id)) if row is not same_folder]
    for row in candidates:
        try:
            info_file = lesson_path(row.path, "info.yaml")
            info = read_info_yaml(info_file) if fs.isfile(info_file) else {}
        except Exception:  # noqa: BLE001 - una lezione illeggibile non blocca l'import
            info = {}
        have = _identity({"data": info.get("data") or row.data, "materia": info.get("materia") or row.materia,
                          "ora": info.get("ora"), "titolo": info.get("titolo") or row.titolo,
                          "argomenti": info.get("argomenti") or row.argomenti})
        if row is not same_folder and (have["data"] != incoming["data"] or have["materia"] != incoming["materia"]
                                       or (have["ora"] and incoming["ora"] and have["ora"] != incoming["ora"])):
            continue
        return {**have, "lesson_id": row.id, "folder_name": row.folder_name,
                "titolo": have["titolo"] or row.folder_name}
    return None


def _backup_for_replace(lesson_id: int) -> str:
    """ZIP completo (stato dello studio compreso) della lezione da rimpiazzare: se la
    sostituzione si interrompe, la lezione torna com'era."""
    from rt.services.lesson_service import resolve_lesson_dir
    from rt.storage.export import ExportError, export_zip_to_tempfile
    try:
        return export_zip_to_tempfile(resolve_lesson_dir(lesson_id), "all", study=True)
    except ExportError as exc:
        raise Conflict("replace_backup_failed",
                       f"Non riesco a fare la copia di sicurezza della lezione da rimpiazzare: {exc}")


def _calendar_links(session, lesson_id: int) -> List[int]:
    from sqlalchemy import select
    from rt.db.models import CalendarEntryState
    return list(session.scalars(select(CalendarEntryState.id).where(CalendarEntryState.lesson_id == lesson_id)))


def _relink_calendar(session, state_ids: List[int], lesson_id: int) -> None:
    from sqlalchemy import update
    from rt.db.models import CalendarEntryState
    if state_ids:
        session.execute(update(CalendarEntryState).where(CalendarEntryState.id.in_(state_ids))
                        .values(lesson_id=lesson_id))


def _remove_lesson(lesson_id: int) -> None:
    from rt.services.lesson_delete_service import delete_lesson
    from rt.services.lesson_service import resolve_lesson_dir
    delete_lesson(lesson_id, resolve_lesson_dir(lesson_id))


def import_archive(archive: Union[str, BinaryIO], on_existing: str = "ask",
                   replace_id: Optional[int] = None) -> int:
    """Importa un export completo. Se la lezione c'è già (vedi _same_lesson):
    on_existing="ask" la rifiuta con LessonAlreadyPresent; "replace" sostituisce per intero
    la lezione replace_id (file, scaletta, stato dello studio), con ripristino automatico se
    qualcosa va storto; "keep" la importa accanto, se il nome della cartella è libero."""
    if on_existing not in EXISTING_ACTIONS:
        raise Invalid("invalid_decision", "Scelta non valida per una lezione già presente.")
    root = lessons_root()
    db = get_database()
    if db is None:
        raise Conflict("setup_required", "Database non disponibile: impossibile importare.")
    with zipfile.ZipFile(archive) as zipped:
        files = _checked_files(zipped)
        names = [item.filename for item in files]
        parts = [name.split("/") for name in names]
        if not parts or any(len(p) < 2 for p in parts):
            raise Invalid("invalid_archive", "Percorsi non validi nell'archivio.")
        folder = parts[0][0]
        if any(p[0] != folder for p in parts) or folder.startswith(".") or folder.endswith(" "):
            raise Invalid("invalid_archive", "L'archivio deve contenere una sola lezione.")
        manifest_name = f"{folder}/rt-export.json"
        if manifest_name not in names:
            raise Invalid("invalid_archive", "Manca il manifesto di un export completo di RT.")
        manifest = json.loads(zipped.read(manifest_name))
        if manifest.get("format") != "rt-lesson" or manifest.get("version") != 1 or manifest.get("scope") != "all":
            raise Invalid("invalid_archive", "Formato o versione dell'archivio non supportati.")
        rows = manifest.get("files")
        if not isinstance(rows, list) or len(rows) != len({row.get("path") for row in rows if isinstance(row, dict)}):
            raise Invalid("invalid_archive", "Manifesto non valido.")
        declared = {f"{folder}/{row['path']}": row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)}
        # L'export di un'anteprima aggiunge il LEGGIMI e il Markdown "(anteprima)", fuori dal manifesto.
        extras = {n for n in set(names) - set(declared) - {manifest_name}
                  if n != f"{folder}/{PREVIEW_README}" and not n.endswith(PREVIEW_SUFFIX + ".md")}
        if extras:
            raise Invalid("invalid_archive", "File non dichiarati nel manifesto.")
        if not declared or not f"{folder}/info.yaml" in declared or set(declared) - set(names):
            raise Invalid("invalid_archive", "Archivio incompleto: manca info.yaml o un file dichiarato.")
        incoming = {**_identity(_archive_info(zipped, f"{folder}/info.yaml")), "folder_name": folder}

        target = os.path.join(os.path.realpath(root), folder)
        with session_scope(db) as session:
            existing = LessonRepository(session).get_by_path(target)
            if existing is not None and existing.storage != fs.STORAGE_DB and not os.path.lexists(target):
                # Riga orfana: la cartella della lezione non esiste più. Non blocca l'import.
                from rt.services.lesson_delete_service import purge_lesson_records
                purge_lesson_records(session, existing)
                session.delete(existing)
                session.flush()
                existing = None
            folder_taken = existing is not None or os.path.lexists(target)
            existing_id = existing.id if existing is not None else None
            match = _same_lesson(session, target, incoming)
        if match is None and folder_taken:
            # Cartella con lo stesso nome ma fuori dal database: non è una lezione da rimpiazzare.
            raise Conflict("duplicate_lesson", f"La lezione {folder} esiste già.")
        replacing = None
        if match is not None:
            if on_existing == "replace" and replace_id == match["lesson_id"]:
                replacing = match
            elif not (on_existing == "keep" and not folder_taken):
                raise LessonAlreadyPresent(match, incoming, can_keep_both=not folder_taken)
            if replacing and folder_taken and existing_id != match["lesson_id"]:
                raise Conflict("duplicate_lesson", f"La lezione {folder} esiste già.")
        staging_base = work_dir()
        os.makedirs(staging_base, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rt-import-", dir=staging_base) as staging:
            for name, row in declared.items():
                item = zipped.getinfo(name)
                if item.file_size != row.get("size") or item.file_size > MAX_BYTES:
                    raise Invalid("invalid_archive", "Dimensione del file incoerente.")
                rel = name[len(folder) + 1:]
                destination = os.path.join(staging, *rel.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                digest = hashlib.sha256()
                with zipped.open(item) as source, open(destination, "wb") as output:
                    while chunk := source.read(1 << 20):
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != row.get("sha256"):
                    raise Invalid("invalid_archive", "Checksum dei file non corrispondente.")
            # La lezione da rimpiazzare si toglie solo dopo che l'archivio ha passato ogni
            # controllo, e prima se ne fa una copia completa per poterla rimettere.
            backup, links = None, []
            if replacing:
                backup = _backup_for_replace(replacing["lesson_id"])
                with session_scope(db) as session:
                    links = _calendar_links(session, replacing["lesson_id"])
                try:
                    _remove_lesson(replacing["lesson_id"])
                except BaseException:
                    os.unlink(backup)
                    raise
            created_id = None
            try:
                target = fs.create_db_lesson(target)
                with session_scope(db) as session:
                    created_id = LessonRepository(session).get_by_path(target).id
                for name in declared:
                    rel = name[len(folder) + 1:]
                    fs.copy2(os.path.join(staging, *rel.split("/")), lesson_path(target, rel))
                with session_scope(db) as session:
                    from rt.services.study_progress_service import restore_units
                    restore_units(session, created_id, manifest.get("study"))
                    _relink_calendar(session, links, created_id)
            except BaseException:
                if created_id is not None:
                    _remove_lesson(created_id)
                if backup:
                    _restore_replaced(backup, links)
                raise
            if backup:
                os.unlink(backup)
            return created_id


def _restore_replaced(backup: str, links: List[int]) -> None:
    """Rimette la lezione rimpiazzata dalla sua copia. Se nemmeno questo riesce, la copia
    resta nella cartella dei backup di RT invece di essere cancellata."""
    try:
        restored = import_archive(backup, on_existing="keep")
        with session_scope(get_database()) as session:
            _relink_calendar(session, links, restored)
    except BaseException as exc:
        from rt.core.paths import data_dir
        folder = os.path.join(data_dir(), "backups")
        os.makedirs(folder, exist_ok=True)
        kept = os.path.join(folder, "lezione-rimpiazzata-" + os.path.basename(backup))
        shutil.move(backup, kept)
        raise Conflict("replace_restore_failed",
                       f"Sostituzione non riuscita e lezione originale non ripristinata: la sua copia è in {kept}. "
                       f"Importala da lì.") from exc
    os.unlink(backup)
