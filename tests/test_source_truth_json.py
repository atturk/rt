"""
tests/test_source_truth_json.py
Verifica rigorosa della priorità e sovranità di 'trascritto grezzo.json'
rispetto a 'trascritto grezzo.md' come Source of Truth temporale e semantica.
"""

import os
import json
import pytest

from rt.pipeline.prepare import run_prepare
from rt.core.models import SegmentsData
from rt.core.lesson_paths import lesson_path


def test_json_is_authoritative_over_markdown(tmp_path):
    """
    Dimostra che quando 'trascritto grezzo.json' è presente e valido:
    1. 'segments.json' viene derivato al 100% dal JSON;
    2. Modifiche arbitrarie a 'trascritto grezzo.md' (testo, timestamp falsificati, righe cancellate)
       NON alterano minimamente i timestamp, i confini di segmento o i testi in 'segments.json'.
    """
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - Source Of Truth")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: '[2026-09-05] TEST - Source Of Truth'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    # 1. Trascritto grezzo JSON autorevole
    authoritative_segments = [
        {"id": "s1", "start": 1000, "end": 5000, "text": "Segmento 1 originale dal microfono."},
        {"id": "s2", "start": 5000, "end": 12000, "text": "Segmento 2 originale con timestamp precisi."}
    ]
    json_path = os.path.join(lesson_dir, "trascritto grezzo.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"segments": authoritative_segments}, f)

    # 2. Trascritto grezzo Markdown con testo alterato e timestamp completamente sballati
    md_content = """---
data: '2026-09-05'
materia: BIOCHIMICA
---

[99:99] Testo markdown completamente falsificato che non deve entrare in segments.json.
[88:88] Altra riga spuria.
"""
    md_path = os.path.join(lesson_dir, "trascritto grezzo.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Eseguiamo run_prepare
    prep_res = run_prepare(lesson_dir)
    assert prep_res["status"] == "prepared"

    # Leggiamo il segments.json generato
    seg_file = lesson_path(lesson_dir, "segments.json")
    assert os.path.isfile(seg_file)
    with open(seg_file, "r", encoding="utf-8") as f:
        seg_data = json.load(f)

    # I segmenti devono riflettere ESCLUSIVAMENTE il JSON
    assert len(seg_data["segments"]) == 2
    assert seg_data["segments"][0]["start_seconds"] == 1.0
    assert seg_data["segments"][0]["end_seconds"] == 5.0
    assert seg_data["segments"][0]["text_raw"] == "Segmento 1 originale dal microfono."
    assert seg_data["segments"][1]["start_seconds"] == 5.0
    assert seg_data["segments"][1]["end_seconds"] == 12.0
    assert seg_data["segments"][1]["text_raw"] == "Segmento 2 originale con timestamp precisi."


def test_prepare_stops_on_corrupt_json(tmp_path):
    """
    Verifica che se 'trascritto grezzo.json' è corrotto o non è un JSON valido,
    run_prepare solleva un errore esplicito e non tenta un fallback silenzioso o corrotto.
    """
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - Corrupt JSON")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: '[2026-09-05] TEST - Corrupt JSON'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    json_path = os.path.join(lesson_dir, "trascritto grezzo.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write("{corrupt json file without close brackets...")

    with pytest.raises((ValueError, json.JSONDecodeError)):
        run_prepare(lesson_dir)


def test_divergence_warning_between_json_and_markdown(tmp_path, capsys):
    """
    Verifica che venga emesso un warning diagnostico se 'trascritto grezzo.md' ha un numero
    di segmenti divergente rispetto al JSON autorevole.
    """
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - Divergence Warning")
    os.makedirs(lesson_dir, exist_ok=True)

    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("fase_corrente: setup_completato\nstato: setup_completato\n")

    json_path = os.path.join(lesson_dir, "trascritto grezzo.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"segments": [{"id": "s1", "start": 0, "end": 2000, "text": "Un solo segmento."}]}, f)

    md_path = os.path.join(lesson_dir, "trascritto grezzo.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("*00:00-00:02*\nSeg 1\n\n*00:02-00:04*\nSeg 2\n\n*00:04-00:06*\nSeg 3\n")

    run_prepare(lesson_dir)
    captured = capsys.readouterr().out

    assert "AVVISO COERENZA ASR" in captured or "divergenza" in captured.lower()
