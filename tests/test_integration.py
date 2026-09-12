"""
Integration test per l'intera pipeline RT end-to-end.
Simula:
ASR source (JSON / MD) -> prepare -> outline -> rewrite -> review -> review_ledger -> build
Verifica conformità totale dei timestamp, provenance e assenza di regressioni.
"""

import os
import json
import pytest
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.rewrite import run_rewrite, load_draft
from rt.pipeline.review import run_review, load_science_issues
from rt.pipeline.ledger import record_decision, load_ledger
from rt.pipeline.build import run_build
from rt.core.segments import load_segments_json
from rt.core.timestamp import format_timestamp


@pytest.fixture
def temp_lesson_dir(tmp_path):
    lesson_dir = str(tmp_path / "[2026-09-05] BIOCHIMICA - Test Lezione")
    os.makedirs(lesson_dir, exist_ok=True)
    
    # 1. info.yaml
    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi e beta-ossidazione
cartella: '[2026-09-05] BIOCHIMICA - Test Lezione'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)
        
    # 2. trascritto grezzo.md
    transcript_content = """---
data: '2026-09-05'
materia: BIOCHIMICA
---

*00:02*
Allora ieri abbiamo visto tutti questione, abbiamo visto

*00:14*
I lipidi sono depositati nel tessuto adiposo.

*00:22*
Quando c'è necessità di degradarli entra in gioco la lipasi.

*00:30*
licorolo finansi converte il glicerolo libero in glicerolo 3 fosfato.

*00:45-00:55*
Nei muscoli lisci ci sono sarcomeri per estrarre energia.

*01:00-01:10*
La via prosegue con la beta-ossidazione mitocondriale degli acidi grassi.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)
        
    return lesson_dir


def test_full_pipeline_end_to_end(temp_lesson_dir):
    lesson_dir = temp_lesson_dir
    
    # 1. PREPARE
    prep_res = run_prepare(lesson_dir)
    assert prep_res["status"] == "prepared"
    assert prep_res["segment_count"] == 6
    assert os.path.isfile(prep_res["segments_json"])
    assert os.path.isfile(prep_res["transcript_normalized_md"])
    
    segments_data = load_segments_json(prep_res["segments_json"])
    assert len(segments_data.segments) == 6
    assert segments_data.segments[0].id == "seg_000001"
    assert segments_data.segments[0].start_seconds == 2.0
    assert segments_data.segments[0].start_formatted == "00:02"
    
    # 2. OUTLINE (mock deterministico)
    out_res = run_outline(lesson_dir, force_mock=True)
    assert out_res["status"] == "outline_validated"
    assert os.path.isfile(out_res["outline_path"])
    
    outline = load_outline(lesson_dir)
    assert len(outline.macro_sections) >= 1
    unit1 = outline.macro_sections[0].units[0]
    assert unit1.start_segment_id == "seg_000001"
    
    # 3. REWRITE (mock deterministico)
    rew_res = run_rewrite(lesson_dir, force_mock=True)
    assert rew_res["status"] == "draft_validated"
    
    draft = load_draft(lesson_dir)
    assert len(draft.units) >= 1
    # Verifica che la provenance (source_segment_ids) sia presente e non vuota
    assert len(draft.units[0].source_segment_ids) > 0
    assert "seg_000001" in draft.units[0].source_segment_ids
    
    # 4. REVIEW
    rev_res = run_review(lesson_dir, force_mock=True)
    assert rev_res["status"] == "review_completed"
    assert os.path.isfile(rev_res["issues_path"])
    
    # 5. DECISION LEDGER (simula approvazione umana)
    record_decision(
        lesson_dir=lesson_dir,
        issue_id="sci_000001",
        decision="accepted",
        resolved_text="glicerolo chinasi",
        resolved_by="human_test"
    )
    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) >= 1
    
    # 6. BUILD (deterministico)
    build_res = run_build(lesson_dir, rename_folder=False)
    assert build_res["status"] == "completed"
    assert os.path.isfile(build_res["pre_elaborato"])
    assert os.path.isfile(build_res["rielaborato"])
    assert os.path.isfile(build_res["errori_concettuali"])
    assert os.path.isfile(build_res["problemi_scientifici"])
    
    # 7. VERIFICA RIGOROSA DEL REQUISITO TIMESTAMP SUI FILE GENERATI
    with open(build_res["rielaborato"], "r", encoding="utf-8") as f:
        rielab_text = f.read()
        
    expected_ts = format_timestamp(segments_data.segments[0].start_seconds) # "00:02"
    assert f"### {unit1.id} {unit1.title}\n{expected_ts}" in rielab_text
    
    # 8. IDEMPOTENZA DEL BUILD: una seconda esecuzione non corrompe nulla
    build_res_2 = run_build(lesson_dir, rename_folder=False)
    assert build_res_2["status"] == "completed"
    with open(build_res["rielaborato"], "r", encoding="utf-8") as f:
        rielab_text_2 = f.read()
    assert rielab_text == rielab_text_2

