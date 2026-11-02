"""Identità di una lezione, condivisa da importazione e controllo prima della coda."""
import os
from datetime import date as calendar_date

from rt.pipeline.setup import parse_flexible_date, sanitize_filename_part
from rt.services.errors import Conflict
from rt.storage import fs


class LessonConflict(Conflict, ValueError):
    def __init__(self, details):
        day = calendar_date.fromisoformat(details['data']).strftime('%d/%m/%Y')
        message = f"Esiste già una lezione del {day} di {details['materia']}"
        if details.get('ora'):
            message += f" alle {details['ora']}"
        super().__init__('lesson_exists', message, details)


def _clean_time(ora):
    return (ora or '').strip()


def lesson_folder(date, materia, ora=''):
    """Nome della lezione: data, materia e, se c'è, l'ora. Gli argomenti non ne fanno parte:
    li genera l'IA e due persone alla stessa lezione li scriverebbero diversi."""
    day = parse_flexible_date(date)
    subject = sanitize_filename_part((materia or '').strip().upper())
    time = _clean_time(ora).replace(':', '.')
    return f'[{day}] {subject}' + (f' - ore {time}' if time else '')


def numbered_folder(folder, n):
    return folder if n == 1 else f'{folder} ({n})'


def free_lesson_path(dest_dir, folder, reusable=None):
    """Senza l'ora due lezioni della stessa materia nello stesso giorno sono lezioni diverse:
    la seconda prende "(2)", la terza "(3)" e così via. `reusable` accetta una cartella già
    presente che si può riprendere (un import interrotto)."""
    n = 1
    while True:
        path = os.path.join(dest_dir, numbered_folder(folder, n))
        if not fs.isdir(path) or (reusable is not None and reusable(path)):
            return path
        n += 1


def find_lesson_conflict(date, materia, ora, dest_dir):
    """Con l'ora, stessa data, materia e ora sono la stessa lezione. Senza ora non c'è
    conflitto: la nuova lezione prende un numero."""
    if not _clean_time(ora):
        return None
    path = os.path.join(dest_dir, lesson_folder(date, materia, ora))
    if not fs.isdir(path):
        return None
    from rt.core.state import read_info_yaml
    from rt.core.lesson_paths import lesson_path
    from rt.db.engine import get_database
    from rt.services.lesson_service import lesson_id_for_dir
    info = read_info_yaml(lesson_path(path, 'info.yaml')) if fs.isfile(lesson_path(path, 'info.yaml')) else {}
    return {'lesson_id': lesson_id_for_dir(path) if get_database() else None,
            'titolo': info.get('titolo') or os.path.basename(path),
            'data': str(info.get('data') or parse_flexible_date(date)),
            'materia': info.get('materia') or materia.strip().upper(),
            'ora': str(info.get('ora') or _clean_time(ora))}


def require_no_lesson_conflict(date, materia, ora, dest_dir):
    conflict = find_lesson_conflict(date, materia, ora, dest_dir)
    if conflict:
        raise LessonConflict(conflict)


def create_lesson_directory(date, materia, ora, dest_dir):
    """Riserva il nome sotto un lock breve, anche con due worker contemporanei."""
    import hashlib
    from rt.core.filelock import file_lock
    from rt.core.paths import data_dir
    folder = lesson_folder(date, materia, ora)
    digest = hashlib.sha256(os.path.realpath(os.path.join(dest_dir, folder)).encode('utf-8')).hexdigest()
    with file_lock(os.path.join(data_dir(), 'locks', f'new-lesson-{digest}.lock')):
        require_no_lesson_conflict(date, materia, ora, dest_dir)
        path = free_lesson_path(dest_dir, folder)
        if fs.new_lessons_use_db():
            return fs.create_db_lesson(path)
        fs.makedirs(path, exist_ok=False)
        return path


def lesson_with_audio(sha: str) -> dict | None:
    """Cerca se esiste già una lezione con questo audio (confrontando l'impronta sha256).
    Ritorna {'lesson_id': ..., 'titolo': ..., 'data': ...} oppure None."""
    if not sha:
        return None
    from rt.core.archive import find
    from rt.core.lesson_paths import lesson_path
    from rt.core.sources import load_sources
    from rt.core.state import read_info_yaml
    from rt.db.engine import get_database
    from rt.services.lesson_service import indexed_lesson_ids, lessons_root
    from rt.storage import fs

    target_shas = {sha}
    try:
        archived = find(sha)
        if archived and archived.get("impronta"):
            target_shas.add(archived["impronta"])
    except Exception:
        pass

    lesson_map = {}
    if get_database():
        try:
            lesson_map = indexed_lesson_ids()
        except Exception:
            lesson_map = {}
    root = lessons_root()
    if fs.isdir(root):
        for d in fs.listdir(root):
            if d.startswith("."):
                continue
            p = os.path.join(root, d)
            if fs.isdir(p) and p not in lesson_map:
                lesson_map[p] = None

    for path, lesson_id in lesson_map.items():
        try:
            sources = load_sources(path, readonly=True)
            for s in sources:
                if s.tipo == "audio" and s.impronta in target_shas and not s.rimossa_il:
                    info = read_info_yaml(lesson_path(path, "info.yaml"))
                    return {
                        "lesson_id": lesson_id,
                        "titolo": info.get("titolo") or os.path.basename(path),
                        "data": str(info.get("data") or ""),
                    }
        except Exception:
            continue
    return None

