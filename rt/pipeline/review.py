"""
rt.pipeline.review
Fase E: REVIEW (Critic Scientifico Indipendente).
Analizza il draft rielaborato identificando:
- ERR_CONCETTUALE (incongruenze scientifiche ed errori concettuali nel rielaborato)
Salva science_issues.json.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity, DraftUnit
from rt.core.segments import load_segments_json
from rt.core.state import transition_to, WorkflowState
from rt.core.manifest import load_manifest
from rt.core.config import load_config, JevConfig
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    SCIENCE_REVIEW_SYSTEM_PROMPT,
    build_science_review_user_prompt,
    ScienceIssueList
)
from rt.pipeline.rewrite import load_draft
from rt.core.lesson_paths import lesson_path
from rt.core.asr_risk import detect_statistical_asr_risks
from rt.llm.jev_client import call_jev, JevChoiceQuestion, JevNoulQuestion, JevError


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
from rt.services.context import RunContext, phase_scope
from rt.storage import fs

LOG = logging.getLogger(__name__)


def get_science_issues_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "science_issues.json")


LEGACY_TYPE_MAP = {
    "ERR_DOCENTE": "ERR_CONCETTUALE",
    "ERR_RECONSTRUCTION": "ERR_CONCETTUALE",
    "SCIENCE_CHECK": "ERR_CONCETTUALE",
}


def load_science_issues(lesson_dir: str) -> List[ScienceIssue]:
    path = get_science_issues_path(lesson_dir)
    if not fs.isfile(path):
        return []
    with fs.open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        cleaned_data = sanitize_object_encoding(data)
        migrated_data = []
        for x in cleaned_data:
            if isinstance(x, dict):
                item = dict(x)
                raw_type = item.get("type")
                if raw_type in LEGACY_TYPE_MAP:
                    item["type"] = LEGACY_TYPE_MAP[raw_type]
                migrated_data.append(item)
            else:
                migrated_data.append(x)
        return [ScienceIssue.model_validate(x) for x in migrated_data]
    return []


def save_science_issues(issues: List[ScienceIssue], lesson_dir: str) -> None:
    path = get_science_issues_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding([iss.model_dump(mode="json") for iss in issues])
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)


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


def _validated_review_issues(client: LLMClient, unit: DraftUnit, prompt: str,
                             lesson_dir: str, unit_label: str,
                             max_repair_attempts: int = 2) -> List[ScienceIssue]:
    """Non persiste claim concettuali che non sono nel draft esaminato dal critic."""
    result = client.call_structured(
        prompt=prompt, system_prompt=SCIENCE_REVIEW_SYSTEM_PROMPT,
        response_model=ScienceIssueList, job_name="review", unit_id=unit_label,
        min_elapsed_seconds=5.0, lesson_dir=lesson_dir,
    )
    issues = list(result.issues)
    for index, issue in enumerate(issues):
        if issue.type != ScienceType.ERR_CONCETTUALE:
            continue
        for attempt in range(max_repair_attempts + 1):
            claim = issue.claim.strip()
            if claim and claim in unit.content:
                issue.claim = claim
                break
            if attempt == max_repair_attempts:
                # Conserviamo l'oggetto per renderlo auditabile, ma il livello web/CLI
                # lo tratta come non applicabile: nessuna decisione può modificarlo.
                # La sidebar lo esclude dall'elenco operativo e mostra il conteggio
                # con il collegamento al JSON completo.
                LOG.error("Review unità %s: claim issue %s non ancorabile dopo %s tentativi; issue marcata come orfana",
                          unit.unit_id, index + 1, max_repair_attempts)
                break
            LOG.warning("Claim review non ancorabile, unità %s issue %s: tentativo di correzione %s/%s",
                        unit.unit_id, index + 1, attempt + 1, max_repair_attempts)
            repair_prompt = (
                "Correggi SOLTANTO il campo claim della singola issue seguente. "
                "Deve essere una sottostringa letteralmente identica e contigua del "
                "TESTO RIELABORATO, completa abbastanza da identificare il punto. "
                "Conserva tipo, gravità, motivazione e proposta; restituisci "
                "ScienceIssueList con esattamente questa unica issue. "
                "Se la tua critica non riguarda il testo fornito, non inventare una citazione.\n\n"
                f"UNITÀ: {unit.unit_id}\nTESTO RIELABORATO:\n{unit.content}\n\n"
                f"ISSUE DA RIPARARE:\n{json.dumps(issue.model_dump(mode='json'), ensure_ascii=False)}"
            )
            repaired = client.call_structured(
                prompt=repair_prompt, system_prompt=SCIENCE_REVIEW_SYSTEM_PROMPT,
                response_model=ScienceIssueList, job_name="review", unit_id=unit_label,
                lesson_dir=lesson_dir,
            )
            if len(repaired.issues) != 1 or repaired.issues[0].type != issue.type:
                continue
            candidate = repaired.issues[0]
            # Il job di correzione può cambiare solo l'ancora, mai il contenuto della critica.
            issue.claim = candidate.claim
    return issues


# -----------------------------------------------------------------------
# Pre-filtro Jev (System One di typesafe.ai): due valutazioni indipendenti per unità,
# ENTRAMBE eseguite (se abilitate) PRIMA della critica scientifica LLM completa.
# -----------------------------------------------------------------------

class JevTaskAVerdict:
    """Esito del Task A (correttezza scientifica): Jev vede SOLO il testo rielaborato."""

    def __init__(self, choice: str, confidence: float, should_skip_expensive_llm: bool):
        self.choice = choice
        self.confidence = confidence
        self.should_skip_expensive_llm = should_skip_expensive_llm


class JevTaskBVerdict:
    """Esito del Task B (coerenza rielaborazione/trascritto grezzo)."""

    def __init__(self, noul_probability: float, is_high_confidence_drift: bool):
        self.noul_probability = noul_probability
        self.is_high_confidence_drift = is_high_confidence_drift


def run_jev_task_a(unit: DraftUnit, jev_cfg: JevConfig, lesson_dir: str) -> Optional[JevTaskAVerdict]:
    """
    Chiede a Jev di classificare la correttezza scientifica dell'unità, vedendo SOLO il
    testo rielaborato (mai il trascritto grezzo, per non contaminare il giudizio con
    considerazioni sulla fedeltà ASR, di competenza del Task B).
    Ritorna None se la chiamata fallisce: fallback prudente, nessuno skip verrà applicato.
    """
    try:
        resp = call_jev(
            state=unit.content,
            questions={
                "correttezza": JevChoiceQuestion(
                    instructions=(
                        "Sei un revisore scientifico che classifica un singolo paragrafo di prosa "
                        "accademica (già rielaborato da una trascrizione di lezione universitaria) "
                        "in base alla gravità di eventuali errori scientifici presenti, SENZA accesso "
                        "alla trascrizione originale. Non correggere il testo: classifica solo la "
                        "gravità di ciò che vi leggi. Ignora eventuali refusi isolati o termini "
                        "graficamente sospetti che sembrano artefatti di trascrizione automatica (ASR) "
                        "non ancora corretti: non è compito tuo, e non contano come errore scientifico "
                        "se isolati e privi di altro significato rilevante."
                    ),
                    criteria={
                        "corretta": (
                            "Il testo è scientificamente corretto, oppure contiene al più imprecisioni "
                            "terminologiche irrilevanti che non cambiano il significato concettuale."
                        ),
                        "imprecisione": (
                            "Il testo contiene una semplificazione o approssimazione minore, di nessuna "
                            "reale conseguenza per la preparazione dell'esame — ad esempio una "
                            "generalizzazione innocua o un dettaglio tecnico secondario reso in modo "
                            "impreciso (es. descrivere come lo stesso enzima due isoforme distinte che "
                            "catalizzano reazioni analoghe). Non merita una segnalazione: correggerla "
                            "sarebbe pignoleria controproducente."
                        ),
                        "errore_grave": (
                            "Il testo contiene un errore concettuale che potrebbe genuinamente "
                            "confondere uno studente durante il ripasso attivo, generare domande di "
                            "richiamo fuorvianti, o riflette un vero fraintendimento concettuale del "
                            "docente — ad esempio confondere due strutture anatomicamente distinte in "
                            "un modo che genera vera confusione (es. dire 'carotide' intendendo "
                            "'coronaria'), oppure affermare con sicurezza il contrario di un fatto "
                            "consolidato e ben noto (es. sostenere che i bastoncelli sono meno numerosi "
                            "dei coni, quando è vero il contrario)."
                        ),
                    },
                )
            },
            job_name="jev_task_a",
            unit_id=unit.unit_id,
            lesson_dir=lesson_dir,
            model=jev_cfg.model,
            credential=jev_cfg.credential,
            base_url=jev_cfg.base_url,
            timeout_seconds=jev_cfg.timeout_seconds,
        )
    except JevError:
        return None

    answer = resp.answers.get("correttezza")
    if answer is None or answer.type != "choice":
        return None

    should_skip = (answer.choice != "errore_grave") and (answer.confidence >= jev_cfg.task_a_skip_confidence_threshold)
    return JevTaskAVerdict(choice=answer.choice, confidence=answer.confidence, should_skip_expensive_llm=should_skip)


def run_jev_task_b(unit: DraftUnit, source_context: str, jev_cfg: JevConfig, lesson_dir: str) -> Optional[JevTaskBVerdict]:
    """
    Chiede a Jev se il testo rielaborato dell'unità introduce contenuto non supportato dai
    segmenti ASR grezzi corrispondenti (possibile invenzione/allucinazione), o si discosta
    significativamente dal loro senso. Vede sia i segmenti grezzi sia il rielaborato.
    Ritorna None se la chiamata fallisce: nessuna issue verrà creata in quel caso.
    """
    state = f"SEGMENTI GREZZI ASR:\n{source_context}\n\n---\n\nTESTO RIELABORATO:\n{unit.content}"
    try:
        resp = call_jev(
            state=state,
            questions={
                "unsupported_content": JevNoulQuestion(
                    instructions=(
                        "Ti vengono forniti (1) i segmenti grezzi della trascrizione automatica (ASR) "
                        "di un frammento di lezione universitaria, così come sono stati trascritti, e "
                        "(2) il testo finale rielaborato in prosa accademica a partire da quei "
                        "segmenti. La rielaborazione in prosa fluida, con parafrasi e riformulazioni "
                        "per la leggibilità, è normale e attesa: NON giudicare la fedeltà lessicale o "
                        "lo stile. Valuta invece se il testo rielaborato introduce contenuto "
                        "sostanziale che NON ha alcun riscontro, nemmeno approssimativo, nei segmenti "
                        "grezzi forniti (possibile invenzione/allucinazione del modello che ha generato "
                        "la rielaborazione, specialmente plausibile quando la trascrizione grezza è "
                        "essa stessa degradata o incomprensibile e il modello sembra aver 'riempito i "
                        "vuoti' con qualcosa di plausibile ma inventato), oppure se si allontana in "
                        "modo significativo dal senso di quanto effettivamente trasmesso nei segmenti "
                        "grezzi. Valuta quanto è vera l'affermazione: 'Il testo rielaborato contiene "
                        "contenuto sostanziale non supportato dai segmenti grezzi, o si discosta "
                        "significativamente dal loro significato.'"
                    ),
                )
            },
            job_name="jev_task_b",
            unit_id=unit.unit_id,
            lesson_dir=lesson_dir,
            model=jev_cfg.model,
            credential=jev_cfg.credential,
            base_url=jev_cfg.base_url,
            timeout_seconds=jev_cfg.timeout_seconds,
        )
    except JevError:
        return None

    answer = resp.answers.get("unsupported_content")
    if answer is None or answer.type != "noul":
        return None

    is_drift = answer.noul >= jev_cfg.task_b_fabrication_threshold
    return JevTaskBVerdict(noul_probability=answer.noul, is_high_confidence_drift=is_drift)


def build_rewrite_drift_issue(unit: DraftUnit, verdict: JevTaskBVerdict) -> ScienceIssue:
    """Costruisce una ScienceIssue ERR_REWRITE_DRIFT da un verdetto Jev ad alta confidenza.
    Nessun testo qui è generato da un LLM: 'reason' è un template deterministico di RT,
    sullo stesso modello già usato da detect_statistical_asr_risks per le issue ERR_ASR_ST."""
    severity = ScienceSeverity.HIGH if verdict.noul_probability >= 0.9 else ScienceSeverity.MEDIUM
    reason = (
        f"Il modello di pre-screening Jev ha rilevato con probabilità {verdict.noul_probability:.2f} "
        f"che questa unità rielaborata contiene contenuto non supportato dai segmenti ASR grezzi "
        f"corrispondenti, o si discosta significativamente dal loro significato. Nessuna revisione "
        f"LLM è stata eseguita su questo punto: verifica ascoltando l'audio originale (tasto P)."
    )
    return ScienceIssue(
        id=f"sci_jevdrift_{unit.unit_id}",
        type=ScienceType.ERR_REWRITE_DRIFT,
        severity=severity,
        unit_id=unit.unit_id,
        segment_id=None,
        claim=unit.content,
        reason=reason,
        suggested_fix=None,
        diplomatic_question=None,
        status="pending",
    )


def run_review(lesson_dir: str, force: bool = False, force_mock: bool = False, asr_llm: bool = False, shadow_jev: bool = False, ctx: "Optional[RunContext]" = None) -> Dict[str, Any]:
    """Esegue la critica scientifica indipendente (eventi e annullamento tra unità su ctx, se dato)."""
    with phase_scope(ctx, "review") as scope:
        return scope.complete(_run_review(lesson_dir, force=force, force_mock=force_mock, asr_llm=asr_llm, shadow_jev=shadow_jev, ctx=ctx))


def _run_review(lesson_dir: str, force: bool = False, force_mock: bool = False, asr_llm: bool = False, shadow_jev: bool = False, ctx: "Optional[RunContext]" = None) -> Dict[str, Any]:
    """Esegue la critica scientifica indipendente sul draft con checkpointing continuo."""
    yaml_path = lesson_path(lesson_dir, "info.yaml")

    manifest_before = load_manifest(lesson_dir)
    old_sci_hash = (
        manifest_before.phase_records.get("review", {})
        .get("artifact_fingerprints", {})
        .get("science_issues.json")
        if manifest_before and manifest_before.phase_records
        else None
    )

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "review")
    if phase_status == PhaseStatus.VALID and not force:
        all_science_issues = load_science_issues(lesson_dir)
        pending_sci = [s for s in all_science_issues if s.status == "pending"]
        next_state = WorkflowState.HUMAN_REVIEW_REQUIRED.value if pending_sci else WorkflowState.READY_TO_BUILD.value
        return {
            "status": "review_completed",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "total_science_issues": len(all_science_issues),
            "concettuale_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_CONCETTUALE),
            "asr_statistical_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_ST),
            "asr_llm_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_LLM),
            "rewrite_drift_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_REWRITE_DRIFT),
            "next_state": next_state,
            "issues_path": get_science_issues_path(lesson_dir)
        }

    action = "FORCE" if force else "RUN"
    
    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in segments_data.segments}

    _cfg = load_config()
    st_issues_all = detect_statistical_asr_risks(
        lesson_dir=lesson_dir,
        k=_cfg.review.asr_statistical_k,
        floor=_cfg.review.asr_statistical_floor,
    )
    st_issues_by_unit: Dict[str, List[ScienceIssue]] = {}
    for st_iss in st_issues_all:
        if st_iss.unit_id:
            st_issues_by_unit.setdefault(st_iss.unit_id, []).append(st_iss)

    # Riconciliazione all'avvio:
    if force or phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID):
        reviewed_unit_ids = []
        all_science_issues: List[ScienceIssue] = []
        save_science_issues(all_science_issues, lesson_dir)
        if force:
            from rt.pipeline.ledger import purge_decisions_by_prefix
            purge_decisions_by_prefix(lesson_dir, prefix="sci_")
    else:
        ckpt, ckpt_status, ckpt_reason = get_phase_checkpoint(lesson_dir, "review")
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
        if ctx is not None:
            ctx.check_cancelled()
            ctx.progress("review", current=idx, total=total_units, message=unit.unit_id)

        source_texts = []
        for s_id in unit.source_segment_ids:
            s = seg_by_id.get(s_id)
            if s:
                source_texts.append(f"[{s.id}] {s.text_raw}")
        source_context = "\n".join(source_texts)

        # Pre-filtro Jev (System One): due valutazioni indipendenti PRIMA della critica LLM
        # completa. In modalità ombra (--shadow-jev) girano e vengono loggate come sempre,
        # ma non saltano né creano nulla: il comportamento resta identico a Jev disattivato.
        skip_expensive_llm = False
        if _cfg.jev.enabled:
            verdict_a = run_jev_task_a(unit, _cfg.jev, lesson_dir)
            verdict_b = run_jev_task_b(unit, source_context, _cfg.jev, lesson_dir)

            if not shadow_jev:
                if verdict_b is not None and verdict_b.is_high_confidence_drift:
                    all_science_issues.append(build_rewrite_drift_issue(unit, verdict_b))
                if verdict_a is not None and verdict_a.should_skip_expensive_llm:
                    skip_expensive_llm = True

        if not skip_expensive_llm:
            asr_risk_context = None
            if asr_llm and unit.unit_id in st_issues_by_unit:
                unit_st = st_issues_by_unit[unit.unit_id][0]
                asr_risk_context = (
                    f"SEGMENTO A RISCHIO ASR RILEVATO STATISTICAMENTE IN QUESTA UNITÀ:\n"
                    f"Trascrizione raw: \"{unit_st.claim}\"\n"
                    f"Dettaglio: {unit_st.reason}\n\n"
                    f"ECCEZIONE PER QUESTO PUNTO SPECIFICO: la tua istruzione generale è di ignorare artefatti ASR isolati — "
                    f"per QUESTO segmento specifico, invece, valuta se il testo rielaborato corrispondente riflette fedelmente "
                    f"questa trascrizione raw o se sembra un'invenzione/allucinazione introdotta durante la riscrittura. "
                    f"Se sospetti fabbricazione o travisamento, genera una issue con \"type\": \"ERR_ASR_LLM\", "
                    f"\"segment_id\": \"{unit_st.segment_id or ''}\", \"claim\": \"{unit_st.claim}\", \"reason\": la tua motivazione, "
                    f"\"suggested_fix\": null. Se non sospetti nulla, non generare alcuna issue per questo punto."
                )

            prompt = build_science_review_user_prompt(
                unit_id=unit.unit_id,
                rewritten_content=unit.content,
                asr_risk_context=asr_risk_context,
            )

            unit_title = unit.title.strip() if getattr(unit, "title", None) else ""
            if len(unit_title) > 28:
                unit_title = unit_title[:25] + "..."
            unit_label = f"unit {idx}/{total_units} ({unit.unit_id}: {unit_title})" if unit_title else f"unit {idx}/{total_units} ({unit.unit_id})"

            for iss in _validated_review_issues(client, unit, prompt, lesson_dir, unit_label):
                iss.unit_id = unit.unit_id
                if iss.segment_id and iss.segment_id not in unit.source_segment_ids:
                    LOG.warning("Segmento %s fuori dall'unità %s: ricalcolo ancora review",
                                iss.segment_id, unit.unit_id)
                    iss.segment_id = None
                if not iss.segment_id:
                    iss.segment_id = _localize_claim_segment(iss.claim, unit, seg_by_id)
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

        source_fp = compute_source_fingerprint(lesson_dir, "review")
        sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))
        record_phase_checkpoint(
            lesson_dir=lesson_dir,
            phase_name="review",
            source_fingerprint=source_fp,
            artifact_fingerprints={"science_issues.json": sci_hash},
            completed_items=reviewed_unit_ids
        )

    # Finalizzazione se tutte le unità del draft sono state esaminate
    all_draft_unit_ids = [u.unit_id for u in draft.units]
    is_fully_reviewed = all(uid in reviewed_set for uid in all_draft_unit_ids)

    if is_fully_reviewed:
        all_science_issues = [iss for iss in all_science_issues if iss.type != ScienceType.ERR_ASR_ST]
        if not asr_llm:
            all_science_issues.extend(st_issues_all)

        for s_idx, iss in enumerate(all_science_issues, start=1):
            iss.id = f"sci_{s_idx:06d}"
        save_science_issues(all_science_issues, lesson_dir)

        source_fp = compute_source_fingerprint(lesson_dir, "review")
        sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))

        _job_cfg = _cfg.jobs.get("review") or _cfg.llm.get("review")
        _provenance = {
            "provider": _job_cfg.primary.provider if (_job_cfg and _job_cfg.primary) else None,
            "model": _job_cfg.primary.model if (_job_cfg and _job_cfg.primary) else None,
        }

        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name="review",
            source_fingerprint=source_fp,
            artifact_fingerprints={"science_issues.json": sci_hash},
            metadata=_provenance,
        )
        if (force or phase_status == PhaseStatus.STALE) and (old_sci_hash is None or old_sci_hash != sci_hash):
            mark_downstream_stale(lesson_dir, "review")

        pending_sci = [s for s in all_science_issues if s.status == "pending"]
        
        allow_t = force or (phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID, PhaseStatus.PARTIAL))
        if pending_sci:
            transition_to(yaml_path, WorkflowState.HUMAN_REVIEW_REQUIRED, allow_force=allow_t)
            next_state = WorkflowState.HUMAN_REVIEW_REQUIRED.value
        else:
            transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=allow_t)
            next_state = WorkflowState.READY_TO_BUILD.value
        status_msg = "review_completed"
    else:
        next_state = "partial"
        status_msg = "review_partial"

    return {
        "status": status_msg,
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "total_science_issues": len(all_science_issues),
        "concettuale_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_CONCETTUALE),
        "asr_statistical_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_ST),
        "asr_llm_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_LLM),
        "rewrite_drift_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_REWRITE_DRIFT),
        "next_state": next_state,
        "issues_path": get_science_issues_path(lesson_dir)
    }
