"""
tests/test_build_lessons_root.py
Test per il Task 69: spostamento automatico della cartella lezione in lessons_root
alla fine della fase di build.
"""

import os
import json
import pytest
from unittest.mock import patch

from rt.core.config import RTConfig, TelegramRuntimeConfig
from rt.core.lesson_paths import lesson_path
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.review import run_review, get_science_issues_path
from rt.pipeline.build import run_build
from rt.pipeline.ledger import record_decision


def _create_synthetic_prepared_lesson(base_dir: str, folder_name: str = "raw_lesson") -> str:
    lesson_dir = os.path.join(base_dir, folder_name)
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = f"""data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi e beta-ossidazione
cartella: '{folder_name}'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    raw_mw_json = {
        "segments": [
            {"id": "s1", "start": 0, "end": 10000, "text": "Introduzione ai trigliceridi e acidi grassi."},
            {"id": "s2", "start": 10000, "end": 20000, "text": "La lipolisi e il rilascio di glicerolo."},
            {"id": "s3", "start": 20000, "end": 35000, "text": "Attivazione degli acidi grassi con acil-CoA sintetasi."},
            {"id": "s4", "start": 35000, "end": 50000, "text": "Ruolo della carnitina palmitoil transferasi 1 e 2."},
            {"id": "s5", "start": 50000, "end": 65000, "text": "Le quattro reazioni cicliche della beta-ossidazione."},
            {"id": "s6", "start": 65000, "end": 80000, "text": "Resa energetica in ATP dell'acido palmitico."}
        ]
    }
    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump(raw_mw_json, f, indent=2)

    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)
    run_review(lesson_dir, force_mock=True)

    sci_path = get_science_issues_path(lesson_dir)
    with open(sci_path, "r", encoding="utf-8") as f:
        sci_data = json.load(f)
    for iss in sci_data:
        record_decision(lesson_dir, iss["id"], "accetta", notes="auto test accept")

    return lesson_dir


def test_build_moves_to_lessons_root(tmp_path):
    audio_dir = str(tmp_path / "audio_source")
    lessons_root = str(tmp_path / "final_lessons")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(lessons_root, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(audio_dir, "lesson_1")
    assert os.path.isdir(lesson_dir)

    mock_cfg = RTConfig(
        telegram=TelegramRuntimeConfig(lessons_root=lessons_root)
    )

    with patch("rt.core.config.load_config", return_value=mock_cfg):
        res = run_build(lesson_dir, rename_folder=False)

    expected_path = os.path.join(lessons_root, "lesson_1")
    assert not os.path.exists(lesson_dir)
    assert os.path.isdir(expected_path)
    assert res["lesson_dir"] == expected_path
    assert os.path.isfile(res["rielaborato"])
    assert res["rielaborato"] == lesson_path(expected_path, "rielaborato.md")


def test_build_without_lessons_root(tmp_path):
    audio_dir = str(tmp_path / "audio_source")
    os.makedirs(audio_dir, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(audio_dir, "lesson_no_root")
    mock_cfg = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=None))

    with patch("rt.core.config.load_config", return_value=mock_cfg):
        res = run_build(lesson_dir, rename_folder=False)

    assert os.path.isdir(lesson_dir)
    assert res["lesson_dir"] == lesson_dir


def test_build_rename_and_move_to_lessons_root(tmp_path):
    audio_dir = str(tmp_path / "audio_source")
    lessons_root = str(tmp_path / "final_lessons")
    os.makedirs(audio_dir, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(audio_dir, "raw_folder")
    mock_cfg = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=lessons_root))

    with patch("rt.core.config.load_config", return_value=mock_cfg):
        res = run_build(lesson_dir, rename_folder=True)

    # Il nome della cartella rinominata riflette data, materia, titolo outline mock
    final_dir = res["lesson_dir"]
    assert os.path.dirname(os.path.abspath(final_dir)) == os.path.abspath(lessons_root)
    assert not os.path.exists(lesson_dir)
    assert os.path.isdir(final_dir)
    assert "[" in os.path.basename(final_dir)
    assert "BIOCHIMICA" in os.path.basename(final_dir)


def test_build_collision_in_lessons_root(tmp_path, capsys):
    audio_dir = str(tmp_path / "audio_source")
    lessons_root = str(tmp_path / "final_lessons")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(lessons_root, exist_ok=True)

    # Creiamo già una cartella con lo stesso nome in lessons_root
    existing_dest = os.path.join(lessons_root, "colliding_lesson")
    os.makedirs(existing_dest, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(audio_dir, "colliding_lesson")
    mock_cfg = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=lessons_root))

    with patch("rt.core.config.load_config", return_value=mock_cfg):
        res = run_build(lesson_dir, rename_folder=False)

    # La cartella NON deve essere spostata, resta in audio_dir
    assert os.path.isdir(lesson_dir)
    assert res["lesson_dir"] == lesson_dir
    captured = capsys.readouterr()
    assert "Impossibile spostare la cartella" in captured.out


def test_build_already_in_lessons_root(tmp_path):
    lessons_root = str(tmp_path / "final_lessons")
    os.makedirs(lessons_root, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(lessons_root, "already_in_root")
    mock_cfg = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=lessons_root))

    with patch("rt.core.config.load_config", return_value=mock_cfg):
        # Prima build
        res1 = run_build(lesson_dir, rename_folder=False)
        assert res1["lesson_dir"] == lesson_dir
        assert os.path.isdir(lesson_dir)

        # Rebuild forzata
        res2 = run_build(lesson_dir, force=True, rename_folder=False)
        assert res2["lesson_dir"] == lesson_dir
        assert os.path.isdir(lesson_dir)


def test_build_skip_moves_if_not_in_lessons_root(tmp_path):
    audio_dir = str(tmp_path / "audio_source")
    lessons_root = str(tmp_path / "final_lessons")
    os.makedirs(audio_dir, exist_ok=True)

    lesson_dir = _create_synthetic_prepared_lesson(audio_dir, "skip_lesson")
    # Eseguiamo la build SENZA lessons_root per completare la fase
    mock_cfg_none = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=None))
    with patch("rt.core.config.load_config", return_value=mock_cfg_none):
        res1 = run_build(lesson_dir, rename_folder=False)
        assert res1["action"] == "RUN"
        assert res1["lesson_dir"] == lesson_dir

    # Ora eseguiamo di nuovo senza force ma CON lessons_root configurato
    mock_cfg_root = RTConfig(telegram=TelegramRuntimeConfig(lessons_root=lessons_root))
    with patch("rt.core.config.load_config", return_value=mock_cfg_root):
        res2 = run_build(lesson_dir, force=False, rename_folder=False)
        assert res2["action"] == "SKIP"
        expected_path = os.path.join(lessons_root, "skip_lesson")
        assert res2["lesson_dir"] == expected_path
        assert not os.path.exists(lesson_dir)
        assert os.path.isdir(expected_path)
