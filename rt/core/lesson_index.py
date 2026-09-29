"""
rt.core.lesson_index
Scansione ed indicizzazione delle lezioni presenti in lessons_root.
"""
from dataclasses import dataclass
from typing import List
import os
from rt.core.state import read_info_yaml
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


@dataclass
class LessonEntry:
    lesson_dir: str
    folder_name: str
    data: str
    materia: str
    titolo: str
    argomenti: str


def scan_lessons(lessons_root: str) -> List[LessonEntry]:
    """Enumera le sottocartelle DIRETTE di lessons_root (struttura piatta, nessun
    annidamento) con un info.yaml leggibile. Cartelle senza info.yaml valido sono
    ignorate silenziosamente."""
    entries = []
    if not lessons_root:
        return entries
    for name in sorted(fs.root_entries(lessons_root)):
        full = os.path.join(lessons_root, name)
        if not fs.isdir(full):
            continue
        yaml_path = lesson_path(full, "info.yaml")
        if not fs.isfile(yaml_path):
            continue
        try:
            info = read_info_yaml(yaml_path)
        except Exception:
            continue
        entries.append(LessonEntry(
            lesson_dir=full,
            folder_name=name,
            data=str(info.get("data", "")),
            materia=str(info.get("materia", "")).strip().upper(),
            titolo=str(info.get("titolo", "")),
            argomenti=str(info.get("argomenti", "")),
        ))
    return entries


def database_lessons() -> List[LessonEntry]:
    """Elenco canonico delle lezioni dal DB, senza scansione della cartella dati."""
    from rt.db.engine import get_database
    from rt.db.repositories import LessonRepository
    from rt.db.session import read_scope

    db = get_database()
    if db is None:
        return []
    with read_scope(db) as session:
        rows = LessonRepository(session).list_all()
        # Stesso filtro della web app (lesson_service.indexed_lesson_ids): una riga a cartelle
        # la cui cartella non esiste più non è una lezione da proporre.
        return [LessonEntry(lesson_dir=row.path, folder_name=row.folder_name, data=row.data,
                            materia=(row.materia or "").strip().upper(), titolo=row.titolo,
                            argomenti=row.argomenti) for row in rows
                if row.storage == fs.STORAGE_DB or os.path.isdir(row.path)]


def filter_by_materia(entries: List[LessonEntry], materia_upper: str) -> List[LessonEntry]:
    return [e for e in entries if e.materia == materia_upper]


def filter_unmapped(entries: List[LessonEntry], topics: dict) -> List[LessonEntry]:
    mapped = set((topics or {}).keys())
    return [e for e in entries if e.materia not in mapped]


def filter_by_date(entries: List[LessonEntry], iso_date: str) -> List[LessonEntry]:
    return [e for e in entries if e.data == iso_date]


def filter_by_keyword(entries: List[LessonEntry], keyword: str) -> List[LessonEntry]:
    kw = keyword.strip().lower()
    if not kw:
        return list(entries)
    return [e for e in entries if kw in e.materia.lower() or kw in e.titolo.lower()
            or kw in e.argomenti.lower() or kw in e.folder_name.lower()]
