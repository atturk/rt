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
        if details['argomenti']:
            message += f" con argomenti «{details['argomenti']}»"
        super().__init__('lesson_exists', message, details)


def lesson_folder(date, materia, argomenti=''):
    day = parse_flexible_date(date)
    subject = sanitize_filename_part((materia or '').strip().upper())
    topic = sanitize_filename_part((argomenti or '').strip())
    return f'[{day}] {subject}' + (f' - {topic}' if topic else '')


def find_lesson_conflict(date, materia, argomenti, dest_dir):
    path = os.path.join(dest_dir, lesson_folder(date, materia, argomenti))
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
            'argomenti': info.get('argomenti') or argomenti or ''}


def require_no_lesson_conflict(date, materia, argomenti, dest_dir):
    conflict = find_lesson_conflict(date, materia, argomenti, dest_dir)
    if conflict:
        raise LessonConflict(conflict)


def create_lesson_directory(date, materia, argomenti, dest_dir):
    """Riserva il nome sotto un lock breve, anche con due worker contemporanei."""
    import hashlib
    from rt.core.filelock import file_lock
    from rt.core.paths import data_dir
    folder = lesson_folder(date, materia, argomenti)
    path = os.path.join(dest_dir, folder)
    digest = hashlib.sha256(os.path.realpath(path).encode('utf-8')).hexdigest()
    with file_lock(os.path.join(data_dir(), 'locks', f'new-lesson-{digest}.lock')):
        require_no_lesson_conflict(date, materia, argomenti, dest_dir)
        if fs.new_lessons_use_db():
            return fs.create_db_lesson(path)
        fs.makedirs(path, exist_ok=False)
        return path
