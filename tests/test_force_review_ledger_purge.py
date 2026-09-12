"""
tests/test_force_review_ledger_purge.py
Test di accettazione per l'invalidazione delle decisioni nel ledger quando viene usato --force:
- purge_decisions_by_prefix rimuove solo le issue con prefisso specificato
- --force su review-asr rigenera e rende pendenti le nuove issue ASR senza toccare sci_
- --force su review-science rigenera e rende pendenti le nuove issue Science senza toccare asr_
- percorso non-force (idempotente) non altera il ledger
"""

import os
import json
import pytest

from rt.pipeline.ledger import (
    load_ledger,
    save_ledger,
    record_decision,
    get_pending_issues,
    purge_decisions_by_prefix,
)
from rt.pipeline.ledger import (
    load_ledger,
    save_ledger,
    record_decision,
    get_pending_issues,
    purge_decisions_by_prefix,
)
from rt.pipeline.review import run_review, save_science_issues
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    SegmentsData, Segment, Draft, DraftUnit
)
from rt.core.manifest import init_or_update_manifest


from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline
from rt.pipeline.rewrite import run_rewrite
from rt.core.idempotency import compute_source_fingerprint, compute_file_sha256, record_phase_fingerprint


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    info_content = """data: '2026-09-09'
materia: BIOCHIMICA
argomenti: Test Purge
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    transcript_content = """---
data: '2026-09-09'
materia: BIOCHIMICA
---

*00:02*
I lipidi sono depositati nel tessuto adiposo.

*00:14*
licorolo finansi converte il glicerolo libero in glicerolo 3 fosfato.

*00:25*
Nei muscoli lisci ci sono sarcomeri per estrarre energia.
"""
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(transcript_content)

    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="L1",
        date="2026-09-09",
        subject="BIOCHIMICA",
        current_state="setup_completato",
        audio_file="audio.mp3",
    )

    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)


def test_purge_decisions_by_prefix_unit(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    record_decision(lesson_dir, "old_000001", "accepted", resolved_text="corr1")
    record_decision(lesson_dir, "old_000002", "rejected", resolved_text="orig2")
    record_decision(lesson_dir, "sci_000001", "accepted", resolved_text="fix1")

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 3

    # Purga solo old_
    removed = purge_decisions_by_prefix(lesson_dir, "old_")
    assert removed == 2

    ledger_after = load_ledger(lesson_dir)
    assert len(ledger_after.decisions) == 1
    assert ledger_after.decisions[0].issue_id == "sci_000001"

    # Purga prefisso inesistente -> 0
    assert purge_decisions_by_prefix(lesson_dir, "nonexistent_") == 0


def test_force_review_purges_and_resets_pending_issues(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)

    # 1. Prima esecuzione mock di review
    res1 = run_review(lesson_dir, force=True, force_mock=True)
    assert res1["status"] == "review_completed"

    _, pending_sci = get_pending_issues(lesson_dir)
    assert len(pending_sci) > 0

    # 2. Decidi tutte le issue Science pendenti
    for iss in pending_sci:
        record_decision(lesson_dir, iss.id, "accepted", resolved_text=iss.suggested_fix)

    # Aggiungi anche una decisione custom con prefisso diverso
    record_decision(lesson_dir, "custom_000001", "accepted", resolved_text="cand1")

    # Verifica che ora Science sia 0 pendenti
    _, pending_sci_after = get_pending_issues(lesson_dir)
    assert len(pending_sci_after) == 0

    # 3. Riesegui con force=False (idempotente) -> SKIP e 0 pendenti
    res_skip = run_review(lesson_dir, force=False, force_mock=True)
    assert res_skip["action"] == "SKIP"
    _, pending_sci_skip = get_pending_issues(lesson_dir)
    assert len(pending_sci_skip) == 0

    # 4. Riesegui con force=True -> rigenera e purga le vecchie decisioni Science
    res_force = run_review(lesson_dir, force=True, force_mock=True)
    assert res_force["action"] == "FORCE"

    _, pending_sci_forced = get_pending_issues(lesson_dir)
    assert len(pending_sci_forced) > 0

    # La decisione custom NON deve essere stata cancellata
    ledger = load_ledger(lesson_dir)
    custom_decisions = [d for d in ledger.decisions if d.issue_id.startswith("custom_")]
    assert len(custom_decisions) == 1
    assert custom_decisions[0].issue_id == "custom_000001"

