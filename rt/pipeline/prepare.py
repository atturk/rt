"""
rt.pipeline.prepare
Fase A: PREPARE (Completamente deterministica).
- Convalida la cartella e info.yaml
- Individua la sorgente di trascrizione (JSON o Markdown grezzo)
- Normalizza tutti i timestamp internamente in secondi
- Genera gli ID stabili dei segmenti (seg_000001, ...)
- Crea segments.json e transcript_normalized.md
- Inizializza il manifest.json
- Avanza lo stato a PREPARED
"""

import os
from typing import Dict, Any
from rt.core.segments import (
    parse_segments_from_json,
    parse_segments_from_markdown,
    save_segments_json,
    export_normalized_transcript_md
)
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.core.manifest import init_or_update_manifest
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    mark_downstream_stale,
)
from rt.core.lesson_paths import lesson_path


def run_prepare(lesson_dir: str, force: bool = False) -> Dict[str, Any]:
    """Esegue la fase deterministica di preparazione della lezione."""
    if not os.path.isdir(lesson_dir):
        raise FileNotFoundError(f"Directory della lezione non trovata: '{lesson_dir}'")

    yaml_path = lesson_path(lesson_dir, "info.yaml")
    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(f"File critico 'info.yaml' mancante in '{lesson_dir}'")

    info = read_info_yaml(yaml_path)
    current_state_raw = info.get("fase_corrente", "") or info.get("stato", "")
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    topics_val = info.get("argomenti", "Argomenti")
    audio_file = info.get("file_audio")
    lesson_id = os.path.basename(os.path.abspath(lesson_dir))
    segments_json_path = lesson_path(lesson_dir, "segments.json")
    norm_md_path = lesson_path(lesson_dir, "transcript_normalized.md")

    # Controllo stato METADATA_ONLY: la preparazione non può proseguire senza ASR reale
    json_candidates = [
        lesson_path(lesson_dir, "trascritto grezzo.json"),
        lesson_path(lesson_dir, "segments_raw.json"),
        lesson_path(lesson_dir, "transcript.json"),
    ]
    has_valid_json = any(os.path.isfile(jc) and os.path.getsize(jc) > 10 for jc in json_candidates)
    if current_state_raw in (WorkflowState.METADATA_ONLY.value, "in_attesa_di_trascrizione") and not has_valid_json:
        raise ValueError(
            f"Trascrizione non disponibile per '{lesson_dir}': la lezione è in stato METADATA_ONLY "
            f"(--skip-transcribe). Esegui prima la trascrizione ASR con macparakeet-cli per generare trascritto grezzo.json."
        )

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "prepare")
    if phase_status == PhaseStatus.VALID and not force:
        from rt.core.segments import load_segments_json
        seg_data = load_segments_json(segments_json_path)
        duration = seg_data.segments[-1].end_seconds if seg_data.segments else 0.0
        return {
            "status": "prepared",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "lesson_id": lesson_id,
            "segment_count": len(seg_data.segments),
            "duration_seconds": duration,
            "segments_json": segments_json_path,
            "transcript_normalized_md": norm_md_path
        }

    action = "FORCE" if force else "RUN"
    
    # 1. Ricerca del trascritto sorgente: JSON è la SOURCE OF TRUTH assoluta
    md_path = lesson_path(lesson_dir, "trascritto grezzo.md")
    
    source_type = None
    source_path = None
    
    for jc in json_candidates:
        if os.path.isfile(jc) and os.path.getsize(jc) > 10:
            source_type = "json"
            source_path = jc
            break
            
    if not source_path:
        if os.path.isfile(md_path) and os.path.getsize(md_path) > 10:
            source_type = "markdown"
            source_path = md_path
        else:
            raise FileNotFoundError(
                f"Nessuna sorgente di trascrizione valida trovata in '{lesson_dir}' "
                f"(cercati trascritto grezzo.json e trascritto grezzo.md non vuoti)"
            )
            
    # 2. Parsing deterministico dei segmenti
    if source_type == "json":
        segments = parse_segments_from_json(source_path)
        # Se esiste anche il Markdown, verifichiamo la coerenza per trasparenza diagnostica
        if os.path.isfile(md_path):
            try:
                md_segs = parse_segments_from_markdown(md_path)
                if md_segs and len(md_segs) != len(segments):
                    print(
                        f"⚠️  [AVVISO COERENZA ASR] Rilevata divergenza tra JSON ({len(segments)} segmenti) "
                        f"e Markdown ({len(md_segs)} segmenti). Il file JSON '{os.path.basename(source_path)}' "
                        f"è e rimane l'unica SOURCE OF TRUTH temporale e semantica autoritativa."
                    )
            except Exception:
                pass
    else:
        segments = parse_segments_from_markdown(source_path)
        
    if not segments:
        raise ValueError("Nessun segmento estratto dalla sorgente di trascrizione.")
        
    # 3. Salvataggio atomico di segments.json (Source of truth derivata dal JSON sorgente)
    save_segments_json(segments, segments_json_path, lesson_id=lesson_id)
    
    # 4. Esportazione atomica di transcript_normalized.md
    export_normalized_transcript_md(segments, norm_md_path)
    
    duration = segments[-1].end_seconds if segments else 0.0
    
    # 5. Registrazione fingerprint e invalidazione mirata downstream
    source_fp = compute_source_fingerprint(lesson_dir, "prepare")
    seg_hash = compute_file_sha256(segments_json_path)
    record_phase_fingerprint(lesson_dir, "prepare", source_fp, {"segments.json": seg_hash})
    if force or phase_status == PhaseStatus.STALE:
        mark_downstream_stale(lesson_dir, "prepare")

    # 6. Inizializzazione / aggiornamento del manifest
    manifest = init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        current_state=WorkflowState.PREPARED.value,
        segment_count=len(segments),
        audio_file=audio_file,
        audio_duration_seconds=duration,
        coverage_stats={"total_segments": len(segments), "duration_seconds": duration}
    )
    
    # 7. Avanzamento stato
    transition_to(yaml_path, WorkflowState.PREPARED, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID)))
    
    return {
        "status": "prepared",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "lesson_id": lesson_id,
        "source_type": source_type,
        "source_path": source_path,
        "segment_count": len(segments),
        "duration_seconds": duration,
        "segments_json": segments_json_path,
        "transcript_normalized_md": norm_md_path
    }
