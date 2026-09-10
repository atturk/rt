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
from rt.core.models import ASRIssue, ASRLevel
from rt.core.segments import load_segments_json
from rt.core.config import load_config
from rt.core.manifest import load_manifest
from rt.core.state import transition_to, WorkflowState
from rt.core.lesson_paths import lesson_path
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
    record_phase_checkpoint,
    get_phase_checkpoint,
    mark_downstream_stale,
)


def get_asr_issues_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "asr_issues.json")


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


def run_review_asr(
    lesson_dir: str,
    force: bool = False,
    force_mock: bool = False,
    batch_size: int = 40
) -> Dict[str, Any]:
    """Esegue la revisione fonetica ASR con confidence gating deterministico e checkpointing continuo."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    config = load_config()

    manifest_before = load_manifest(lesson_dir)
    old_asr_hash = (
        manifest_before.phase_records.get("review_asr", {})
        .get("artifact_fingerprints", {})
        .get("asr_issues.json")
        if manifest_before and manifest_before.phase_records
        else None
    )

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

    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_idx_map = {s.id: s.index for s in segments_data.segments}

    # Mappa segment_id -> unità didattica del draft che lo copre, per dare a ogni batch
    # il testo del draft corrispondente (vedi ASR_REVIEW_SYSTEM_PROMPT: le issue riguardano
    # il testo come compare ora nel draft, non la trascrizione grezza in sé).
    from rt.pipeline.rewrite import load_draft
    draft = load_draft(lesson_dir)
    unit_by_segment = {}
    for u in draft.units:
        for sid in u.source_segment_ids:
            unit_by_segment[sid] = u

    total_segments = len(segments_data.segments)
    total_batches = max(1, (total_segments + batch_size - 1) // batch_size)

    # Riconciliazione all'avvio:
    if force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID):
        completed_batches: List[str] = []
        all_issues: List[ASRIssue] = []
        save_asr_issues(all_issues, lesson_dir)
        if force:
            from rt.pipeline.ledger import purge_decisions_by_prefix
            purge_decisions_by_prefix(lesson_dir, prefix="asr_")
    else:
        ckpt, ckpt_status, ckpt_reason = get_phase_checkpoint(lesson_dir, "review_asr")
        existing_issues = load_asr_issues(lesson_dir)
        if ckpt and ckpt.get("completed_items"):
            completed_batches = list(ckpt["completed_items"])
            
            # Estrae gli intervalli di segmenti dei batch committati
            committed_seg_ranges = []
            for b_id in completed_batches:
                parts = b_id.split("_")
                # format: batch_001_seg_000001_seg_000040
                if len(parts) >= 6:
                    s_start = f"{parts[2]}_{parts[3]}"
                    s_end = f"{parts[4]}_{parts[5]}"
                    if s_start in seg_idx_map and s_end in seg_idx_map:
                        committed_seg_ranges.append((seg_idx_map[s_start], seg_idx_map[s_end]))

            def is_seg_in_committed(seg_id: str) -> bool:
                if seg_id not in seg_idx_map:
                    return False
                idx = seg_idx_map[seg_id]
                return any(start <= idx <= end for start, end in committed_seg_ranges)

            cleaned_issues = [iss for iss in existing_issues if is_seg_in_committed(iss.segment_id)]
            all_issues = cleaned_issues
            if len(cleaned_issues) != len(existing_issues):
                save_asr_issues(all_issues, lesson_dir)

            # Riconciliazione Ledger: assicura che ogni issue GREEN committata sia registrata nel ledger
            from rt.pipeline.ledger import load_ledger
            curr_ledger = load_ledger(lesson_dir)
            recorded_dec_ids = {d.issue_id for d in curr_ledger.decisions}
            for iss in all_issues:
                if iss.level == ASRLevel.GREEN and iss.id not in recorded_dec_ids:
                    record_decision(
                        lesson_dir=lesson_dir,
                        issue_id=iss.id,
                        decision="accepted",
                        resolved_text=iss.candidate,
                        resolved_by="auto_green",
                        notes=f"Auto-applicata confidenza alta ({iss.confidence:.2f})"
                    )

            if completed_batches:
                print(f"🔄 [CHECKPOINT RESUME] {len(completed_batches)}/{total_batches} batch ASR già verificati e riconciliati nel ledger.")
        else:
            completed_batches = []
            all_issues = []
            save_asr_issues(all_issues, lesson_dir)
    
    client = LLMClient(force_mock=force_mock)
    
    for idx, i in enumerate(range(0, total_segments, batch_size), start=1):
        batch = segments_data.segments[i : i + batch_size]
        start_seg = i + 1
        end_seg = min(i + batch_size, total_segments)
        batch_id = f"batch_{idx:03d}_{batch[0].id}_{batch[-1].id}"

        if not force and batch_id in completed_batches:
            continue

        batch_label = f"batch {idx:02d}/{total_batches:02d} (seg {start_seg}-{end_seg})"
        batch_text = "\n".join(f"[{s.id}] ({s.start_formatted}) {s.text_raw}" for s in batch)

        # Unità didattiche del draft che coprono i segmenti di questo batch (dedup preservando
        # l'ordine di prima apparizione, un'unità può coprire più batch consecutivi).
        covering_units = []
        seen_unit_ids = set()
        for s in batch:
            u = unit_by_segment.get(s.id)
            if u and u.unit_id not in seen_unit_ids:
                covering_units.append(u)
                seen_unit_ids.add(u.unit_id)
        draft_context = "\n\n".join(f"[Unità {u.unit_id} - {u.title}]\n{u.content}" for u in covering_units)

        prompt = build_asr_review_user_prompt(batch_text, draft_context)
        issue_list = client.call_structured(
            prompt=prompt,
            system_prompt=ASR_REVIEW_SYSTEM_PROMPT,
            response_model=ASRIssueList,
            job_name="review_asr",
            unit_id=batch_label,
            min_elapsed_seconds=5.0,
            lesson_dir=lesson_dir
        )
        
        # Applicazione deterministica dei livelli di confidenza da configurazione
        batch_issues: List[ASRIssue] = []
        for iss in issue_list.issues:
            if iss.confidence >= config.thresholds.green:
                iss.level = ASRLevel.GREEN
                iss.status = "accepted"
            elif iss.confidence >= config.thresholds.yellow:
                iss.level = ASRLevel.YELLOW
            else:
                iss.level = ASRLevel.RED
            batch_issues.append(iss)
            
        # Ordinamento canonico deterministico all'interno del batch
        batch_issues.sort(key=lambda x: (seg_idx_map.get(x.segment_id, 0), x.source_text.lower(), x.candidate.lower()))

        # Assegnazione di ID stabili immutabili a partire dall'offset delle issue già committate
        offset = len(all_issues)
        for sub_idx, iss in enumerate(batch_issues, start=1):
            iss.id = f"asr_{offset + sub_idx:06d}"

        all_issues.extend(batch_issues)

        # 1. Salvataggio atomico su disco dell'artefatto
        save_asr_issues(all_issues, lesson_dir)

        # 2. Applicazione idempotente delle decisioni GREEN nel ledger
        for iss in batch_issues:
            if iss.level == ASRLevel.GREEN:
                record_decision(
                    lesson_dir=lesson_dir,
                    issue_id=iss.id,
                    decision="accepted",
                    resolved_text=iss.candidate,
                    resolved_by="auto_green",
                    notes=f"Auto-applicata confidenza alta ({iss.confidence:.2f})"
                )

        # 3. Registrazione Checkpoint nel manifest
        completed_batches.append(batch_id)
        source_fp = compute_source_fingerprint(lesson_dir, "review_asr")
        asr_hash = compute_file_sha256(get_asr_issues_path(lesson_dir))
        record_phase_checkpoint(
            lesson_dir=lesson_dir,
            phase_name="review_asr",
            source_fingerprint=source_fp,
            artifact_fingerprints={"asr_issues.json": asr_hash},
            completed_items=completed_batches,
            metadata={"ledger_reconciled": True}
        )

    is_all_batches_done = len(completed_batches) == total_batches
    if is_all_batches_done:
        source_fp = compute_source_fingerprint(lesson_dir, "review_asr")
        asr_hash = compute_file_sha256(get_asr_issues_path(lesson_dir))

        _cfg = load_config()
        _job_cfg = _cfg.jobs.get("review_asr") or _cfg.llm.get("review_asr")
        _provenance = {
            "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
            "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
        }

        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name="review_asr",
            source_fingerprint=source_fp,
            artifact_fingerprints={"asr_issues.json": asr_hash},
            metadata=_provenance,
        )
        if (force or phase_status == PhaseStatus.STALE) and (old_asr_hash is None or old_asr_hash != asr_hash):
            mark_downstream_stale(lesson_dir, "review_asr")


        transition_to(yaml_path, WorkflowState.ASR_REVIEW_READY, allow_force=(force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID, PhaseStatus.PARTIAL)))
        status_msg = "asr_review_completed"
    else:
        status_msg = "asr_review_partial"
    
    green_count = sum(1 for x in all_issues if x.level == ASRLevel.GREEN)
    yellow_count = sum(1 for x in all_issues if x.level == ASRLevel.YELLOW)
    red_count = sum(1 for x in all_issues if x.level == ASRLevel.RED)
    
    return {
        "status": status_msg,
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "total_issues": len(all_issues),
        "green_auto_applied": green_count,
        "yellow_review_queue": yellow_count,
        "red_human_required": red_count,
        "issues_path": get_asr_issues_path(lesson_dir)
    }
