"""
rt.pipeline.review_asr
Fase D: ASR REVIEW (Ambiguità fonetiche e Confidence Gating).
Classifica le anomalie in tre livelli:
- GREEN: confidenza >= soglia_green -> Auto-apply nel ledger con log
- YELLOW: confidenza >= soglia_yellow -> Coda di revisione utente
- RED: confidenza < soglia_yellow -> Revisione obbligatoria con coordinate di ascolto audio
Salva asr_issues.json.
"""

import os
import json
from typing import Dict, Any, List
from rt.core.models import ASRIssue, ASRLevel, SegmentsData
from rt.core.segments import load_segments_json
from rt.core.config import load_config
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.llm.client import LLMClient
from rt.llm.prompts import ASR_REVIEW_SYSTEM_PROMPT, build_asr_review_user_prompt, ASRIssueList
from rt.pipeline.ledger import record_decision


from rt.core.encoding import sanitize_object_encoding
from rt.core.idempotency import (
    PhaseStatus,
    check_phase_status,
    compute_source_fingerprint,
    compute_file_sha256,
    record_phase_fingerprint,
    mark_downstream_stale,
)


def get_asr_issues_path(lesson_dir: str) -> str:
    return os.path.join(lesson_dir, "asr_issues.json")


def load_asr_issues(lesson_dir: str) -> List[ASRIssue]:
    path = get_asr_issues_path(lesson_dir)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        cleaned_data = sanitize_object_encoding(data)
        return [ASRIssue.model_validate(x) for x in cleaned_data]
    return []


def save_asr_issues(issues: List[ASRIssue], lesson_dir: str) -> None:
    path = get_asr_issues_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding([iss.model_dump(mode="json") for iss in issues])
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def run_review_asr(lesson_dir: str, force: bool = False, force_mock: bool = False) -> Dict[str, Any]:
    """Esegue la revisione fonetica ASR con confidence gating deterministico."""
    yaml_path = os.path.join(lesson_dir, "info.yaml")
    config = load_config()

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "review_asr")
    if phase_status == PhaseStatus.VALID and not force:
        issues = load_asr_issues(lesson_dir)
        green_count = sum(1 for x in issues if x.level == ASRLevel.GREEN)
        yellow_count = sum(1 for x in issues if x.level == ASRLevel.YELLOW)
        red_count = sum(1 for x in issues if x.level == ASRLevel.RED)
        return {
            "status": "asr_review_completed",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "total_issues": len(issues),
            "green_auto_applied": green_count,
            "yellow_review_queue": yellow_count,
            "red_human_required": red_count,
            "issues_path": get_asr_issues_path(lesson_dir)
        }

    action = "FORCE" if force else "RUN"
    
    segments_data = load_segments_json(os.path.join(lesson_dir, "segments.json"))
    
    # Raggruppa i segmenti in batch per l'analisi ASR (es. blocchi da 40 segmenti)
    batch_size = 40
    all_issues: List[ASRIssue] = []
    client = LLMClient(force_mock=force_mock)
    
    total_segments = len(segments_data.segments)
    total_batches = max(1, (total_segments + batch_size - 1) // batch_size)
    
    for idx, i in enumerate(range(0, total_segments, batch_size), start=1):
        batch = segments_data.segments[i : i + batch_size]
        start_seg = i + 1
        end_seg = min(i + batch_size, total_segments)
        batch_label = f"batch {idx:02d}/{total_batches:02d} (seg {start_seg}-{end_seg})"
        
        batch_text = "\n".join(f"[{s.id}] ({s.start_formatted}) {s.text_raw}" for s in batch)
        
        prompt = build_asr_review_user_prompt(batch_text)
        issue_list = client.call_structured(
            prompt=prompt,
            system_prompt=ASR_REVIEW_SYSTEM_PROMPT,
            response_model=ASRIssueList,
            job_name="review_asr",
            unit_id=batch_label
        )
        
        # Applicazione deterministica dei livelli di confidenza da configurazione
        for iss in issue_list.issues:
            if iss.confidence >= config.thresholds.green:
                iss.level = ASRLevel.GREEN
                iss.status = "accepted"
            elif iss.confidence >= config.thresholds.yellow:
                iss.level = ASRLevel.YELLOW
            else:
                iss.level = ASRLevel.RED
                
            all_issues.append(iss)
            
    # Assegna ID univoci progressivi deterministici ordinati per segmento
    seg_idx_map = {s.id: s.index for s in segments_data.segments}
    all_issues.sort(key=lambda x: seg_idx_map.get(x.segment_id, 0))
    for idx, iss in enumerate(all_issues, start=1):
        iss.id = f"asr_{idx:06d}"
        if iss.level == ASRLevel.GREEN:
            record_decision(
                lesson_dir=lesson_dir,
                issue_id=iss.id,
                decision="accepted",
                resolved_text=iss.candidate,
                resolved_by="auto_green",
                notes=f"Auto-applicata confidenza alta ({iss.confidence:.2f})"
            )
        
    save_asr_issues(all_issues, lesson_dir)

    # Registrazione fingerprint e invalidazione downstream
    source_fp = compute_source_fingerprint(lesson_dir, "review_asr")
    asr_hash = compute_file_sha256(get_asr_issues_path(lesson_dir))
    record_phase_fingerprint(lesson_dir, "review_asr", source_fp, {"asr_issues.json": asr_hash})
    if force or phase_status == PhaseStatus.STALE:
        mark_downstream_stale(lesson_dir, "review_asr")

    transition_to(yaml_path, WorkflowState.ASR_REVIEW_READY, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID)))
    
    green_count = sum(1 for x in all_issues if x.level == ASRLevel.GREEN)
    yellow_count = sum(1 for x in all_issues if x.level == ASRLevel.YELLOW)
    red_count = sum(1 for x in all_issues if x.level == ASRLevel.RED)
    
    return {
        "status": "asr_review_completed",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "total_issues": len(all_issues),
        "green_auto_applied": green_count,
        "yellow_review_queue": yellow_count,
        "red_human_required": red_count,
        "issues_path": get_asr_issues_path(lesson_dir)
    }
