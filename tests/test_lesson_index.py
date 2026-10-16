import os
from rt.core.lesson_index import (
    scan_lessons,
    filter_by_materia,
    filter_unmapped,
    filter_by_date,
    filter_by_keyword,
)


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


