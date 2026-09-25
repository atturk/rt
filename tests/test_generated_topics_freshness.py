"""
Argomenti generati dall'outline e freschezza delle fasi.

Se la lezione nasce senza argomenti (import dalla web app, oppure rt run senza -a),
l'outline li genera e il build li scrive in info.yaml. Quella scrittura non deve far
risultare l'outline (e con lui rewrite e build) STALE al controllo successivo.
"""
import json
import os

import pytest

from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.core.lesson_paths import lesson_path
from rt.core.state import read_info_yaml
from rt.pipeline.build import run_build
from rt.pipeline.ledger import record_decision
from rt.pipeline.outline import get_outline_path, run_outline
from rt.pipeline.prepare import run_prepare
from rt.pipeline.review import get_science_issues_path, run_review
from rt.pipeline.rewrite import run_rewrite

GENERATED = ["Trigliceridi", "Beta-ossidazione", "Resa energetica"]


@pytest.fixture(params=["argomenti: ''", "argomenti:"], ids=["empty-string", "null"])
def lesson_without_topics(tmp_path, request):
    # run_setup scrive "argomenti:" (null); altri percorsi scrivono una stringa vuota.
    lesson_dir = str(tmp_path / "[2026-09-25] ANATOMIA")
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(
            f"data: '2026-09-25'\nmateria: ANATOMIA\n{request.param}\n"
            "cartella: '[2026-09-25] ANATOMIA'\nfile_audio: a.m4a\n"
            "fase_corrente: setup_completato\nstato: setup_completato\n"
        )
    segments = {"segments": [
        {"id": f"s{i}", "start": i * 10000, "end": (i + 1) * 10000, "text": text}
        for i, text in enumerate([
            "Introduzione ai trigliceridi e acidi grassi.",
            "La lipolisi e il rilascio di glicerolo.",
            "Attivazione degli acidi grassi con acil-CoA sintetasi.",
            "Ruolo della carnitina palmitoil transferasi.",
            "Le quattro reazioni della beta-ossidazione.",
            "Resa energetica in ATP dell'acido palmitico.",
        ])
    ]}
    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump(segments, f)
    return lesson_dir


def _run_all(lesson_dir):
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    # Come fa l'LLM reale quando gli argomenti mancano (il mock non li genera).
    out_path = get_outline_path(lesson_dir)
    with open(out_path, "r", encoding="utf-8") as f:
        outline = json.load(f)
    outline["generated_topics"] = GENERATED
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(outline, f)
    run_rewrite(lesson_dir, force_mock=True)
    run_review(lesson_dir, force_mock=True)
    with open(get_science_issues_path(lesson_dir), "r", encoding="utf-8") as f:
        issues = json.load(f)
    for iss in issues:
        record_decision(lesson_dir, iss["id"], "accepted")
    run_build(lesson_dir, rename_folder=False)


def test_generated_topics_written_by_build_keep_phases_valid(lesson_without_topics):
    lesson_dir = lesson_without_topics
    _run_all(lesson_dir)

    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    assert info["argomenti"] == ", ".join(GENERATED)
    for phase in ("prepare", "outline", "rewrite", "build"):
        status, reason = check_phase_status(lesson_dir, phase)
        assert status == PhaseStatus.VALID, f"{phase}: {status.value} ({reason})"


def test_user_edit_of_topics_still_marks_outline_stale(lesson_without_topics):
    lesson_dir = lesson_without_topics
    _run_all(lesson_dir)

    from rt.core.state import update_info_yaml
    update_info_yaml(lesson_path(lesson_dir, "info.yaml"), {"argomenti": "Argomenti scelti a mano"})
    status, _ = check_phase_status(lesson_dir, "outline")
    assert status == PhaseStatus.STALE
