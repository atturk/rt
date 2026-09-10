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
from typing import Dict, Any, List, Optional, Tuple
from rt.core.models import Draft, DraftUnit, Segment
from rt.core.segments import load_segments_json
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.core.manifest import load_manifest, init_or_update_manifest
from rt.core.config import load_config
from rt.llm.client import LLMClient
from rt.llm.prompts import REWRITE_SYSTEM_PROMPT, build_rewrite_user_prompt
from rt.pipeline.outline import load_outline
from rt.pipeline.validator import validate_draft
from rt.core.lesson_paths import lesson_path


from rt.core.encoding import sanitize_object_encoding
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


def get_draft_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "draft.json")


def load_draft(lesson_dir: str) -> Draft:
    path = get_draft_path(lesson_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"draft.json non trovato in {lesson_dir}")
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


def extract_context_window(
    all_segments: List[Segment],
    start_seg: Segment,
    end_seg: Segment,
    window_seconds: float = 90.0,
    max_segments: int = 20
) -> Tuple[List[Segment], List[Segment]]:
    """
    Estrae deterministicamente i segmenti di contesto precedente e successivo
    basandosi sulla durata temporale (~90 secondi), con un tetto massimo di segmenti (20)
    per prevenire finestre sproporzionate in caso di segmenti ASR molto brevi.
    """
    prev_segs: List[Segment] = []
    cur_prev_idx = start_seg.index - 2  # 0-indexed per il segmento precedente
    while cur_prev_idx >= 0 and len(prev_segs) < max_segments:
        cand = all_segments[cur_prev_idx]
        if (start_seg.start_seconds - cand.start_seconds) > window_seconds:
            break
        prev_segs.append(cand)
        cur_prev_idx -= 1
    prev_segs.reverse()

    next_segs: List[Segment] = []
    cur_next_idx = end_seg.index  # 0-indexed per il segmento successivo
    while cur_next_idx < len(all_segments) and len(next_segs) < max_segments:
        cand = all_segments[cur_next_idx]
        if (cand.end_seconds - end_seg.end_seconds) > window_seconds:
            break
        next_segs.append(cand)
        cur_next_idx += 1

    return prev_segs, next_segs


def run_rewrite(
    lesson_dir: str,
    target_unit_id: Optional[str] = None,
    force: bool = False,
    force_mock: bool = False
) -> Dict[str, Any]:
    """Esegue la rielaborazione delle unità didattiche a finestre scorrevoli con checkpointing continuo."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)

    outline = load_outline(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    all_segments = segments_data.segments
    all_outline_units = [u for m in outline.macro_sections for u in m.units]
    outline_units_map = {u.id: u for u in all_outline_units}

    # Carica o inizializza draft
    draft_path = get_draft_path(lesson_dir)
    if os.path.isfile(draft_path):
        try:
            draft = load_draft(lesson_dir)
        except Exception:
            draft = Draft(schema_version="1.0", lesson_id=os.path.basename(os.path.abspath(lesson_dir)), units=[])
    else:
        draft = Draft(schema_version="1.0", lesson_id=os.path.basename(os.path.abspath(lesson_dir)), units=[])
        
    draft_units_map = {u.unit_id: u for u in draft.units}
    
    manifest_before = load_manifest(lesson_dir)
    old_draft_hash = (
        manifest_before.phase_records.get("rewrite", {})
        .get("artifact_fingerprints", {})
        .get("draft.json")
        if manifest_before and manifest_before.phase_records
        else None
    )

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

    # Riconciliazione all'avvio:
    # Se force=True (globale) o se gli input sono STALE o INVALID, non riutilizzare il vecchio draft.json
    if (force and not target_unit_id) or (phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID) and not target_unit_id):
        draft = Draft(schema_version="1.0", lesson_id=os.path.basename(os.path.abspath(lesson_dir)), units=[])
        draft_units_map = {}
    else:
        # Se PARTIAL o recupero checkpoint: verifichiamo la coerenza di ciò che è committato
        ckpt, ckpt_status, ckpt_reason = get_phase_checkpoint(lesson_dir, "rewrite")
        if ckpt and ckpt.get("completed_items"):
            committed_ids = set(ckpt["completed_items"])
            filtered_map = {}
            for u in draft.units:
                if u.unit_id in committed_ids and u.content.strip() and u.source_segment_ids:
                    # Verifica che appartenga all'outline corrente con coordinate coerenti
                    if u.unit_id in outline_units_map:
                        filtered_map[u.unit_id] = u
            draft_units_map = filtered_map
            # Ricostruisce ordinamento e ripulisce draft se necessario
            ordered_units = [draft_units_map[ou.id] for ou in all_outline_units if ou.id in draft_units_map]
            draft.units = ordered_units
            if len(draft.units) != len(draft_units_map) or (os.path.isfile(draft_path) and compute_file_sha256(draft_path) != ckpt.get("artifact_fingerprints", {}).get("draft.json")):
                save_draft(draft, lesson_dir)
            if draft_units_map:
                print(f"🔄 [CHECKPOINT RESUME] {len(draft_units_map)}/{len(all_outline_units)} unità didattiche già completate e verificate.")
        else:
            draft = Draft(schema_version="1.0", lesson_id=os.path.basename(os.path.abspath(lesson_dir)), units=[])
            draft_units_map = {}

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
        
        # Contesto temporale basato su ~90s (precedente e successivo, max 20 segmenti)
        prev_segs, next_segs = extract_context_window(
            all_segments=all_segments,
            start_seg=start_seg,
            end_seg=end_seg,
            window_seconds=90.0,
            max_segments=20
        )
        prev_text = "\n".join(s.text_raw for s in prev_segs)
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
            unit_id=unit_label,
            lesson_dir=lesson_dir
        )

        # Forziamo rigorosamente la rispondenza della provenance prima del commit
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

        # Ordinamento canonico e checkpoint atomico su disco
        ordered_units = [draft_units_map[ou.id] for ou in all_outline_units if ou.id in draft_units_map]
        draft.units = ordered_units
        save_draft(draft, lesson_dir)

        source_fp = compute_source_fingerprint(lesson_dir, "rewrite")
        draft_hash = compute_file_sha256(draft_path)
        record_phase_checkpoint(
            lesson_dir=lesson_dir,
            phase_name="rewrite",
            source_fingerprint=source_fp,
            artifact_fingerprints={"draft.json": draft_hash},
            completed_items=[ou.unit_id for ou in draft.units]
        )
        
    # Verifica stato finale
    ordered_units = [draft_units_map[ou.id] for ou in all_outline_units if ou.id in draft_units_map]
    draft.units = ordered_units

    all_outline_uids = [ou.id for ou in all_outline_units]
    is_fully_covered = all(uid in draft_units_map for uid in all_outline_uids)

    if target_unit_id:
        source_fp = compute_source_fingerprint(lesson_dir, "rewrite", target_unit_id=target_unit_id)
        draft_hash = compute_file_sha256(draft_path)
        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name="rewrite",
            source_fingerprint=source_fp,
            artifact_fingerprints={"draft.json": draft_hash},
            unit_id=target_unit_id
        )
        if force or processed_count > 0:
            mark_downstream_stale(lesson_dir, "rewrite", target_unit_id=target_unit_id)

        if is_fully_covered:
            validation_report = validate_draft(draft, outline, segments_data)
            init_or_update_manifest(
                lesson_dir=lesson_dir,
                lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
                date=info.get("data", "0000-00-00"),
                subject=info.get("materia", "MATERIA"),
                topics=info.get("argomenti", "Argomenti"),
                current_state=WorkflowState.DRAFT_VALIDATED.value
            )
            transition_to(yaml_path, WorkflowState.DRAFT_VALIDATED, allow_force=True)
            status_msg = "draft_validated"
        else:
            validation_report = {"valid": True, "note": f"Unità {target_unit_id} rigenerata, draft complessivo parziale"}
            status_msg = "unit_regenerated"
    elif is_fully_covered:
        validation_report = validate_draft(draft, outline, segments_data)
        source_fp = compute_source_fingerprint(lesson_dir, "rewrite")
        draft_hash = compute_file_sha256(draft_path)

        _cfg = load_config()
        _job_cfg = _cfg.jobs.get("rewrite") or _cfg.llm.get("rewrite")
        _provenance = {
            "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
            "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
        }

        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name="rewrite",
            source_fingerprint=source_fp,
            artifact_fingerprints={"draft.json": draft_hash},
            metadata=_provenance,
        )
        if (force or phase_status == PhaseStatus.STALE or processed_count > 0) and (old_draft_hash is None or old_draft_hash != draft_hash):
            mark_downstream_stale(lesson_dir, "rewrite")



        
        init_or_update_manifest(
            lesson_dir=lesson_dir,
            lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
            date=info.get("data", "0000-00-00"),
            subject=info.get("materia", "MATERIA"),
            topics=info.get("argomenti", "Argomenti"),
            current_state=WorkflowState.DRAFT_VALIDATED.value
        )
        transition_to(yaml_path, WorkflowState.DRAFT_VALIDATED, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID)))
        status_msg = "draft_validated"
    else:
        validation_report = {"valid": False, "reason": "Draft parziale"}
        status_msg = "draft_partial"
    
    return {
        "status": status_msg,
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else f"processed {processed_count} unit(s)",
        "processed_units": processed_count,
        "total_units": len(draft.units),
        "validation_report": validation_report
    }

