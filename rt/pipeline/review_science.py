"""
rt.pipeline.review_science
Fase E: SCIENCE REVIEW (Critic Scientifico Indipendente).
Analizza il draft contro la fonte originale identificando:
- ERR_DOCENTE (lapsus del docente con domanda diplomatica)
- ERR_RECONSTRUCTION (errori introdotti dal modello durante la rielaborazione)
- SCIENCE_CHECK (elementi critici ad alto rischio da verificare)
Salva science_issues.json.
"""

import os
import json
from typing import Dict, Any, List
from rt.core.models import ScienceIssue, ScienceType
from rt.core.segments import load_segments_json
from rt.core.state import transition_to, WorkflowState
from rt.core.manifest import load_manifest
from rt.core.config import load_config
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    SCIENCE_REVIEW_SYSTEM_PROMPT,
    build_science_review_user_prompt,
    ScienceIssueList
)
from rt.pipeline.rewrite import load_draft
from rt.pipeline.review_asr import load_asr_issues
from rt.core.models import ASRLevel
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


def get_science_issues_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "science_issues.json")


def load_science_issues(lesson_dir: str) -> List[ScienceIssue]:
    path = get_science_issues_path(lesson_dir)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        cleaned_data = sanitize_object_encoding(data)
        return [ScienceIssue.model_validate(x) for x in cleaned_data]
    return []


def save_science_issues(issues: List[ScienceIssue], lesson_dir: str) -> None:
    path = get_science_issues_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding([iss.model_dump(mode="json") for iss in issues])
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def check_text_grounding_score(query: str, source_text: str) -> float:
    """
    Calcola un punteggio conservativo di grounding (0.0 - 1.0) tra una frase/citazione
    e la trascrizione sorgente, gestendo variazioni di punteggiatura e parafrasi.
    """
    if not query or not source_text:
        return 0.0
    import re
    q_clean = re.sub(r"[^\w\s]", " ", query.lower()).strip()
    src_clean = re.sub(r"[^\w\s]", " ", source_text.lower()).strip()
    if not q_clean or not src_clean:
        return 0.0
    # Match esatto sottostringa
    if q_clean in src_clean:
        return 1.0
    # Match parole significative (lunghezza >= 4)
    words = [w for w in q_clean.split() if len(w) >= 4]
    if not words:
        words = q_clean.split()
    if not words:
        return 0.0
    matched = sum(1 for w in words if w in src_clean)
    return matched / len(words)


def disambiguate_science_issue(iss: Any, source_text: str) -> Any:
    """
    Applica una classificazione conservativa e basata su prove (grounding)
    per distinguere oggettivamente tra:
    - ERR_DOCENTE: l'errore o lapsus è effettivamente presente nella lezione sorgente.
    - ERR_RECONSTRUCTION: l'errore/allucinazione è stato introdotto dal modello e non ha riscontro nella lezione.
    - SCIENCE_CHECK: affermazione plausibile ma critica o con correlazione parziale/ambigua.
    """
    is_dict = isinstance(iss, dict)
    quote = (iss.get("source_quote") if is_dict else iss.source_quote) or ""
    claim = (iss.get("claim") if is_dict else iss.claim) or ""
    curr_type = iss.get("type") if is_dict else iss.type
    if isinstance(curr_type, ScienceType):
        curr_type = curr_type.value
    curr_reason = (iss.get("reason") or iss.get("explanation", "")) if is_dict else iss.reason
    diplomatic_question = (iss.get("diplomatic_question") if is_dict else iss.diplomatic_question) or ""

    score_quote = check_text_grounding_score(quote, source_text) if quote else 0.0
    score_claim = check_text_grounding_score(claim, source_text) if claim else 0.0
    max_grounding = max(score_quote, score_claim)

    new_type = curr_type
    new_reason = curr_reason
    new_question = diplomatic_question

    if curr_type == ScienceType.ERR_DOCENTE.value:
        if max_grounding >= 0.65:
            # Forte riscontro nella sorgente: confermato lapsus docente
            if not new_question:
                new_question = f"Professore, riguardo a '{claim}', potrebbe confermare se il riferimento inteso è corretto?"
        elif max_grounding <= 0.20:
            # Nessun riscontro nella sorgente: il docente non l'ha mai detto, introdotto dal modello
            new_type = ScienceType.ERR_RECONSTRUCTION.value
            new_reason = f"[AUTO-RECLASSIFIED from ERR_DOCENTE to ERR_RECONSTRUCTION: affermazione non presente nella sorgente] {curr_reason}"
        else:
            # Grounding parziale/ambiguo: non imputare né al docente né al modello
            new_type = ScienceType.SCIENCE_CHECK.value
            new_reason = f"[AUTO-RECLASSIFIED to SCIENCE_CHECK: correlazione parziale con la registrazione] {curr_reason}"

    elif curr_type == ScienceType.ERR_RECONSTRUCTION.value:
        if max_grounding >= 0.75:
            # Il testo contestato (claim, dal draft) ha forte riscontro letterale nella
            # trascrizione originale: non è un'invenzione del modello, il docente l'ha
            # detto (o quasi) così. Usa "claim" (prosa del draft), mai "quote": il critic
            # non ha più accesso alla trascrizione grezza, un'eventuale "quote" prodotta
            # comunque dal modello non è affidabile e non va mai mostrata all'utente.
            new_type = ScienceType.ERR_DOCENTE.value
            if not new_question:
                new_question = f"Professore, riguardo a '{claim}', intendeva confermare questo dettaglio?"

    if is_dict:
        iss["type"] = new_type
        iss["reason"] = new_reason
        iss["explanation"] = new_reason
        if new_question:
            iss["diplomatic_question"] = new_question
    else:
        iss.type = ScienceType(new_type)
        iss.reason = new_reason
        if new_question:
            iss.diplomatic_question = new_question

    return iss


def _localize_claim_segment(claim: str, unit, seg_by_id: dict) -> Optional[str]:
    """Stima il segment_id più vicino al punto in cui 'claim' compare nel testo rielaborato
    dell'unità, mappando proporzionalmente la posizione del carattere sulla durata cumulativa
    dei segmenti sorgente. Approssimazione: non esiste provenance a grana fine tra singole
    frasi rielaborate e segmenti sorgente. Ritorna None se la claim non è rintracciabile
    (nessuna corrispondenza testuale) o se l'unità non ha segmenti sorgente risolvibili."""
    offset = unit.content.find(claim.strip())
    if offset < 0:
        return None
    segs = [seg_by_id[sid] for sid in unit.source_segment_ids if sid in seg_by_id]
    if not segs:
        return None
    ratio = offset / max(1, len(unit.content))
    total_duration = sum(max(0.01, s.end_seconds - s.start_seconds) for s in segs)
    target = ratio * total_duration
    cumulative = 0.0
    for s in segs:
        cumulative += max(0.01, s.end_seconds - s.start_seconds)
        if cumulative >= target:
            return s.id
    return segs[-1].id


def run_review_science(lesson_dir: str, force: bool = False, force_mock: bool = False) -> Dict[str, Any]:
    """Esegue la critica scientifica indipendente sul draft confrontato con l'ASR con checkpointing continuo."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")

    # Nessun avviso o vincolo d'ordine rispetto a review-asr: il critic scientifico non
    # vede più la trascrizione grezza (vedi SCIENCE_REVIEW_SYSTEM_PROMPT), quindi può
    # essere eseguito prima, dopo o senza mai eseguire review-asr, senza rischio di
    # confondere un artefatto ASR con un errore concettuale.
    from rt.pipeline.ledger import load_ledger, apply_asr_decisions_to_text

    manifest_before = load_manifest(lesson_dir)
    old_sci_hash = (
        manifest_before.phase_records.get("review_science", {})
        .get("artifact_fingerprints", {})
        .get("science_issues.json")
        if manifest_before and manifest_before.phase_records
        else None
    )

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "review_science")
    if phase_status == PhaseStatus.VALID and not force:
        all_science_issues = load_science_issues(lesson_dir)
        asr_issues = load_asr_issues(lesson_dir)
        pending_asr = [a for a in asr_issues if a.level in (ASRLevel.YELLOW, ASRLevel.RED) and a.status == "pending"]
        pending_sci = [s for s in all_science_issues if s.status == "pending"]
        next_state = WorkflowState.HUMAN_REVIEW_REQUIRED.value if (pending_asr or pending_sci) else WorkflowState.READY_TO_BUILD.value
        return {
            "status": "science_review_completed",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "total_science_issues": len(all_science_issues),
            "docente_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_DOCENTE),
            "reconstruction_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_RECONSTRUCTION),
            "science_checks": sum(1 for x in all_science_issues if x.type == ScienceType.SCIENCE_CHECK),
            "next_state": next_state,
            "issues_path": get_science_issues_path(lesson_dir)
        }

    action = "FORCE" if force else "RUN"
    
    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in segments_data.segments}

    ledger = load_ledger(lesson_dir)
    decisions_map = {d.issue_id: d for d in ledger.decisions}
    asr_issues = load_asr_issues(lesson_dir)

    # Riconciliazione all'avvio:
    if force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID):
        reviewed_unit_ids = []
        all_science_issues: List[ScienceIssue] = []
        save_science_issues(all_science_issues, lesson_dir)
        if force:
            from rt.pipeline.ledger import purge_decisions_by_prefix
            purge_decisions_by_prefix(lesson_dir, prefix="sci_")
    else:
        ckpt, ckpt_status, ckpt_reason = get_phase_checkpoint(lesson_dir, "review_science")
        existing_issues = load_science_issues(lesson_dir)
        if ckpt and ckpt.get("completed_items"):
            reviewed_unit_ids = list(ckpt["completed_items"])
            reviewed_set = set(reviewed_unit_ids)
            # Riconciliazione: conserva solo le issue di unità committate nel manifest
            cleaned_issues = [iss for iss in existing_issues if iss.unit_id in reviewed_set]
            all_science_issues = cleaned_issues
            if len(cleaned_issues) != len(existing_issues):
                save_science_issues(all_science_issues, lesson_dir)
            if reviewed_unit_ids:
                print(f"🔄 [CHECKPOINT RESUME] {len(reviewed_unit_ids)}/{len(draft.units)} unità didattiche già revisionate per science critic.")
        else:
            reviewed_unit_ids = []
            all_science_issues = []
            save_science_issues(all_science_issues, lesson_dir)
    
    client = LLMClient(force_mock=force_mock)
    reviewed_set = set(reviewed_unit_ids)
    total_units = len(draft.units)
    
    for idx, unit in enumerate(draft.units, start=1):
        if not force and unit.unit_id in reviewed_set:
            continue

        source_texts = []
        for s_id in unit.source_segment_ids:
            s = seg_by_id.get(s_id)
            if s:
                source_texts.append(f"[{s.id}] {s.text_raw}")
        source_context = "\n".join(source_texts)

        unit_content_for_prompt = apply_asr_decisions_to_text(
            unit.content, asr_issues, decisions_map, unit.source_segment_ids
        )
        prompt = build_science_review_user_prompt(
            unit_id=unit.unit_id,
            rewritten_content=unit_content_for_prompt,
        )
        
        unit_title = unit.title.strip() if getattr(unit, "title", None) else ""
        if len(unit_title) > 28:
            unit_title = unit_title[:25] + "..."
        unit_label = f"unit {idx}/{total_units} ({unit.unit_id}: {unit_title})" if unit_title else f"unit {idx}/{total_units} ({unit.unit_id})"

        res = client.call_structured(
            prompt=prompt,
            system_prompt=SCIENCE_REVIEW_SYSTEM_PROMPT,
            response_model=ScienceIssueList,
            job_name="review_science",
            unit_id=unit_label,
            min_elapsed_seconds=5.0,
            lesson_dir=lesson_dir
        )
        
        for iss in res.issues:
            iss.unit_id = unit.unit_id
            if not iss.segment_id:
                iss.segment_id = _localize_claim_segment(iss.claim, unit, seg_by_id)
            if not force_mock:
                iss = disambiguate_science_issue(iss, source_context)
            all_science_issues.append(iss)
            
        # Numerazione deterministica progressiva
        for s_idx, iss in enumerate(all_science_issues, start=1):
            iss.id = f"sci_{s_idx:06d}"
            
        # Salvataggio atomico dell'artefatto su disco
        save_science_issues(all_science_issues, lesson_dir)

        # Commit atomico nel checkpoint
        if unit.unit_id not in reviewed_set:
            reviewed_unit_ids.append(unit.unit_id)
            reviewed_set.add(unit.unit_id)

        source_fp = compute_source_fingerprint(lesson_dir, "review_science")
        sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))
        record_phase_checkpoint(
            lesson_dir=lesson_dir,
            phase_name="review_science",
            source_fingerprint=source_fp,
            artifact_fingerprints={"science_issues.json": sci_hash},
            completed_items=reviewed_unit_ids
        )

    # Finalizzazione se tutte le unità del draft sono state esaminate
    all_draft_unit_ids = [u.unit_id for u in draft.units]
    is_fully_reviewed = all(uid in reviewed_set for uid in all_draft_unit_ids)

    if is_fully_reviewed:
        for s_idx, iss in enumerate(all_science_issues, start=1):
            iss.id = f"sci_{s_idx:06d}"
        save_science_issues(all_science_issues, lesson_dir)

        source_fp = compute_source_fingerprint(lesson_dir, "review_science")
        sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))

        _cfg = load_config()
        _job_cfg = _cfg.jobs.get("review_science") or _cfg.llm.get("review_science")
        _provenance = {
            "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
            "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
        }

        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name="review_science",
            source_fingerprint=source_fp,
            artifact_fingerprints={"science_issues.json": sci_hash},
            metadata=_provenance,
        )
        if (force or phase_status == PhaseStatus.STALE) and (old_sci_hash is None or old_sci_hash != sci_hash):
            mark_downstream_stale(lesson_dir, "review_science")

        
        asr_issues = load_asr_issues(lesson_dir)
        pending_asr = [a for a in asr_issues if a.level in (ASRLevel.YELLOW, ASRLevel.RED) and a.status == "pending"]
        pending_sci = [s for s in all_science_issues if s.status == "pending"]
        
        allow_t = force or (phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID, PhaseStatus.PARTIAL))
        if pending_asr or pending_sci:
            transition_to(yaml_path, WorkflowState.HUMAN_REVIEW_REQUIRED, allow_force=allow_t)
            next_state = WorkflowState.HUMAN_REVIEW_REQUIRED.value
        else:
            transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=allow_t)
            next_state = WorkflowState.READY_TO_BUILD.value
        status_msg = "science_review_completed"
    else:
        next_state = "partial"
        status_msg = "science_review_partial"

    return {
        "status": status_msg,
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "total_science_issues": len(all_science_issues),
        "docente_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_DOCENTE),
        "reconstruction_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_RECONSTRUCTION),
        "science_checks": sum(1 for x in all_science_issues if x.type == ScienceType.SCIENCE_CHECK),
        "next_state": next_state,
        "issues_path": get_science_issues_path(lesson_dir)
    }
