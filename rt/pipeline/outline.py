"""
rt.pipeline.outline
Fase B: OUTLINE.
Genera la struttura gerarchica della lezione tramite LLM vincolando i timestamp
ai soli segment_id esistenti, e ne valida la coerenza e la copertura didattica.
"""

import os
import json
from typing import Dict, Any
from rt.core.models import Outline
from rt.core.segments import load_segments_json
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.core.manifest import init_or_update_manifest
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    OUTLINE_SYSTEM_PROMPT,
    build_outline_user_prompt,
    build_outline_revision_followup_prompt,
    build_outline_selfrepair_followup_prompt,
)
from rt.pipeline.validator import validate_outline, ValidationError
from rt.core.lesson_paths import lesson_path
from rt.core.config import load_config


from rt.core.encoding import sanitize_object_encoding
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    mark_downstream_stale,
)


def get_outline_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "outline.json")


def load_outline(lesson_dir: str) -> Outline:
    path = get_outline_path(lesson_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"outline.json non trovato in '{lesson_dir}'")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cleaned_data = sanitize_object_encoding(data)
    return Outline.model_validate(cleaned_data)


def save_outline(outline: Outline, lesson_dir: str) -> None:
    path = get_outline_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding(outline.model_dump(mode="json"))
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def run_outline(lesson_dir: str, force: bool = False, force_mock: bool = False) -> Dict[str, Any]:
    """Genera e valida l'outline della lezione."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    topics_val = info.get("argomenti") or None
    
    segments_path = lesson_path(lesson_dir, "segments.json")
    if not os.path.isfile(segments_path):
        raise FileNotFoundError(f"segments.json mancante. Esegui prima 'rt prepare' su '{lesson_dir}'")
        
    segments_data = load_segments_json(segments_path)
    
    # Controllo idempotenza: se valido e non forzato, SKIP immediato senza invocare LLM
    phase_status, reason = check_phase_status(lesson_dir, "outline")
    if phase_status == PhaseStatus.VALID and not force:
        cached_outline = load_outline(lesson_dir)
        validation_report = validate_outline(cached_outline, segments_data)
        return {
            "status": "outline_validated",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "outline_path": get_outline_path(lesson_dir),
            "validation_report": validation_report
        }
        
    action = "FORCE" if force else "RUN"
    
    # Costruzione sommario segmenti per prompt
    summary_lines = []
    for s in segments_data.segments:
        text_preview = " ".join(s.text_raw.split()[:18])
        summary_lines.append(f"[{s.id}] {s.start_formatted} - {s.end_formatted}: {text_preview}")
    segments_summary = "\n".join(summary_lines)
    
def _generate_validated_outline(
    client: LLMClient,
    system_prompt: str,
    base_history: list,
    final_user_prompt: str,
    segments_data,
    lesson_dir: str,
    max_repair_attempts: int = 2,
):
    history = list(base_history)
    current_prompt = final_user_prompt
    last_error = None
    for attempt in range(max_repair_attempts + 1):
        outline = client.call_structured(
            prompt=current_prompt,
            system_prompt=system_prompt,
            response_model=Outline,
            job_name="outline",
            lesson_dir=lesson_dir,
            history=history or None,
        )
        try:
            return outline, validate_outline(outline, segments_data)
        except ValidationError as e:
            last_error = e
            if attempt >= max_repair_attempts:
                raise
            print(f"⚠️  Outline non valida (tentativo {attempt+1}/{max_repair_attempts+1}): {e}\n"
                  f"   Richiedo correzione automatica all'LLM...")
            outline_json = json.dumps(outline.model_dump(mode="json"), ensure_ascii=False, indent=2)
            history = history + [
                {"role": "user", "content": current_prompt},
                {"role": "assistant", "content": outline_json},
            ]
            current_prompt = build_outline_selfrepair_followup_prompt(str(e))
    raise last_error


def run_outline(lesson_dir: str, force: bool = False, force_mock: bool = False) -> Dict[str, Any]:
    """Genera e valida l'outline della lezione."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    topics_val = info.get("argomenti") or None
    
    segments_path = lesson_path(lesson_dir, "segments.json")
    if not os.path.isfile(segments_path):
        raise FileNotFoundError(f"segments.json mancante. Esegui prima 'rt prepare' su '{lesson_dir}'")
        
    segments_data = load_segments_json(segments_path)
    
    # Controllo idempotenza: se valido e non forzato, SKIP immediato senza invocare LLM
    phase_status, reason = check_phase_status(lesson_dir, "outline")
    if phase_status == PhaseStatus.VALID and not force:
        cached_outline = load_outline(lesson_dir)
        validation_report = validate_outline(cached_outline, segments_data)
        return {
            "status": "outline_validated",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "outline_path": get_outline_path(lesson_dir),
            "validation_report": validation_report
        }
        
    action = "FORCE" if force else "RUN"
    
    # Costruzione sommario segmenti per prompt
    summary_lines = []
    for s in segments_data.segments:
        text_preview = " ".join(s.text_raw.split()[:18])
        summary_lines.append(f"[{s.id}] {s.start_formatted} - {s.end_formatted}: {text_preview}")
    segments_summary = "\n".join(summary_lines)
    
    prompt = build_outline_user_prompt(date_val, subject_val, topics_val, segments_summary)
    client = LLMClient(force_mock=force_mock)
    
    outline, validation_report = _generate_validated_outline(
        client, OUTLINE_SYSTEM_PROMPT, [], prompt, segments_data, lesson_dir
    )
    
    # Salvataggio atomico
    save_outline(outline, lesson_dir)
    
    # Registrazione fingerprint e invalidazione downstream
    source_fp = compute_source_fingerprint(lesson_dir, "outline")
    out_hash = compute_file_sha256(get_outline_path(lesson_dir))
    _cfg = load_config()
    _job_cfg = _cfg.jobs.get("outline") or _cfg.llm.get("outline")
    _provenance = {
        "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
        "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
    }
    record_phase_fingerprint(lesson_dir, "outline", source_fp, {"outline.json": out_hash}, metadata=_provenance)
    if force or phase_status == PhaseStatus.STALE:
        mark_downstream_stale(lesson_dir, "outline")
    
    # Aggiornamento manifest e transizione stato
    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        current_state=WorkflowState.OUTLINE_VALIDATED.value,
        coverage_stats=validation_report
    )
    transition_to(yaml_path, WorkflowState.OUTLINE_VALIDATED, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID)))
    
    return {
        "status": "outline_validated",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "outline_path": get_outline_path(lesson_dir),
        "validation_report": validation_report
    }


def run_outline_revision(lesson_dir: str, feedback: str, force_mock: bool = False) -> Dict[str, Any]:
    """Rigenera l'outline incorporando un feedback testuale libero dell'utente.
    A differenza di run_outline(), ignora sempre l'idempotenza: una revisione è
    per definizione una richiesta esplicita dell'utente."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    topics_val = info.get("argomenti") or None

    segments_path = lesson_path(lesson_dir, "segments.json")
    segments_data = load_segments_json(segments_path)

    summary_lines = []
    for s in segments_data.segments:
        text_preview = " ".join(s.text_raw.split()[:18])
        summary_lines.append(f"[{s.id}] {s.start_formatted} - {s.end_formatted}: {text_preview}")
    segments_summary = "\n".join(summary_lines)

    previous_outline = load_outline(lesson_dir)
    previous_outline_json = json.dumps(previous_outline.model_dump(mode="json"), ensure_ascii=False, indent=2)

    original_user_prompt = build_outline_user_prompt(date_val, subject_val, topics_val, segments_summary)
    client = LLMClient(force_mock=force_mock)

    history = [
        {"role": "user", "content": original_user_prompt},
        {"role": "assistant", "content": previous_outline_json},
    ]
    followup_prompt = build_outline_revision_followup_prompt(feedback)
    outline, validation_report = _generate_validated_outline(
        client, OUTLINE_SYSTEM_PROMPT, history, followup_prompt, segments_data, lesson_dir
    )

    save_outline(outline, lesson_dir)

    source_fp = compute_source_fingerprint(lesson_dir, "outline")
    out_hash = compute_file_sha256(get_outline_path(lesson_dir))
    _cfg = load_config()
    _job_cfg = _cfg.jobs.get("outline") or _cfg.llm.get("outline")
    _provenance = {
        "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
        "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
    }
    record_phase_fingerprint(lesson_dir, "outline", source_fp, {"outline.json": out_hash}, metadata=_provenance)
    mark_downstream_stale(lesson_dir, "outline")

    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        current_state=WorkflowState.OUTLINE_VALIDATED.value,
        coverage_stats=validation_report
    )
    transition_to(yaml_path, WorkflowState.OUTLINE_VALIDATED, allow_force=True)

    return {
        "status": "outline_validated",
        "action": "REVISION",
        "skipped": False,
        "outline_path": get_outline_path(lesson_dir),
        "validation_report": validation_report
    }
