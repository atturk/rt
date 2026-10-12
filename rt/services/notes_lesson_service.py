"""Creazione di lezioni solo da appunti, senza segnaposto audio."""
import os
from datetime import datetime, timezone

import yaml

from rt.core.lesson_paths import lesson_path
from rt.core.sources import add_source
from rt.pipeline.setup import parse_flexible_date, sanitize_filename_part
from rt.storage import fs


def create_notes_lesson(text, *, date, materia, argomenti="", docente="", ora="", dest_dir):
    if not text or not text.strip():
        raise ValueError("Inserisci il testo degli appunti")
    date = parse_flexible_date(date)
    materia = sanitize_filename_part(materia.strip())
    if not materia:
        raise ValueError("Indica la materia")
    suffix = sanitize_filename_part(argomenti.strip())
    folder = f"[{date}] {materia}" + (f" - {suffix}" if suffix else "")
    lesson_dir = os.path.join(dest_dir, folder)
    if fs.isdir(lesson_dir):
        raise ValueError("Esiste già una lezione con questi metadati")
    if fs.new_lessons_use_db():
        lesson_dir = fs.create_db_lesson(lesson_dir)
    else:
        fs.makedirs(lesson_dir, exist_ok=False)
    info = {"data": date, "materia": materia, "argomenti": argomenti, "docente": docente,
            "ora": ora, "cartella": folder, "file_audio": "",
            "creato_il": datetime.now(timezone.utc).isoformat(),
            "fase_corrente": "setup_completato", "stato": "pronto_per_rielaborazione"}
    with fs.open(lesson_path(lesson_dir, "info.yaml"), "w", encoding="utf-8") as stream:
        yaml.safe_dump(info, stream, allow_unicode=True, sort_keys=False)
    add_source(lesson_dir, "appunti", "appunti.txt", text.encode("utf-8"))
    from rt.db.sync import dual_write_lesson
    dual_write_lesson(lesson_dir)
    return lesson_dir
