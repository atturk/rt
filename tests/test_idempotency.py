"""
tests/test_idempotency.py
Suite completa per la validazione dell'idempotenza, del safe rerun,
della protezione dei costi LLM, del flag --force, dell'invalidazione downstream
e della crash-safety nel workflow RT 2.0.
Tutti i test usano fixture sintetiche in memoria/tmp_path senza chiamate a lezioni reali o API esterne.
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
from rt.core.state import read_info_yaml, transition_to, get_current_state, VALID_TRANSITIONS, WorkflowState
from rt.core.manifest import load_manifest, init_or_update_manifest
from rt.core.lesson_paths import lesson_path
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    mark_downstream_stale,
)
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, run_outline_revision, load_outline, get_outline_path
from rt.pipeline.rewrite import run_rewrite, load_draft, get_draft_path
from rt.pipeline.review_asr import run_review_asr, load_asr_issues, get_asr_issues_path
from rt.pipeline.review_science import run_review_science, load_science_issues, get_science_issues_path
from rt.pipeline.build import run_build
from rt.pipeline.ledger import load_ledger, record_decision
from rt.llm.client import LLMClient
from rt.llm.telemetry import GLOBAL_TELEMETRY, LLMTelemetryRecord


@pytest.fixture
def synthetic_lesson(tmp_path):
    """Crea una lezione sintetica isolata con 6 segmenti per test offline deterministici."""
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - Lezione Idempotenza")
    os.makedirs(lesson_dir, exist_ok=True)
    
    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi e beta-ossidazione
cartella: '[2026-09-05] TEST - Lezione Idempotenza'
file_audio: test_audio.m4a
fase_corrente: setup_completato
stato: setup_completato
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)
        
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


# ==============================================================================
# TEST 1: TEST ECONOMICO ESPLICITO SUI 4 JOB LLM (Run1 > 0, Run2 = 0, Force > 0)
# ==============================================================================

def test_economic_outline_phase(synthetic_lesson):
    """Verifica costo e chiamate su outline: 1a esecuzione -> LLM > 0; 2a -> 0 LLM (SKIP); --force -> LLM > 0."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)

    GLOBAL_TELEMETRY.clear()
    
    # 1. Prima esecuzione: chiama LLM
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res1 = run_outline(lesson_dir, force_mock=True)
        assert res1["action"] == "RUN"
        assert res1["skipped"] is False
        assert spy_call.call_count == 1
        assert len(GLOBAL_TELEMETRY.get_all(job="outline")) == 1

    # 2. Seconda esecuzione identica: SKIP immediato, ZERO chiamate LLM, ZERO delta telemetria
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res2 = run_outline(lesson_dir, force_mock=True)
        assert res2["action"] == "SKIP"
        assert res2["skipped"] is True
        assert spy_call.call_count == 0, "Seconda esecuzione non doveva effettuare chiamate LLM!"
        assert len(GLOBAL_TELEMETRY.get_all(job="outline")) == 1, "Nessun record di telemetria deve essere aggiunto sullo SKIP"

    # 3. Terza esecuzione con --force: nuove chiamate LLM, nuova telemetria
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res3 = run_outline(lesson_dir, force=True, force_mock=True)
        assert res3["action"] == "FORCE"
        assert res3["skipped"] is False
        assert spy_call.call_count == 1, "Il rerun forzato doveva effettuare una nuova chiamata LLM!"
        assert len(GLOBAL_TELEMETRY.get_all(job="outline")) == 2


def test_outline_revision_updates_fingerprint_and_validates(synthetic_lesson):
    """Verifica che run_outline_revision rigeneri l'outline, aggiorni fingerprint e passi la validazione."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    res_initial = run_outline(lesson_dir, force_mock=True)
    assert res_initial["status"] == "outline_validated"

    # Esegui la revisione con feedback
    res_rev = run_outline_revision(lesson_dir, feedback="Raggruppa le prime due unità didattiche", force_mock=True)
    assert res_rev["status"] == "outline_validated"
    assert res_rev["action"] == "REVISION"
    assert res_rev["validation_report"]["coverage_percentage"] > 0
    assert res_rev["validation_report"]["units_count"] > 0

    # Verifica persistenza dell'outline rivista
    revised_outline = load_outline(lesson_dir)
    assert revised_outline.lesson_title is not None
    assert len(revised_outline.macro_sections) > 0


def test_economic_rewrite_phase(synthetic_lesson):
    """Verifica costo e chiamate su rewrite: 1a esecuzione -> LLM > 0; 2a -> 0 LLM (SKIP); --force -> LLM > 0."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)

    GLOBAL_TELEMETRY.clear()

    # 1. Prima esecuzione rewrite
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res1 = run_rewrite(lesson_dir, force_mock=True)
        assert res1["action"] == "RUN"
        assert res1["skipped"] is False
        call_count_first_run = spy_call.call_count
        assert call_count_first_run > 0
        assert len(GLOBAL_TELEMETRY.get_all(job="rewrite")) == call_count_first_run

    # 2. Seconda esecuzione: SKIP completo, ZERO chiamate LLM
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res2 = run_rewrite(lesson_dir, force_mock=True)
        assert res2["action"] == "SKIP"
        assert res2["skipped"] is True
        assert res2["processed_units"] == 0
        assert spy_call.call_count == 0, "Rewrite seconda esecuzione doveva fare 0 chiamate LLM!"
        assert len(GLOBAL_TELEMETRY.get_all(job="rewrite")) == call_count_first_run

    # 3. Esecuzione con --force: riesegue tutte le unità
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res3 = run_rewrite(lesson_dir, force=True, force_mock=True)
        assert res3["action"] == "FORCE"
        assert res3["skipped"] is False
        assert spy_call.call_count == call_count_first_run
        assert len(GLOBAL_TELEMETRY.get_all(job="rewrite")) == call_count_first_run * 2


def test_economic_review_asr_phase(synthetic_lesson):
    """Verifica costo e chiamate su review-asr: 1a -> LLM > 0; 2a -> 0 LLM (SKIP); --force -> LLM > 0."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)

    GLOBAL_TELEMETRY.clear()

    # 1. Prima esecuzione
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res1 = run_review_asr(lesson_dir, force_mock=True)
        assert res1["action"] == "RUN"
        assert res1["skipped"] is False
        assert spy_call.call_count > 0
        recorded_calls = len(GLOBAL_TELEMETRY.get_all(job="review_asr"))

    # 2. Seconda esecuzione
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res2 = run_review_asr(lesson_dir, force_mock=True)
        assert res2["action"] == "SKIP"
        assert res2["skipped"] is True
        assert spy_call.call_count == 0
        assert len(GLOBAL_TELEMETRY.get_all(job="review_asr")) == recorded_calls

    # 3. Force
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res3 = run_review_asr(lesson_dir, force=True, force_mock=True)
        assert res3["action"] == "FORCE"
        assert res3["skipped"] is False
        assert spy_call.call_count > 0


def test_economic_review_science_phase(synthetic_lesson):
    """Verifica costo e chiamate su review-science: 1a -> LLM > 0; 2a -> 0 LLM (SKIP); --force -> LLM > 0."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)

    GLOBAL_TELEMETRY.clear()

    # 1. Prima esecuzione
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res1 = run_review_science(lesson_dir, force_mock=True)
        assert res1["action"] == "RUN"
        assert res1["skipped"] is False
        assert spy_call.call_count > 0
        recorded_calls = len(GLOBAL_TELEMETRY.get_all(job="review_science"))

    # 2. Seconda esecuzione
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res2 = run_review_science(lesson_dir, force_mock=True)
        assert res2["action"] == "SKIP"
        assert res2["skipped"] is True
        assert spy_call.call_count == 0
        assert len(GLOBAL_TELEMETRY.get_all(job="review_science")) == recorded_calls

    # 3. Force
    with patch.object(LLMClient, "call_structured", wraps=LLMClient(force_mock=True).call_structured) as spy_call:
        res3 = run_review_science(lesson_dir, force=True, force_mock=True)
        assert res3["action"] == "FORCE"
        assert res3["skipped"] is False
        assert spy_call.call_count > 0


# ==============================================================================
# TEST 2: ARTEFATTO MANCANTE (MISSING -> RUN)
# ==============================================================================

def test_missing_artifact_triggers_execution(synthetic_lesson):
    """Se un artefatto viene eliminato, la fase deve rilevarne l'assenza e rieseguire."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)

    draft_path = get_draft_path(lesson_dir)
    assert os.path.isfile(draft_path)

    # Elimina draft.json
    os.remove(draft_path)
    status, reason = check_phase_status(lesson_dir, "rewrite")
    assert status == PhaseStatus.MISSING

    # Riesegui rewrite
    res = run_rewrite(lesson_dir, force_mock=True)
    assert res["action"] == "RUN"
    assert res["skipped"] is False
    assert os.path.isfile(draft_path)


# ==============================================================================
# TEST 3: INPUT MODIFICATO (STALE -> RE-RUN)
# ==============================================================================

def test_upstream_input_change_marks_downstream_stale(synthetic_lesson):
    """Se l'input upstream (es. segments.json) viene modificato, outline rileva STALE e riesegue."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)

    # Stato iniziale: outline è VALID
    st, _ = check_phase_status(lesson_dir, "outline")
    assert st == PhaseStatus.VALID

    # Modifica segments.json aggiungendo o modificando un segmento
    seg_path = lesson_path(lesson_dir, "segments.json")
    with open(seg_path, "r", encoding="utf-8") as f:
        seg_data = json.load(f)
    seg_data["segments"][0]["text_raw"] = "Testo modificato per test di invalidazione"
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(seg_data, f)

    # Ora check_phase_status per outline deve rilevare STALE
    st, reason = check_phase_status(lesson_dir, "outline")
    assert st == PhaseStatus.STALE
    assert "modificati" in reason

    # Riesecuzione normale di outline deve procedere con RUN (non SKIP) per aggiornarsi
    res = run_outline(lesson_dir, force_mock=True)
    assert res["action"] == "RUN"
    assert res["skipped"] is False


# ==============================================================================
# TEST 4: ARTEFATTO CORROTTO O INVALIDO (INVALID -> RE-RUN)
# ==============================================================================

def test_corrupt_artifact_triggers_regeneration(synthetic_lesson):
    """Se un artefatto esistente è malformato (es. JSON corrotto), la fase deve rilevare INVALID e rieseguire."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)

    out_path = get_outline_path(lesson_dir)
    # Scrivi JSON non valido
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("{corrupt_json: true, unterminated...")

    st, reason = check_phase_status(lesson_dir, "outline")
    assert st == PhaseStatus.INVALID

    res = run_outline(lesson_dir, force_mock=True)
    assert res["action"] == "RUN"
    assert res["skipped"] is False
    assert os.path.isfile(out_path)
    # Verifica che ora sia un'outline valida
    valid_outline = load_outline(lesson_dir)
    assert len(valid_outline.macro_sections) >= 1


# ==============================================================================
# TEST 5: FORCE RERUN & INVALIDAZIONE DOWNSTREAM SELETTIVA
# ==============================================================================

def test_force_rerun_and_selective_downstream_invalidation(synthetic_lesson):
    """Riesecuzione forzata di rewrite invalida science review, ASR review (draft-aware) e build,
    senza toccare prepare o outline."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)
    run_rewrite(lesson_dir, force_mock=True)
    run_review_asr(lesson_dir, force_mock=True)
    run_review_science(lesson_dir, force_mock=True)
    run_build(lesson_dir)

    # Tutte le fasi devono essere VALID
    for ph in ["prepare", "outline", "rewrite", "review_asr", "review_science", "build"]:
        st, _ = check_phase_status(lesson_dir, ph)
        assert st == PhaseStatus.VALID, f"Fase {ph} doveva essere VALID!"

    # Eseguiamo rewrite --force
    res = run_rewrite(lesson_dir, force=True, force_mock=True)
    assert res["action"] == "FORCE"

    # Verifichiamo gli stati dopo il force rewrite:
    # - prepare, outline: rimangono VALID (non dipendono dal draft)
    assert check_phase_status(lesson_dir, "prepare")[0] == PhaseStatus.VALID
    assert check_phase_status(lesson_dir, "outline")[0] == PhaseStatus.VALID

    # - rewrite: è tornato VALID (appena rigenerato)
    assert check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID

    # - review_asr, review_science e build: devono essere STALE! (review_asr dipende ora
    #   anche dal draft, non solo dalla trascrizione grezza)
    assert check_phase_status(lesson_dir, "review_asr")[0] == PhaseStatus.STALE
    assert check_phase_status(lesson_dir, "review_science")[0] == PhaseStatus.STALE
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.STALE


# ==============================================================================
# TEST 6: RERUN PARZIALE PER SINGOLA UNITÀ (rewrite --unit X --force)
# ==============================================================================

def test_partial_rewrite_single_unit(synthetic_lesson):
    """Rigenerazione di una singola unità con --force aggiorna solo quella unità e preserva le altre."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)
    
    # Creiamo manualmente un'outline con 2 unità distinte
    seg_path = lesson_path(lesson_dir, "segments.json")
    from rt.core.segments import load_segments_json
    seg_data = load_segments_json(seg_path)
    
    custom_outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione a Due Unita",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Capitolo Unico",
                units=[
                    OutlineUnit(id="1.1", title="Prima Unita", start_segment_id="seg_000001", end_segment_id="seg_000003"),
                    OutlineUnit(id="1.2", title="Seconda Unita", start_segment_id="seg_000004", end_segment_id="seg_000006"),
                ]
            )
        ]
    )
    from rt.pipeline.outline import save_outline
    save_outline(custom_outline, lesson_dir)
    source_fp = compute_source_fingerprint(lesson_dir, "outline")
    record_phase_fingerprint(lesson_dir, "outline", source_fp, {"outline.json": compute_file_sha256(get_outline_path(lesson_dir))})
    transition_to(os.path.join(lesson_dir, "info.yaml"), WorkflowState.OUTLINE_VALIDATED)

    # Prima esecuzione globale rewrite (genera 1.1 e 1.2)
    run_rewrite(lesson_dir, force_mock=True)
    draft_init = load_draft(lesson_dir)
    assert len(draft_init.units) == 2
    u1_init_content = draft_init.units[0].content
    u2_init_content = draft_init.units[1].content

    # Modifica simulata dell'unità 1.1 con rewrite --unit 1.1 --force
    with patch.object(LLMClient, "call_structured") as mock_call:
        # Il mock restituisce testo aggiornato solo per 1.1
        mock_unit = DraftUnit(
            unit_id="1.1",
            title="Prima Unita",
            start_segment_id="seg_000001",
            end_segment_id="seg_000003",
            source_segment_ids=["seg_000001", "seg_000002", "seg_000003"],
            content="TESTO UNIT 1.1 RIGENERATO DA UTENTE ESPLICITAMENTE"
        )
        mock_call.return_value = mock_unit

        res_unit = run_rewrite(lesson_dir, target_unit_id="1.1", force=True, force_mock=False)
        assert res_unit["action"] == "FORCE"
        assert res_unit["processed_units"] == 1
        # ESATTAMENTE 1 chiamata LLM effettuata!
        assert mock_call.call_count == 1

    # Verifichiamo il draft risultante su disco
    draft_after = load_draft(lesson_dir)
    assert len(draft_after.units) == 2
    # L'unità 1.1 è stata aggiornata
    assert draft_after.units[0].content == "TESTO UNIT 1.1 RIGENERATO DA UTENTE ESPLICITAMENTE"
    # L'unità 1.2 è rimasta TOTALMENTE INVARIATA
    assert draft_after.units[1].content == u2_init_content

    # review_science e build non sono mai stati eseguiti in questo test (nessuna chiamata a
    # run_review_science()/run_build() sopra): non c'è nulla da invalidare, quindi restano
    # MISSING (mai generati), non STALE — semantica corretta dal disaccoppiamento di
    # review_asr/review_science dalla run di default (mark_downstream_stale() non marca più
    # STALE una fase che non ha mai avuto un record nel manifest, vedi rt/core/idempotency.py).
    assert check_phase_status(lesson_dir, "review_science")[0] == PhaseStatus.MISSING
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.MISSING


# ==============================================================================
# TEST 7: CRASH-SAFETY & CONSISTENZA ATOMICA DELLO STATO
# ==============================================================================

def test_crash_safety_on_pipeline_failure(synthetic_lesson):
    """Se si verifica un'eccezione durante la fase, non deve rimanere uno stato o artefatto parziale corrotto."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)

    yaml_path = os.path.join(lesson_dir, "info.yaml")
    init_state = get_current_state(yaml_path)
    assert init_state == WorkflowState.PREPARED

    # Simuliamo un'eccezione non gestita durante la chiamata LLM di outline
    with patch.object(LLMClient, "call_structured", side_effect=RuntimeError("Simulated LLM network drop")):
        with pytest.raises(RuntimeError):
            run_outline(lesson_dir, force_mock=False)

    # Verifiche crash-safety:
    # 1. outline.json NON deve esistere (nessun file mezzo scritto)
    assert not os.path.isfile(get_outline_path(lesson_dir))
    assert not os.path.isfile(get_outline_path(lesson_dir) + ".tmp")

    # 2. Lo stato in info.yaml NON deve essere avanzato a OUTLINE_VALIDATED
    state_after = get_current_state(yaml_path)
    assert state_after == WorkflowState.PREPARED

    # 3. Il manifest deve rimanere integro
    manifest = load_manifest(lesson_dir)
    assert manifest.current_state == WorkflowState.PREPARED.value


# ==============================================================================
# TEST 8: DIAGNOSTICA RT STATUS CON MOTIVAZIONI
# ==============================================================================

def test_rt_status_reporting(synthetic_lesson):
    """Verifica che check_phase_status fornisca motivazioni chiare per ogni stato."""
    lesson_dir = synthetic_lesson
    run_prepare(lesson_dir)

    # Prepare deve essere VALID
    st_prep, reason_prep = check_phase_status(lesson_dir, "prepare")
    assert st_prep == PhaseStatus.VALID
    assert "valido" in reason_prep

    # Outline deve essere MISSING
    st_out, reason_out = check_phase_status(lesson_dir, "outline")
    assert st_out == PhaseStatus.MISSING
    assert "non trovato" in reason_out

    # Rewrite deve essere MISSING
    st_rew, reason_rew = check_phase_status(lesson_dir, "rewrite")
    assert st_rew == PhaseStatus.MISSING


# ==============================================================================
# TEST 9: STATE MACHINE FORWARD VS FORCE RERUN
# ==============================================================================

def test_state_machine_strictness_and_force():
    """Verifica che la state machine rimanga rigorosa per progressioni non consentite, ma gestisca allow_force."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yaml_path = os.path.join(td, "info.yaml")
        with open(yaml_path, "w") as f:
            f.write("fase_corrente: outline_validata\nstato: outline_validata\n")

        # Da outline_validata non è consentito saltare a completed direttamente
        with pytest.raises(ValueError, match="Transizione di stato non consentita"):
            transition_to(yaml_path, WorkflowState.COMPLETED, allow_force=False)

        # Con allow_force=True è consentito (ad es. per rollback o reset di sviluppo)
        transition_to(yaml_path, WorkflowState.COMPLETED, allow_force=True)
        assert get_current_state(yaml_path) == WorkflowState.COMPLETED


def test_manifest_self_heals_after_folder_moved(tmp_path):
    """Regressione trovata in test manuale: se la cartella della lezione viene spostata
    a mano (mv, Finder) dopo che manifest.json è stato scritto la prima volta, ogni
    scrittura successiva (record_phase_fingerprint/checkpoint, mark_downstream_stale)
    crashava con FileNotFoundError perché save_manifest() scriveva sempre nel vecchio
    percorso memorizzato in manifest.lesson_dir, mai in quello reale corrente."""
    import shutil
    old_dir = str(tmp_path / "lesson_old")
    os.makedirs(old_dir, exist_ok=True)
    with open(os.path.join(old_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(
            "data: '2026-09-08'\nmateria: BIOCHIMICA\nargomenti: Lipidi\n"
            "cartella: lesson_old\nfile_audio: test.m4a\n"
            "fase_corrente: setup_completato\nstato: setup_completato\n"
        )
    with open(os.path.join(old_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(
            "---\ndata: '2026-09-08'\nmateria: BIOCHIMICA\n---\n\n"
            "*00:02*\nIntroduzione alla lezione.\n\n*00:20*\nSeconda frase.\n"
        )

    run_prepare(old_dir)
    run_outline(old_dir, force_mock=True)

    new_dir = str(tmp_path / "sottocartella" / "lesson_new")
    os.makedirs(str(tmp_path / "sottocartella"), exist_ok=True)
    shutil.move(old_dir, new_dir)

    # Prima del fix: FileNotFoundError su manifest.json.tmp nel vecchio percorso.
    run_rewrite(new_dir, force_mock=True)
    build_res = run_build(new_dir)
    assert build_res.get("skipped") is False

    manifest = load_manifest(new_dir)
    assert manifest.lesson_dir == os.path.abspath(new_dir)
