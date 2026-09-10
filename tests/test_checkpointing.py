"""
tests/test_checkpointing.py
Suite completa di test per il checkpointing incrementale continuo, crash-consistency,
stabilità degli ID e ripresa a costo zero in RT 2.0 (rewrite, review_science, review_asr).
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rt.core.models import (
    Segment, SegmentsData,
    Outline, OutlineMacro, OutlineUnit,
    Draft, DraftUnit, ASRIssue, ASRLevel,
    ScienceIssue, ScienceType, ScienceSeverity,
    DecisionLedger, ReviewDecision
)
from rt.core.state import read_info_yaml, transition_to, get_current_state, WorkflowState
from rt.core.manifest import load_manifest, init_or_update_manifest
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    record_phase_checkpoint,
    get_phase_checkpoint,
    mark_downstream_stale,
)
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import load_outline, get_outline_path
from rt.pipeline.rewrite import run_rewrite, load_draft, get_draft_path, save_draft
from rt.pipeline.review_asr import run_review_asr, load_asr_issues, get_asr_issues_path, save_asr_issues
from rt.pipeline.review_science import run_review_science, load_science_issues, get_science_issues_path, save_science_issues
from rt.pipeline.build import run_build
from rt.pipeline.ledger import load_ledger, record_decision, get_ledger_path
from rt.llm.client import LLMClient
from rt.llm.telemetry import GLOBAL_TELEMETRY


@pytest.fixture
def multi_unit_lesson(tmp_path):
    """Crea una lezione sintetica con 6 segmenti e un outline con 3 unità didattiche distinte."""
    lesson_dir = str(tmp_path / "[2026-09-06] TEST - Checkpointing Lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-06'
materia: BIOCHIMICA
argomenti: Lipidi e metabolismo energetico
cartella: '[2026-09-06] TEST - Checkpointing Lesson'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    transcript_content = """---
data: '2026-09-06'
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

    # Esegui prepare per generare segments.json e segments.raw.md
    run_prepare(lesson_dir)

    # Crea outline con 3 unità: 1.1, 1.2, 1.3
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Test Checkpoint",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Capitolo 1: Metabolismo lipidico",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Introduzione e riserve adipose",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000002",
                        key_concepts=["Tessuto adiposo", "Riserve energetiche"]
                    ),
                    OutlineUnit(
                        id="1.2",
                        title="Attivazione della lipasi e fosforilazione",
                        start_segment_id="seg_000003",
                        end_segment_id="seg_000004",
                        key_concepts=["Lipasi", "Glicerolo chinasi"]
                    ),
                    OutlineUnit(
                        id="1.3",
                        title="Beta ossidazione ed energia",
                        start_segment_id="seg_000005",
                        end_segment_id="seg_000006",
                        key_concepts=["Beta-ossidazione", "Sarcomeri muscolari"]
                    )
                ]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "outline.json"), "w", encoding="utf-8") as f:
        f.write(outline.model_dump_json(indent=2))

    source_fp = compute_source_fingerprint(lesson_dir, "outline")
    outline_hash = compute_file_sha256(os.path.join(lesson_dir, "outline.json"))
    record_phase_fingerprint(lesson_dir, "outline", source_fp, {"outline.json": outline_hash})
    transition_to(os.path.join(lesson_dir, "info.yaml"), WorkflowState.OUTLINE_VALIDATED)

    return lesson_dir


# ==============================================================================
# TEST 1: REWRITE CHECKPOINTING & CRASH RESUME
# ==============================================================================

def test_rewrite_checkpoint_and_clean_resume(multi_unit_lesson):
    """
    Verifica che:
    1. Se il rewrite fallisce sull'unità 1.2, l'unità 1.1 è salvata e il checkpoint è PARTIAL.
    2. La fase 'build' rimane bloccata in stato STALE.
    3. Al riavvio, l'unità 1.1 NON viene richiamata dall'LLM (0 token per 1.1).
    4. La fase completa a VALID al secondo passaggio.
    """
    lesson_dir = multi_unit_lesson
    original_call = LLMClient(force_mock=True).call_structured

    call_history = []

    def mock_call_with_crash(self, prompt, system_prompt, response_model, job_name=None, unit_id=None, **kwargs):
        call_history.append(unit_id)
        if "1.2" in str(unit_id):
            raise RuntimeError("CRASH SIMULATO SULL'UNITÀ 1.2")
        return original_call(prompt, system_prompt, response_model, job_name=job_name, unit_id=unit_id, **kwargs)

    # 1. Primo run: fallisce durante l'unità 1.2
    with patch.object(LLMClient, "call_structured", mock_call_with_crash):
        with pytest.raises(RuntimeError, match="CRASH SIMULATO SULL'UNITÀ 1.2"):
            run_rewrite(lesson_dir, force_mock=True)

    # Verifica stato PARTIAL
    status, reason = check_phase_status(lesson_dir, "rewrite")
    assert status == PhaseStatus.PARTIAL, f"Rewrite doveva essere PARTIAL ma era {status} ({reason})"

    # Verifica DAG: build deve rimanere non valido (MISSING o STALE) e non può essere saltato
    build_status, build_reason = check_phase_status(lesson_dir, "build")
    assert build_status in (PhaseStatus.STALE, PhaseStatus.MISSING), f"Build doveva essere bloccato ma era {build_status}"

    # Verifica che draft.json contenga solo l'unità 1.1
    draft = load_draft(lesson_dir)
    assert len(draft.units) == 1
    assert draft.units[0].unit_id == "1.1"

    # Verifica checkpoint nel manifest
    ckpt, ckpt_status, _ = get_phase_checkpoint(lesson_dir, "rewrite")
    assert ckpt is not None
    assert ckpt["status"] == "PARTIAL"
    assert ckpt["completed_items"] == ["1.1"]

    # 2. Secondo run (ripresa senza crash)
    call_history.clear()
    with patch.object(LLMClient, "call_structured", wraps=original_call) as spy_call:
        res = run_rewrite(lesson_dir, force_mock=True)
        assert res["action"] == "RUN"
        assert res["skipped"] is False
        assert res["processed_units"] == 2  # Solo 1.2 e 1.3!

        # Verifica che l'unità 1.1 non sia stata rielaborata
        called_unit_labels = [call.kwargs.get("unit_id") for call in spy_call.call_args_list]
        for label in called_unit_labels:
            assert "1.1" not in str(label), f"L'unità 1.1 non doveva essere richiamata: {label}"

    # Verifica completamento finale
    status_final, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_final == PhaseStatus.VALID

    final_draft = load_draft(lesson_dir)
    assert len(final_draft.units) == 3
    assert [u.unit_id for u in final_draft.units] == ["1.1", "1.2", "1.3"]


def test_rewrite_reconciliation_uncommitted_unit_in_draft(multi_unit_lesson):
    """
    Simula un crash tra save_draft e record_phase_checkpoint:
    draft.json contiene 1.1 e 1.2, ma il manifest riporta solo completed_items: ["1.1"].
    All'avvio, la riconciliazione deve scartare 1.2 e rieseguirla garantendo integrità.
    """
    lesson_dir = multi_unit_lesson
    # Esegui 1.1 regolarmente
    run_rewrite(lesson_dir, target_unit_id="1.1", force_mock=True)

    # Inietta artificialmente l'unità 1.2 nel draft senza aggiornare il manifest
    draft = load_draft(lesson_dir)
    draft.units.append(DraftUnit(
        unit_id="1.2",
        title="Unità 1.2 sporca non committata",
        start_segment_id="seg_000003",
        end_segment_id="seg_000004",
        source_segment_ids=["seg_000003", "seg_000004"],
        content="Testo parziale interrotto prima del manifest update."
    ))
    save_draft(draft, lesson_dir)

    # Checkpoint nel manifest riporta solo 1.1
    ckpt, _, _ = get_phase_checkpoint(lesson_dir, "rewrite")
    assert ckpt["completed_items"] == ["1.1"]

    # Riavvia run_rewrite
    run_rewrite(lesson_dir, force_mock=True)

    final_draft = load_draft(lesson_dir)
    assert len(final_draft.units) == 3
    # L'unità 1.2 è stata ricalcolata e non contiene il testo sporco
    unit_1_2 = next(u for u in final_draft.units if u.unit_id == "1.2")
    assert "Unità 1.2 sporca" not in unit_1_2.title
    status_final, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_final == PhaseStatus.VALID


def test_rewrite_target_unit_isolation_preserves_partial(multi_unit_lesson):
    """
    Verifica che l'elaborazione di una singola unità con target_unit_id non promuova
    accidentalmente una fase incompleta a VALID.
    """
    lesson_dir = multi_unit_lesson

    # Esegui solo target_unit_id="1.2"
    res = run_rewrite(lesson_dir, target_unit_id="1.2", force_mock=True)
    assert res["status"] == "unit_regenerated"

    # La fase globale rewrite DEVE essere PARTIAL, non VALID!
    status, _ = check_phase_status(lesson_dir, "rewrite")
    assert status == PhaseStatus.PARTIAL

    # Tuttavia il controllo specifico per 1.2 deve risultare VALID
    status_1_2, _ = check_phase_status(lesson_dir, "rewrite", target_unit_id="1.2")
    assert status_1_2 == PhaseStatus.VALID

    # L'unità 1.1 non è ancora nel draft: il suo stato specifico per unità è MISSING
    status_1_1, _ = check_phase_status(lesson_dir, "rewrite", target_unit_id="1.1")
    assert status_1_1 == PhaseStatus.MISSING

    # Rigenerando le altre unità (1.1 e 1.3) una alla volta
    run_rewrite(lesson_dir, target_unit_id="1.1", force_mock=True)
    status_mid, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_mid == PhaseStatus.PARTIAL

    run_rewrite(lesson_dir, target_unit_id="1.3", force_mock=True)
    # Ora che tutte le unità sono presenti nel draft, la fase globale diventa VALID!
    status_full, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_full == PhaseStatus.VALID


# ==============================================================================
# TEST 2: REVIEW SCIENCE CHECKPOINTING & 0-ISSUE TRACKING
# ==============================================================================

def test_review_science_checkpoint_and_zero_issue_tracking(multi_unit_lesson):
    """
    Verifica che:
    1. Unità con zero issue vengano comunque tracciate in reviewed_unit_ids.
    2. Se si verifica un crash sull'unità 1.3, il checkpoint conserva 1.1 e 1.2.
    3. Alla ripresa, le unità 1.1 e 1.2 non vengono riesaminate.
    """
    lesson_dir = multi_unit_lesson
    run_rewrite(lesson_dir, force_mock=True)

    original_call = LLMClient(force_mock=True).call_structured

    def mock_science_call(self, prompt, system_prompt, response_model, job_name=None, unit_id=None, **kwargs):
        if "1.1" in str(unit_id):
            # Unità 1.1: 0 issue trovate
            class EmptyList:
                issues = []
            return EmptyList()
        elif "1.2" in str(unit_id):
            # Unità 1.2: 1 issue trovata
            iss = ScienceIssue(
                id="sci_temp",
                unit_id="1.2",
                segment_id="seg_000003",
                type=ScienceType.ERR_DOCENTE,
                claim="Affermazione contestata",
                source_quote="I lipidi sono depositati nel tessuto adiposo",
                reason="Lapsus terminologico",
                severity=ScienceSeverity.HIGH,
                status="pending"
            )
            class OneIssueList:
                issues = [iss]
            return OneIssueList()
        elif "1.3" in str(unit_id):
            raise RuntimeError("CRASH SIMULATO SU SCIENCE REVIEW 1.3")
        return original_call(prompt, system_prompt, response_model, job_name=job_name, unit_id=unit_id, **kwargs)

    # 1. Primo run con crash
    with patch.object(LLMClient, "call_structured", mock_science_call):
        with pytest.raises(RuntimeError, match="CRASH SIMULATO SU SCIENCE REVIEW 1.3"):
            run_review_science(lesson_dir, force_mock=True)

    # Verifica stato PARTIAL
    status, _ = check_phase_status(lesson_dir, "review_science")
    assert status == PhaseStatus.PARTIAL

    # Verifica checkpoint: 1.1 e 1.2 devono essere presenti anche se 1.1 ha 0 issue!
    ckpt, _, _ = get_phase_checkpoint(lesson_dir, "review_science")
    assert ckpt is not None
    assert ckpt["completed_items"] == ["1.1", "1.2"]

    # Verifica issues salvate
    issues = load_science_issues(lesson_dir)
    assert len(issues) == 1
    assert issues[0].unit_id == "1.2"
    assert issues[0].id == "sci_000001"

    # 2. Secondo run (ripresa)
    with patch.object(LLMClient, "call_structured", wraps=original_call) as spy_call:
        res = run_review_science(lesson_dir, force_mock=True)
        assert res["action"] == "RUN"

        # Solo l'unità 1.3 deve essere stata chiamata
        called_units = [call.kwargs.get("unit_id") for call in spy_call.call_args_list]
        assert len(called_units) == 1
        assert "1.3" in str(called_units[0])

    # Verifica completamento
    status_final, _ = check_phase_status(lesson_dir, "review_science")
    assert status_final == PhaseStatus.VALID


def test_review_science_reconciliation_orphan_issues(multi_unit_lesson):
    """
    Simula la presenza di issue orfane in science_issues.json (dovute a crash prima del manifest).
    La riconciliazione all'avvio deve ripulirle tenendo solo quelle committate nel manifest.
    """
    lesson_dir = multi_unit_lesson
    run_rewrite(lesson_dir, force_mock=True)

    # Creiamo un checkpoint valido con solo l'unità 1.1 completata (senza issue)
    source_fp = compute_source_fingerprint(lesson_dir, "review_science")
    save_science_issues([], lesson_dir)
    sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))
    record_phase_checkpoint(
        lesson_dir=lesson_dir,
        phase_name="review_science",
        source_fingerprint=source_fp,
        artifact_fingerprints={"science_issues.json": sci_hash},
        completed_items=["1.1"]
    )

    # Inseriamo un'issue sporca per l'unità 1.2 nel file JSON senza aggiornare il manifest
    orphan_iss = ScienceIssue(
        id="sci_999999",
        unit_id="1.2",
        segment_id="seg_000003",
        type=ScienceType.ERR_RECONSTRUCTION,
        claim="Orphan claim",
        source_quote="Quote",
        reason="Reason",
        severity=ScienceSeverity.LOW,
        status="pending"
    )
    save_science_issues([orphan_iss], lesson_dir)

    # Eseguiamo run_review_science
    run_review_science(lesson_dir, force_mock=True)

    final_issues = load_science_issues(lesson_dir)
    # L'issue con id 'sci_999999' o 'Orphan claim' è stata rimossa durante la riconciliazione
    assert not any(i.claim == "Orphan claim" for i in final_issues)
    status_final, _ = check_phase_status(lesson_dir, "review_science")
    assert status_final == PhaseStatus.VALID


# ==============================================================================
# TEST 3: REVIEW ASR CHECKPOINTING, LEDGER CONSISTENCY & ID STABILITY
# ==============================================================================

def test_review_asr_checkpoint_ledger_consistency_and_id_stability(multi_unit_lesson):
    """
    Verifica che:
    1. In caso di crash su un batch successivo (batch 2 di 3), il batch 1 è salvato.
    2. Le decisioni GREEN del batch 1 sono registrate nel ledger.json.
    3. Gli ID asr_{idx:06d} rimangono immutabili e stabili attraverso il restart.
    4. Alla ripresa, il batch 1 non viene rieseguito e non si generano duplicati nel ledger.
    """
    lesson_dir = multi_unit_lesson
    run_rewrite(lesson_dir, force_mock=True)  # review_asr dipende ora anche da rewrite (draft-aware)
    original_call = LLMClient(force_mock=True).call_structured

    # Creiamo 3 batch ASR usando batch_size=2 sui 6 segmenti
    batch_count = 0

    def mock_asr_call_with_crash(self, prompt, system_prompt, response_model, job_name=None, unit_id=None, **kwargs):
        nonlocal batch_count
        batch_count += 1
        if "batch 02" in str(unit_id):
            raise RuntimeError("CRASH SIMULATO SUL BATCH ASR 2")

        # Ritorna 2 issue per batch: una GREEN (auto-accepted) e una YELLOW
        class ASRMockList:
            issues = [
                ASRIssue(
                    id="placeholder",
                    segment_id="seg_000001",
                    source_text="licorolo",
                    candidate="glicerolo",
                    confidence=0.96,  # GREEN
                    level=ASRLevel.GREEN,
                    reason="Correzione fonetica",
                    status="accepted"
                ),
                ASRIssue(
                    id="placeholder2",
                    segment_id="seg_000002",
                    source_text="finansi",
                    candidate="chinasi",
                    confidence=0.80,  # YELLOW
                    level=ASRLevel.YELLOW,
                    reason="Termine incerto",
                    status="pending"
                )
            ]
        return ASRMockList()

    # 1. Primo run con crash sul batch 2
    with patch.object(LLMClient, "call_structured", mock_asr_call_with_crash):
        with pytest.raises(RuntimeError, match="CRASH SIMULATO SUL BATCH ASR 2"):
            run_review_asr(lesson_dir, force_mock=True, batch_size=2)

    # Verifica stato PARTIAL
    status, _ = check_phase_status(lesson_dir, "review_asr")
    assert status == PhaseStatus.PARTIAL

    # Verifica che il batch 1 abbia registrato 2 issue
    issues_run1 = load_asr_issues(lesson_dir)
    assert len(issues_run1) == 2
    batch1_ids = [i.id for i in issues_run1]
    assert batch1_ids == ["asr_000001", "asr_000002"]

    # Verifica che la GREEN sia nel ledger
    ledger_run1 = load_ledger(lesson_dir)
    assert len(ledger_run1.decisions) == 1
    assert ledger_run1.decisions[0].issue_id == "asr_000001"
    assert ledger_run1.decisions[0].decision == "accepted"

    # 2. Secondo run: ripresa e completamento
    with patch.object(LLMClient, "call_structured", wraps=original_call) as spy_call:
        res = run_review_asr(lesson_dir, force_mock=True, batch_size=2)
        assert res["action"] == "RUN"

        # Verifica che il batch 1 non sia stato rielaborato
        called_batches = [call.kwargs.get("unit_id") for call in spy_call.call_args_list]
        for b in called_batches:
            assert "batch 01" not in str(b), f"Batch 1 non doveva essere rieseguito: {b}"

    # Verifica stabilità degli ID: le prime due issue devono avere gli stessi identici ID
    final_issues = load_asr_issues(lesson_dir)
    assert len(final_issues) >= 2
    assert final_issues[0].id == "asr_000001"
    assert final_issues[1].id == "asr_000002"
    # Gli ID successivi sono sequenziali e stabili
    assert final_issues[2].id == "asr_000003"

    # Verifica assenza di duplicazioni nel ledger
    final_ledger = load_ledger(lesson_dir)
    ledger_issue_ids = [d.issue_id for d in final_ledger.decisions]
    assert len(ledger_issue_ids) == len(set(ledger_issue_ids)), "Trovati duplicati nel ledger!"

    # Stato finale completato
    status_final, _ = check_phase_status(lesson_dir, "review_asr")
    assert status_final == PhaseStatus.VALID


def test_review_asr_reconciliation_missing_ledger_entry(multi_unit_lesson):
    """
    Simula un crash tra il salvataggio di asr_issues.json e la scrittura del ledger:
    asr_issues.json contiene una decisione GREEN ma il ledger non la contiene ancora.
    All'avvio, la procedura di riconciliazione deve rilevarla e committarla nel ledger.
    """
    lesson_dir = multi_unit_lesson
    run_rewrite(lesson_dir, force_mock=True)  # review_asr dipende ora anche da rewrite (draft-aware)

    # Inizializziamo asr_issues con una issue GREEN
    green_iss = ASRIssue(
        id="asr_000001",
        segment_id="seg_000001",
        source_text="finansi",
        candidate="chinasi",
        confidence=0.98,
        level=ASRLevel.GREEN,
        reason="Fonetica",
        status="accepted"
    )
    save_asr_issues([green_iss], lesson_dir)

    # Creiamo un checkpoint in cui il batch 1 è registrato
    source_fp = compute_source_fingerprint(lesson_dir, "review_asr")
    asr_hash = compute_file_sha256(get_asr_issues_path(lesson_dir))
    record_phase_checkpoint(
        lesson_dir=lesson_dir,
        phase_name="review_asr",
        source_fingerprint=source_fp,
        artifact_fingerprints={"asr_issues.json": asr_hash},
        completed_items=["batch_001_seg_000001_seg_000002"]
    )

    # Il ledger è vuoto (simulando crash prima di record_decision)
    ledger = DecisionLedger(schema_version="1.0", lesson_id=os.path.basename(lesson_dir), decisions=[])
    with open(get_ledger_path(lesson_dir), "w", encoding="utf-8") as f:
        f.write(ledger.model_dump_json(indent=2))

    # Eseguiamo run_review_asr
    run_review_asr(lesson_dir, force_mock=True, batch_size=2)

    # Verifica che la issue GREEN sia stata recuperata e inserita nel ledger
    reconciled_ledger = load_ledger(lesson_dir)
    assert any(d.issue_id == "asr_000001" for d in reconciled_ledger.decisions)


# ==============================================================================
# TEST 4: INVARIANTI GENERALI (FORCE RESET & SKIP ZERO-COST)
# ==============================================================================

def test_checkpoint_force_rerun_resets_progress(multi_unit_lesson):
    """
    Verifica che il flag --force ignori e resetti i checkpoint parziali, rieseguendo tutto.
    """
    lesson_dir = multi_unit_lesson
    # Creiamo uno stato parziale con l'unità 1.1
    run_rewrite(lesson_dir, target_unit_id="1.1", force_mock=True)

    status_before, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_before == PhaseStatus.PARTIAL

    # Esecuzione con force=True
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res = run_rewrite(lesson_dir, force=True, force_mock=True)
        assert res["action"] == "FORCE"
        # Tutte e 3 le unità vengono rielaborate
        assert res["processed_units"] == 3
        assert spy_call.call_count == 3

    status_after, _ = check_phase_status(lesson_dir, "rewrite")
    assert status_after == PhaseStatus.VALID


def test_completed_phase_skip_zero_llm_calls(multi_unit_lesson):
    """
    Verifica che quando una fase ha completato tutti i checkpoint ed è VALID,
    le successive esecuzioni ritornano SKIP con esattamente 0 chiamate LLM.
    """
    lesson_dir = multi_unit_lesson

    # Completa rewrite
    run_rewrite(lesson_dir, force_mock=True)
    assert check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID

    # Seconda esecuzione: SKIP
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res = run_rewrite(lesson_dir, force_mock=True)
        assert res["action"] == "SKIP"
        assert res["skipped"] is True
        assert spy_call.call_count == 0

    # Completa review_asr
    run_review_asr(lesson_dir, force_mock=True)
    assert check_phase_status(lesson_dir, "review_asr")[0] == PhaseStatus.VALID

    # Seconda esecuzione: SKIP
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res = run_review_asr(lesson_dir, force_mock=True)
        assert res["action"] == "SKIP"
        assert res["skipped"] is True
        assert spy_call.call_count == 0

    # Completa review_science
    run_review_science(lesson_dir, force_mock=True)
    assert check_phase_status(lesson_dir, "review_science")[0] == PhaseStatus.VALID

    # Seconda esecuzione: SKIP
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res = run_review_science(lesson_dir, force_mock=True)
        assert res["action"] == "SKIP"
        assert res["skipped"] is True
        assert spy_call.call_count == 0
