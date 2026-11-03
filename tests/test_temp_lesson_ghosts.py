import os
import tempfile
import pytest

from rt.core import paths
from rt.db.engine import get_database
from rt.db.models import Lesson
from rt.db.session import session_scope
from rt.services.doctor_service import check_missing_info_lessons
from rt.services.lesson_service import ensure_indexed, list_lessons
from rt.services.subjects import list_subjects
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_ensure_indexed_ignores_temp_dir_when_data_dir_elsewhere(tmp_path, monkeypatch, rt_db):
    # Cartella dati fuori dai percorsi temp standard (simuliamo paths.data_dir che restituisce un percorso non-temp)
    fake_data_dir = "/Users/testuser/.rt"
    monkeypatch.setattr(paths, "data_dir", lambda: fake_data_dir)

    lesson_dir = str(tmp_path / "temp_lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\ntitolo: Prova\n")

    res = ensure_indexed([lesson_dir])
    # Deve ignorarla e non registrarla
    assert len(res) == 0


def test_ensure_indexed_indexes_when_data_dir_in_temp(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = str(tmp_path / "test_lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\ntitolo: Prova\ndata: 2026-09-05\n")

    res = ensure_indexed([lesson_dir])
    assert len(res) == 1
    assert os.path.realpath(lesson_dir) in res


def test_list_lessons_and_subjects_hide_folder_without_info_yaml(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)

    # 1. Lezione valida
    valid_dir = _synthetic_lesson(root, {"1.1": "Testo valido"})
    ensure_indexed([valid_dir])

    # 2. Lezione folder nel DB la cui cartella non ha info.yaml
    broken_folder = str(tmp_path / "broken_lesson")
    os.makedirs(broken_folder, exist_ok=True)
    # Nessun info.yaml

    db = get_database()
    with session_scope(db) as session:
        session.add(
            Lesson(
                path=os.path.realpath(broken_folder),
                folder_name="broken_lesson",
                storage="folder",
                materia="MATERIA FANTASMA",
                titolo="Fantasma",
            )
        )

    # list_lessons non mostra la lezione fantasma
    lessons = list_lessons()
    assert all(l["folder_name"] != "broken_lesson" for l in lessons)

    # GET /lessons via API non la mostra
    res = api_client.get("/api/v1/lessons")
    assert res.status_code == 200
    assert all(l["folder_name"] != "broken_lesson" for l in res.json())

    # list_subjects non include MATERIA FANTASMA
    subjects = list_subjects()
    assert all(s["nome"] != "MATERIA FANTASMA" for s in subjects)

    # doctor rileva la cartella mancante o senza info.yaml
    check = check_missing_info_lessons()
    assert check.status == "warn"
    assert "1 (" in check.message
    assert os.path.realpath(broken_folder) in check.message


def test_folder_lesson_with_info_in_state_dir_is_kept(tmp_path, monkeypatch, rt_db):
    """Layout nuovo: info.yaml in _state/ non rende la lezione un fantasma (elenco, materie, doctor)."""
    from rt.services.lesson_service import indexed_lesson_ids
    isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = tmp_path / "nuova"
    (lesson_dir / "_state").mkdir(parents=True)
    (lesson_dir / "_state" / "info.yaml").write_text("materia: MATERIA STATE\n", encoding="utf-8")
    with session_scope(get_database()) as session:
        session.add(Lesson(path=os.path.realpath(lesson_dir), folder_name="nuova", storage="folder",
                           materia="MATERIA STATE", titolo="Nuova"))
    assert os.path.realpath(lesson_dir) in indexed_lesson_ids()
    assert any(s["nome"] == "MATERIA STATE" for s in list_subjects())
    assert check_missing_info_lessons().status == "ok"
