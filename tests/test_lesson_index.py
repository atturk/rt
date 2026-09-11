import os
import pytest
from rt.core.lesson_index import (
    LessonEntry,
    scan_lessons,
    filter_by_materia,
    filter_unmapped,
    filter_by_date,
    filter_by_keyword,
)
from rt.telegram.lesson_query import resolve_recall_query, MAX_INLINE_DISAMBIGUATION


def _create_fake_lesson(root_dir, folder_name, materia, date, titolo, argomenti):
    lesson_dir = os.path.join(root_dir, folder_name)
    os.makedirs(lesson_dir, exist_ok=True)
    info_content = f"""materia: {materia}
data: '{date}'
titolo: '{titolo}'
argomenti: '{argomenti}'
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)
    return lesson_dir


def test_scan_lessons_and_filters(tmp_path):
    root = str(tmp_path)
    _create_fake_lesson(root, "2026-03-10_biochimica_lipidi", "BIOCHIMICA", "2026-03-10", "Lipidi e membrane", "Lipidi, Colesterolo")
    _create_fake_lesson(root, "2026-03-11_biochimica_enzimi", "BIOCHIMICA", "2026-03-11", "Cinetica enzimatica", "Enzimi")
    _create_fake_lesson(root, "2026-03-12_anatomia_cuore", "ANATOMIA", "2026-03-12", "Sistema cardiocircolatorio", "Cuore")
    _create_fake_lesson(root, "2026-03-13_filosofia_etica", "FILOSOFIA", "2026-03-13", "Etica Nicomachea", "Aristotele")

    # Cartella senza info.yaml (deve essere ignorata)
    os.makedirs(os.path.join(root, "empty_dir"), exist_ok=True)

    entries = scan_lessons(root)
    assert len(entries) == 4

    # Test filter_by_materia
    bio = filter_by_materia(entries, "BIOCHIMICA")
    assert len(bio) == 2
    assert {e.folder_name for e in bio} == {"2026-03-10_biochimica_lipidi", "2026-03-11_biochimica_enzimi"}

    # Test filter_unmapped
    topics = {"BIOCHIMICA": 10, "ANATOMIA": 20}
    unmapped = filter_unmapped(entries, topics)
    assert len(unmapped) == 1
    assert unmapped[0].materia == "FILOSOFIA"

    # Test filter_by_date
    d10 = filter_by_date(entries, "2026-03-10")
    assert len(d10) == 1
    assert d10[0].titolo == "Lipidi e membrane"

    # Test filter_by_keyword
    kw_enzimi = filter_by_keyword(entries, "enzimi")
    assert len(kw_enzimi) == 1
    assert kw_enzimi[0].folder_name == "2026-03-11_biochimica_enzimi"

    kw_cuore = filter_by_keyword(entries, "Cuore")
    assert len(kw_cuore) == 1
    assert kw_cuore[0].materia == "ANATOMIA"


def test_resolve_recall_query(tmp_path):
    root = str(tmp_path)
    _create_fake_lesson(root, "2026-03-10_biochimica_lipidi", "BIOCHIMICA", "2026-03-10", "Lipidi", "Lipidi e Colesterolo - introduzione")
    _create_fake_lesson(root, "2026-03-10_biochimica_colesterolo", "BIOCHIMICA", "2026-03-10", "Biosintesi Colesterolo", "Colesterolo")
    _create_fake_lesson(root, "2026-03-11_biochimica_enzimi", "BIOCHIMICA", "2026-03-11", "Enzimi", "Cinetica")

    entries = scan_lessons(root)

    # 1. Query per data flessibile ("10 marzo 2026") -> mode="date", 2 match
    mode, matches = resolve_recall_query(entries, "10 marzo 2026")
    assert mode == "date"
    assert len(matches) == 2

    # 2. Query per keyword ("enzimi") -> mode="keyword", 1 match
    mode, matches = resolve_recall_query(entries, "enzimi")
    assert mode == "keyword"
    assert len(matches) == 1
    assert matches[0].folder_name == "2026-03-11_biochimica_enzimi"

    # 3. Query composta ("10-03-2026 - Lipidi") -> mode="date_and_keyword", 1 match
    mode, matches = resolve_recall_query(entries, "10-03-2026 - Lipidi")
    assert mode == "date_and_keyword"
    assert len(matches) == 1
    assert matches[0].folder_name == "2026-03-10_biochimica_lipidi"

    # 4. Caso limite: query che sembra data ma non lo è ("99-99-9999") -> fallback a keyword
    mode, matches = resolve_recall_query(entries, "99-99-9999")
    assert mode == "keyword"
    assert len(matches) == 0

    # 5. Caso limite: data valida senza risultati ("2026-12-31") -> mode="date", 0 match
    mode, matches = resolve_recall_query(entries, "2026-12-31")
    assert mode == "date"
    assert len(matches) == 0

    # 6. Caso limite: keyword che contiene letteralmente " - " senza data valida ("non_data - parola") -> mode="keyword"
    mode, matches = resolve_recall_query(entries, "non_data - parola")
    assert mode == "keyword"
