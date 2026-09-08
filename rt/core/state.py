"""
rt.core.state
Macchina a stati deterministica per il ciclo di vita della lezione.
Mantiene allineati `info.yaml` e `manifest.json`.
"""

from enum import Enum
from typing import Dict, Any, Optional
import os
import re


class WorkflowState(str, Enum):
    METADATA_ONLY = "metadata_only"
    SETUP_COMPLETED = "setup_completato"
    PREPARED = "preparato"
    OUTLINE_VALIDATED = "outline_validata"
    DRAFT_VALIDATED = "draft_validato"
    ASR_REVIEW_READY = "revisione_asr_completata"
    SCIENCE_REVIEW_READY = "revisione_scientifica_completata"
    HUMAN_REVIEW_REQUIRED = "in_attesa_revisione_umana"
    READY_TO_BUILD = "pronto_per_build"
    COMPLETED = "completato"
    FAILED = "fallito"


# Mappa di transizioni consentite: stato_corrente -> set di stati successivi ammissibili
VALID_TRANSITIONS = {
    WorkflowState.METADATA_ONLY: {WorkflowState.SETUP_COMPLETED, WorkflowState.PREPARED, WorkflowState.FAILED},
    WorkflowState.SETUP_COMPLETED: {WorkflowState.PREPARED, WorkflowState.FAILED},
    WorkflowState.PREPARED: {WorkflowState.OUTLINE_VALIDATED, WorkflowState.PREPARED, WorkflowState.FAILED},
    WorkflowState.OUTLINE_VALIDATED: {WorkflowState.DRAFT_VALIDATED, WorkflowState.OUTLINE_VALIDATED, WorkflowState.FAILED},
    WorkflowState.DRAFT_VALIDATED: {WorkflowState.ASR_REVIEW_READY, WorkflowState.SCIENCE_REVIEW_READY, WorkflowState.READY_TO_BUILD, WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.ASR_REVIEW_READY: {WorkflowState.SCIENCE_REVIEW_READY, WorkflowState.HUMAN_REVIEW_REQUIRED, WorkflowState.READY_TO_BUILD, WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.SCIENCE_REVIEW_READY: {WorkflowState.HUMAN_REVIEW_REQUIRED, WorkflowState.READY_TO_BUILD, WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.HUMAN_REVIEW_REQUIRED: {WorkflowState.READY_TO_BUILD, WorkflowState.HUMAN_REVIEW_REQUIRED, WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.READY_TO_BUILD: {WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: {WorkflowState.COMPLETED, WorkflowState.PREPARED, WorkflowState.ASR_REVIEW_READY, WorkflowState.SCIENCE_REVIEW_READY, WorkflowState.READY_TO_BUILD}, # Ribilanciamento / review incrementale / re-build consentito

    WorkflowState.FAILED: set(WorkflowState), # Da fallito è possibile ripartire da qualsiasi stato valido dopo fix
}



def read_info_yaml(yaml_path: str) -> Dict[str, str]:
    """Legge info.yaml e restituisce un dizionario di stringhe."""
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"info.yaml non trovato in '{yaml_path}'")
    
    data: Dict[str, str] = {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                data[k.strip()] = v.strip().strip("\"'")
    return data


def format_yaml_value(value: Any) -> str:
    """Formatta in modo sicuro un valore per info.yaml."""
    s = str(value)
    if not s:
        return "''"
    if re.match(r"^[a-zA-Z0-9_-]+$", s):
        return s
    escaped = s.replace("'", "''")
    return f"'{escaped}'"


def update_info_yaml(yaml_path: str, updates: Dict[str, Any]) -> None:
    """Aggiorna le chiavi specificate in info.yaml in modo atomico preservando commenti e ordine."""
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"info.yaml non trovato in '{yaml_path}'")
    
    with open(yaml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    updated_keys = set()
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped and ":" in stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            key = stripped.split(":", 1)[0].strip()
            if key in updates:
                formatted = format_yaml_value(updates[key])
                new_lines.append(f"{key}: {formatted}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)
    
    for k, v in updates.items():
        if k not in updated_keys:
            formatted = format_yaml_value(v)
            new_lines.append(f"{k}: {formatted}\n")
    
    # Scrittura atomica
    tmp_path = yaml_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.replace(tmp_path, yaml_path)


def get_current_state(yaml_path: str) -> Optional[WorkflowState]:
    """Legge lo stato corrente del workflow da info.yaml."""
    if not os.path.exists(yaml_path):
        return None
    info = read_info_yaml(yaml_path)
    current_raw = info.get("fase_corrente", "") or info.get("stato", "")
    for state in WorkflowState:
        if state.value == current_raw or state.name.lower() == current_raw.lower():
            return state
    return None


def transition_to(yaml_path: str, new_state: WorkflowState, allow_force: bool = False) -> None:
    """
    Effettua la transizione verso il nuovo stato.
    Lancia ValueError se la transizione non è valida e allow_force è False.
    """
    info = read_info_yaml(yaml_path)
    current_raw = info.get("fase_corrente", "") or info.get("stato", "")
    
    # Mappa stati legacy a stati nuovi se applicabile
    current_state: Optional[WorkflowState] = None
    for state in WorkflowState:
        if state.value == current_raw or state.name.lower() == current_raw.lower():
            current_state = state
            break
    
    # Se lo stato attuale è legacy (es. 'pronto_per_rielaborazione'), trattalo come SETUP_COMPLETED
    if not current_state:
        if current_raw in ("pronto_per_rielaborazione", "fase_2_rielaborazione"):
            current_state = WorkflowState.SETUP_COMPLETED
        else:
            current_state = WorkflowState.SETUP_COMPLETED
    
    if current_state == new_state:
        update_info_yaml(yaml_path, {
            "fase_corrente": new_state.value,
            "stato": new_state.value
        })
        return

    if not allow_force and current_state in VALID_TRANSITIONS:
        allowed = VALID_TRANSITIONS[current_state]
        if new_state not in allowed:
            raise ValueError(f"Transizione di stato non consentita: da '{current_state.value}' a '{new_state.value}'")
    
    update_info_yaml(yaml_path, {
        "fase_corrente": new_state.value,
        "stato": new_state.value
    })


def compute_effective_workflow_state(lesson_dir: str) -> Optional[WorkflowState]:
    """
    Valuta e calcola dinamicamente lo stato effettivo e veritiero del workflow
    in base alla freschezza reale degli artefatti, alle dipendenze a monte e
    alle decisioni del Decision Ledger.
    
    Invariante fondamentale:
    WorkflowState.COMPLETED è vero SOLO se:
    1. build è VALID
    2. prepare, outline e rewrite sono VALID; review_asr e review_science sono VALID
       oppure semplicemente MAI generate (MISSING: sono opzionali, disaccoppiate dalla
       run di default) — solo se STALE/INVALID (generate ma superate da modifiche a
       monte) fanno retrocedere lo stato
    3. tutte le review ASR (YELLOW/RED) e Science EFFETTIVAMENTE generate sono state
       decise (0 pendenti; se non generate affatto, non c'è nulla da decidere)
    
    Se una fase a monte è STALE o INVALID, lo stato retrocede coerentemente
    alla prima fase che richiede attenzione.
    """
    yaml_path = os.path.join(lesson_dir, "info.yaml")
    if not os.path.isfile(yaml_path):
        return None

    info = read_info_yaml(yaml_path)
    current_raw = info.get("fase_corrente", "") or info.get("stato", "")
    if current_raw == WorkflowState.METADATA_ONLY.value:
        return WorkflowState.METADATA_ONLY
    if current_raw == WorkflowState.FAILED.value:
        return WorkflowState.FAILED

    from rt.core.idempotency import check_phase_status, PhaseStatus
    from rt.pipeline.ledger import load_ledger
    from rt.pipeline.review_asr import load_asr_issues
    from rt.pipeline.review_science import load_science_issues
    from rt.core.models import ASRLevel

    # 1. Prepare
    st_prep, _ = check_phase_status(lesson_dir, "prepare")
    if st_prep != PhaseStatus.VALID:
        return WorkflowState.SETUP_COMPLETED

    # 2. Outline
    st_out, _ = check_phase_status(lesson_dir, "outline")
    if st_out != PhaseStatus.VALID:
        return WorkflowState.PREPARED

    # 3. Rewrite
    st_rew, _ = check_phase_status(lesson_dir, "rewrite")
    if st_rew != PhaseStatus.VALID:
        return WorkflowState.OUTLINE_VALIDATED

    # 4. Review ASR — opzionale dal disaccoppiamento dalla run di default: MISSING (mai
    # generata, per scelta) non blocca il completamento; solo STALE/INVALID (era stata
    # generata ma una modifica a monte l'ha resa superata) retrocede davvero lo stato.
    st_asr, _ = check_phase_status(lesson_dir, "review_asr")
    if st_asr not in (PhaseStatus.VALID, PhaseStatus.MISSING):
        return WorkflowState.DRAFT_VALIDATED

    # 5. Review Science — stessa logica del punto 4.
    st_sci, _ = check_phase_status(lesson_dir, "review_science")
    if st_sci not in (PhaseStatus.VALID, PhaseStatus.MISSING):
        return WorkflowState.ASR_REVIEW_READY

    # 6. Verifica Decisioni Umane (ASR YELLOW/RED e Science)
    ledger = load_ledger(lesson_dir)
    decided_ids = {d.issue_id for d in ledger.decisions}
    asr_issues = load_asr_issues(lesson_dir)
    sci_issues = load_science_issues(lesson_dir)

    pending_asr = [
        iss for iss in asr_issues
        if iss.level in (ASRLevel.YELLOW, ASRLevel.RED) and iss.id not in decided_ids
    ]
    pending_sci = [
        iss for iss in sci_issues
        if iss.id not in decided_ids
    ]

    if pending_asr or pending_sci:
        return WorkflowState.HUMAN_REVIEW_REQUIRED

    # 7. Build
    st_bld, _ = check_phase_status(lesson_dir, "build")
    if st_bld != PhaseStatus.VALID:
        return WorkflowState.READY_TO_BUILD

    return WorkflowState.COMPLETED


