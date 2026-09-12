"""
tests/test_dag_freshness.py
Verifica rigorosa della DAG di dipendenze (UPSTREAM_DEPENDENCIES),
della propagazione transitiva della staleness, della semantica ASR vs Science Review,
della determinazione dinamica dello stato globale (compute_effective_workflow_state)
e della preservazione del fingerprint globale durante riscritture a singola unità.
"""

import os
import json
import pytest

from rt.core.models import (
    SegmentsData, Outline, Draft, DecisionLedger
)
from rt.core.state import (
    read_info_yaml, get_current_state, WorkflowState,
    compute_effective_workflow_state
)
from rt.core.lesson_paths import lesson_path
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    UPSTREAM_DEPENDENCIES,
    record_phase_fingerprint,
    compute_source_fingerprint
)
from rt.pipeline.prepare import run_prepare
from rt.pipeline.rewrite import run_rewrite, get_draft_path
from rt.pipeline.review import run_review, get_science_issues_path
from rt.pipeline.build import run_build
from rt.pipeline.ledger import record_decision


@pytest.fixture
def fully_built_lesson(tmp_path):
    """Costruisce una lezione sintetica completa fino allo stadio di build."""
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - DAG Semantics")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi e beta-ossidazione
cartella: '[2026-09-05] TEST - DAG Semantics'
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

    # Eseguiamo tutti gli stadi della pipeline in modalità mock
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)
    run_review(lesson_dir, force_mock=True)

    sci_path = get_science_issues_path(lesson_dir)
    with open(sci_path, "r", encoding="utf-8") as f:
        sci_data = json.load(f)
    for iss in sci_data:
        record_decision(lesson_dir, iss["id"], "accetta", notes="auto test accept")

    run_build(lesson_dir, rename_folder=False)
    return lesson_dir


def test_dag_definition_and_semantics():
    assert "prepare" not in UPSTREAM_DEPENDENCIES or UPSTREAM_DEPENDENCIES["prepare"] == []
    assert UPSTREAM_DEPENDENCIES["outline"] == ["prepare"]
    assert set(UPSTREAM_DEPENDENCIES["rewrite"]) == {"prepare", "outline"}
    assert set(UPSTREAM_DEPENDENCIES["review"]) == {"prepare", "rewrite"}
    assert set(UPSTREAM_DEPENDENCIES["build"]) == {"prepare", "outline", "rewrite", "review"}


def test_transitive_staleness_on_outline_modification(fully_built_lesson):
    """
    Caso 1: Modifica a outline.json
    - rewrite diventa STALE
    - build diventa transitivamente STALE (anche se il file rielaborato.md esiste fisicamente)
    - review_asr diventa transitivamente STALE (dipende ora anche da rewrite)
    - compute_effective_workflow_state() riporta OUTLINE_VALIDATED
    """
    lesson_dir = fully_built_lesson

    # Stato iniziale: tutto valido
    eff_state = compute_effective_workflow_state(lesson_dir)
    assert eff_state == WorkflowState.COMPLETED
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID

    # Modifichiamo outline.json
    outline_file = get_outline_path(lesson_dir)
    with open(outline_file, "r", encoding="utf-8") as f:
        out_data = json.load(f)
    out_data["macro_sections"][0]["title"] = "Titolo Macro Modificato Manualmente"
    with open(outline_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

    # Verifiche stati
    st_rew, r_rew = check_phase_status(lesson_dir, "rewrite")
    assert st_rew == PhaseStatus.STALE
    assert "outline" in r_rew

    st_rev, r_rev = check_phase_status(lesson_dir, "review")
    assert st_rev == PhaseStatus.STALE, "review dipende da rewrite, quindi diventa transitivamente STALE"

    st_bld, r_bld = check_phase_status(lesson_dir, "build")
    assert st_bld == PhaseStatus.STALE, "build deve essere transitivamente STALE se rewrite è STALE"
    assert "a monte" in r_bld

    eff_state_after = compute_effective_workflow_state(lesson_dir)
    assert eff_state_after == WorkflowState.OUTLINE_VALIDATED


def test_transitive_staleness_on_segments_modification(fully_built_lesson):
    """
    Caso 2: Modifica a segments.json
    - Tutte le fasi a valle (outline, rewrite, review, build) diventano STALE.
    """
    lesson_dir = fully_built_lesson

    seg_file = lesson_path(lesson_dir, "segments.json")
    with open(seg_file, "r", encoding="utf-8") as f:
        seg_data = json.load(f)
    seg_data["segments"][0]["text_raw"] = "Testo segmento modificato radicalmente."
    with open(seg_file, "w", encoding="utf-8") as f:
        json.dump(seg_data, f, indent=2)

    assert check_phase_status(lesson_dir, "outline")[0] == PhaseStatus.STALE
    assert check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.STALE
    assert check_phase_status(lesson_dir, "review")[0] == PhaseStatus.STALE
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.STALE

    eff_state = compute_effective_workflow_state(lesson_dir)
    assert eff_state in (WorkflowState.SETUP_COMPLETED, WorkflowState.PREPARED)


def test_selective_invalidation_draft_modification(fully_built_lesson):
    """
    Caso 3: Modifica a draft.json
    - review e build diventano STALE.
    - outline RIMANE VALID.
    """
    lesson_dir = fully_built_lesson

    draft_file = get_draft_path(lesson_dir)
    with open(draft_file, "r", encoding="utf-8") as f:
        draft_data = json.load(f)
    draft_data["units"][0]["content"] = "Contenuto riscritto aggiornato dall'utente."
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(draft_data, f, indent=2)

    assert check_phase_status(lesson_dir, "outline")[0] == PhaseStatus.VALID
    assert check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID  # Il file draft esiste e l'input outline non è cambiato
    assert check_phase_status(lesson_dir, "review")[0] == PhaseStatus.STALE, "review deve essere STALE perché draft è mutato"
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.STALE, "build deve essere STALE"


def test_single_unit_rewrite_preserves_global_fingerprint(fully_built_lesson):
    """
    Caso 5: Esecuzione di rewrite con target_unit_id non deve distruggere o alterare
    il fingerprint globale di fase registrato nel manifest.
    """
    lesson_dir = fully_built_lesson

    # Riscriviamo solo l'unità 1.1 con force_mock
    res_unit = run_rewrite(lesson_dir, target_unit_id="1.1", force=True, force_mock=True)
    assert res_unit["status"] == "draft_validated"

    # Verifichiamo che la fase rewrite NON risulti falsamente STALE rispetto al suo input outline
    st_rew, r_rew = check_phase_status(lesson_dir, "rewrite")
    assert st_rew == PhaseStatus.VALID, f"Rewrite globale non deve diventare STALE per singola unità: {r_rew}"


def test_build_valid_and_completed_without_optional_reviews(tmp_path):
    """
    Regressione (disaccoppiamento ASR/scienza dalla run di default): una lezione che
    passa da prepare -> outline -> rewrite -> build SENZA MAI eseguire review_asr/
    review_science (fasi ora opzionali) deve risultare build VALID (non STALE) e
    compute_effective_workflow_state() deve riportare COMPLETED, coerente con
    'fase_corrente: completato' scritto da run_build(). Prima del fix, due meccanismi
    condivisi assumevano che review_asr/review_science venissero SEMPRE eseguite:
    1. mark_downstream_stale() marcava review_science/build come STALE dopo ogni
       rewrite anche se non erano mai state generate (nulla da invalidare davvero);
    2. check_phase_status('build') trattava review_asr/review_science MISSING come
       una dipendenza a monte non valida, quindi 'build' restava STALE per sempre
       anche a build riuscita, rompendo la sua stessa idempotenza (mai SKIP al 2° giro).
    """
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(
            "data: '2026-09-08'\nmateria: BIOCHIMICA\nargomenti: Lipidi\n"
            "cartella: lesson\nfile_audio: test.m4a\n"
            "fase_corrente: setup_completato\nstato: setup_completato\n"
        )
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(
            "---\ndata: '2026-09-08'\nmateria: BIOCHIMICA\n---\n\n"
            "*00:02*\nIntroduzione alla lezione di biochimica sui lipidi.\n\n"
            "*00:20*\nI lipidi sono depositati nel tessuto adiposo.\n"
        )

    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)
    # Nessuna run_review_asr()/run_review_science(): simula il flusso di default senza --with-review.
    build_res = run_build(lesson_dir)
    assert build_res.get("skipped") is False

    st_bld, reason_bld = check_phase_status(lesson_dir, "build")
    assert st_bld == PhaseStatus.VALID, f"build deve essere VALID anche senza review generate: {reason_bld}"

    info = read_info_yaml(os.path.join(lesson_dir, "info.yaml"))
    assert info.get("fase_corrente") == "completato"

    effective = compute_effective_workflow_state(lesson_dir)
    assert effective == WorkflowState.COMPLETED, (
        f"Stato effettivo ({effective}) deve coincidere con 'completato', "
        "non deve retrocedere solo perché review_asr/science non sono mai state generate."
    )

    # Idempotenza reale: una seconda esecuzione di build deve fare SKIP (non deve
    # ricostruire ogni volta i Markdown perché build resta erroneamente STALE).
    build_res2 = run_build(lesson_dir)
    assert build_res2.get("skipped") is True
