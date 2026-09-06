"""
rt.pipeline.rewrite
Fase C: REWRITE (Rielaborazione a finestre con memoria di contesto e provenance).
Ogni unità riceve:
- Segmenti principali (da rielaborare)
- Contesto precedente (per tenere il filo)
- Contesto successivo (per transizione naturale)
- Outline globale
- Glossario
Salva draft.json garantendo l'integrità della provenance (source_segment_ids).
"""

import os
import json
from typing import Dict, Any, List, Optional
from rt.core.models import Draft, DraftUnit, Outline, SegmentsData, Segment
from rt.core.segments import load_segments_json
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.core.manifest import init_or_update_manifest
from rt.llm.client import LLMClient
from rt.llm.prompts import REWRITE_SYSTEM_PROMPT, build_rewrite_user_prompt
from rt.pipeline.outline import load_outline
from rt.pipeline.validator import validate_draft


from rt.core.encoding import sanitize_object_encoding
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    mark_downstream_stale,
)


def get_draft_path(lesson_dir: str) -> str:
    return os.path.join(lesson_dir, "draft.json")


def load_draft(lesson_dir: str) -> Draft:
    path = get_draft_path(lesson_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"draft.json non trovato in '{lesson_dir}'")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cleaned_data = sanitize_object_encoding(data)
    return Draft.model_validate(cleaned_data)


def save_draft(draft: Draft, lesson_dir: str) -> None:
    path = get_draft_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding(draft.model_dump(mode="json"))
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def run_rewrite(
    lesson_dir: str,
    target_unit_id: Optional[str] = None,
    force: bool = False,
    force_mock: bool = False
) -> Dict[str, Any]:
    """Esegue la rielaborazione delle unità didattiche a finestre scorrevoli."""
    yaml_path = os.path.join(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    
    outline = load_outline(lesson_dir)
    segments_data = load_segments_json(os.path.join(lesson_dir, "segments.json"))
    
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    all_segments = segments_data.segments
    
    # Carica o inizializza draft
    draft_path = get_draft_path(lesson_dir)
    if os.path.isfile(draft_path):
        draft = load_draft(lesson_dir)
    else:
        draft = Draft(schema_version="1.0", lesson_id=os.path.basename(os.path.abspath(lesson_dir)), units=[])
        
    draft_units_map = {u.unit_id: u for u in draft.units}
    
    # Controllo idempotenza: se valido e non forzato, SKIP immediato senza chiamate LLM
    phase_status, reason = check_phase_status(lesson_dir, "rewrite", target_unit_id=target_unit_id)
    if phase_status == PhaseStatus.VALID and not force:
        validation_report = validate_draft(draft, outline, segments_data)
        return {
            "status": "draft_validated",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "processed_units": 0,
            "total_units": len(draft.units),
            "validation_report": validation_report
        }

    action = "FORCE" if force else "RUN"
    
    # Costruisci sommario globale dell'outline per il contesto del modello
    outline_summary_lines = []
    for macro in outline.macro_sections:
        outline_summary_lines.append(f"Capitolo {macro.id}: {macro.title}")
        for u in macro.units:
            outline_summary_lines.append(f"  - {u.id} {u.title}")
    outline_summary = "\n".join(outline_summary_lines)
    
    client = LLMClient(force_mock=force_mock)
    
    # Raccogli le unità dell'outline che necessitano di generazione
    units_to_process = []
    for macro in outline.macro_sections:
        for u in macro.units:
            if target_unit_id is not None:
                if u.id == target_unit_id:
                    units_to_process.append(u)
            else:
                # Se non forzato e l'unità è già presente e non vuota con provenance integra, possiamo riutilizzarla
                if not force and u.id in draft_units_map:
                    existing_u = draft_units_map[u.id]
                    if existing_u.content.strip() and existing_u.source_segment_ids:
                        continue
                units_to_process.append(u)
                
    processed_count = 0
    total_units_count = len(units_to_process)
    
    for idx, u in enumerate(units_to_process, start=1):
        start_seg = seg_by_id[u.start_segment_id]
        end_seg = seg_by_id[u.end_segment_id]
        
        # Segmenti principali: dal start_seg.index al end_seg.index (inclusi)
        main_segs = all_segments[start_seg.index - 1 : end_seg.index]
        main_seg_ids = [s.id for s in main_segs]
        main_text = "\n".join(f"[{s.id}] ({s.start_formatted}) {s.text_raw}" for s in main_segs)
        
        # Contesto precedente (fino a 10 segmenti o 90 secondi prima)
        prev_idx_start = max(0, start_seg.index - 1 - 8)
        prev_segs = all_segments[prev_idx_start : start_seg.index - 1]
        prev_text = "\n".join(s.text_raw for s in prev_segs)
        
        # Contesto successivo (fino a 8 segmenti dopo)
        next_idx_end = min(len(all_segments), end_seg.index + 8)
        next_segs = all_segments[end_seg.index : next_idx_end]
        next_text = "\n".join(s.text_raw for s in next_segs)
        
        prompt = build_rewrite_user_prompt(
            unit_id=u.id,
            unit_title=u.title,
            main_segments_text=main_text,
            main_segment_ids=main_seg_ids,
            prev_context=prev_text,
            next_context=next_text,
            outline_summary=outline_summary
        )
        
        u_title = u.title.strip() if getattr(u, "title", None) else ""
        if len(u_title) > 28:
            u_title = u_title[:25] + "..."
        unit_label = f"unit {idx}/{total_units_count} ({u.id}: {u_title})" if u_title else f"unit {idx}/{total_units_count} ({u.id})"

        unit_draft = client.call_structured(
            prompt=prompt,
            system_prompt=REWRITE_SYSTEM_PROMPT,
            response_model=DraftUnit,
            job_name="rewrite",
            unit_id=unit_label
        )

        # Forziamo comunque la rispondenza della provenance ai segmenti assegnati
        unit_draft.start_segment_id = u.start_segment_id
        unit_draft.end_segment_id = u.end_segment_id
        unit_draft.unit_id = u.id
        if not unit_draft.source_segment_ids:
            unit_draft.source_segment_ids = main_seg_ids
        else:
            # Filtra solo i segmenti validi ed entro l'intervallo outline dell'unità [start .. end]
            start_idx = seg_by_id[u.start_segment_id].index
            end_idx = seg_by_id[u.end_segment_id].index
            valid_ids = [
                s_id for s_id in unit_draft.source_segment_ids
                if s_id in seg_by_id and start_idx <= seg_by_id[s_id].index <= end_idx
            ]
            # Ordina rigorosamente per indice temporale ed elimina duplicati
            valid_ids.sort(key=lambda s_id: seg_by_id[s_id].index)
            seen_s = set()
            dedup_ids = []
            for s_id in valid_ids:
                if s_id not in seen_s:
                    dedup_ids.append(s_id)
                    seen_s.add(s_id)
            unit_draft.source_segment_ids = dedup_ids if dedup_ids else main_seg_ids
            
        draft_units_map[u.id] = unit_draft
        processed_count += 1
        
    # Ordina le unità secondo l'ordine dell'outline
    ordered_units = []
    for macro in outline.macro_sections:
        for u in macro.units:
            if u.id in draft_units_map:
                ordered_units.append(draft_units_map[u.id])
                
    draft.units = ordered_units
    
    # Validazione deterministica
    validation_report = validate_draft(draft, outline, segments_data)

    # Salvataggio atomico
    save_draft(draft, lesson_dir)

    # Registrazione fingerprint e invalidazione mirata downstream
    source_fp = compute_source_fingerprint(lesson_dir, "rewrite", target_unit_id=target_unit_id)
    draft_hash = compute_file_sha256(draft_path)
    record_phase_fingerprint(
        lesson_dir=lesson_dir,
        phase_name="rewrite",
        source_fingerprint=source_fp,
        artifact_fingerprints={"draft.json": draft_hash},
        unit_id=target_unit_id
    )
    # Invalida solo ciò che dipende da questo draft (o questa unità)
    if force or phase_status == PhaseStatus.STALE or processed_count > 0:
        mark_downstream_stale(lesson_dir, "rewrite", target_unit_id=target_unit_id)
    
    # Aggiornamento stato
    init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
        date=info.get("data", "0000-00-00"),
        subject=info.get("materia", "MATERIA"),
        topics=info.get("argomenti", "Argomenti"),
        current_state=WorkflowState.DRAFT_VALIDATED.value
    )
    transition_to(yaml_path, WorkflowState.DRAFT_VALIDATED, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID)))
    
    return {
        "status": "draft_validated",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else f"processed {processed_count} unit(s)",
        "processed_units": processed_count,
        "total_units": len(draft.units),
        "validation_report": validation_report
    }
