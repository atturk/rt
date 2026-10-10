"""
rt.pipeline.review
Fase E: REVIEW (Critic Scientifico Indipendente).
Analizza il draft rielaborato identificando:
- ERR_CONCETTUALE (incongruenze scientifiche ed errori concettuali nel rielaborato)
Salva science_issues.json.
"""
from rt.core.lesson_lock import lesson_locked

import os
import json
import logging
from typing import Dict, Any, List, Optional, Callable, Literal

from pydantic import ValidationError
from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity, DraftUnit
from rt.core.segments import load_segments_json
from rt.core.state import transition_to, WorkflowState
from rt.core.manifest import load_manifest
from rt.core.config import load_config, JevConfig
from rt.llm.client import LLMClient
from rt.services.prompt_settings import append_extra, effective_system
from rt.llm.prompts import (
    SCIENCE_REVIEW_SYSTEM_PROMPT,
    build_science_review_user_prompt,
    ScienceIssueList
)
from rt.pipeline.ledger import load_resolved_draft
from rt.pipeline.rewrite import load_draft
from rt.core.lesson_paths import lesson_path
from rt.core.asr_risk import detect_statistical_asr_risks
from rt.llm.jev_client import call_jev, JevNoulQuestion, JevError


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
from rt.services.events import Notice, ListReporter, ReviewUnitDone, ReviewUnitsQueued
from rt.pipeline.unit_failures import UnitFailureTracker, is_unit_failure
from rt.storage import fs
from rt.pipeline.review_units import record_review_unit, load_review_units

LOG = logging.getLogger(__name__)


def get_science_issues_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "science_issues.json")


LEGACY_TYPE_MAP = {
    "ERR_DOCENTE": "ERR_CONCETTUALE",
    "ERR_RECONSTRUCTION": "ERR_CONCETTUALE",
    "SCIENCE_CHECK": "ERR_CONCETTUALE",
}


def load_science_issues(lesson_dir: str, *, _migrate: bool = True) -> List[ScienceIssue]:
    if _migrate:
        from rt.pipeline.review_migration import migrate_review_anchors
        migrate_review_anchors(lesson_dir)
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


@lesson_locked
def save_science_issues(issues: List[ScienceIssue], lesson_dir: str) -> None:
    path = get_science_issues_path(lesson_dir)
    tmp_path = path + ".tmp"
    data = sanitize_object_encoding([iss.model_dump(mode="json") for iss in issues])
    for item in data:
        if item.get("anchor") is None:
            item.pop("anchor", None)
        if item.get("origin") == "verifica":
            item.pop("origin", None)
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
        prompt=prompt, system_prompt=effective_system("review", SCIENCE_REVIEW_SYSTEM_PROMPT),
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
                prompt=repair_prompt, system_prompt=effective_system("review", SCIENCE_REVIEW_SYSTEM_PROMPT),
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
    """Esito del Task A (correttezza scientifica): Jev vede SOLO il testo rielaborato.
    label/outcome/answer vengono dalla mappatura configurata (rt.services.jev_mapping)."""

    def __init__(self, choice: str, confidence: float, should_skip_expensive_llm: bool,
                 label: str = "", outcome: str = "", answer: Optional[Dict[str, Any]] = None):
        self.choice = choice
        self.confidence = confidence
        self.should_skip_expensive_llm = should_skip_expensive_llm
        self.label = label
        self.outcome = outcome
        self.answer = answer or {}

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "outcome": self.outcome, "answer": self.answer}


class JevTaskBVerdict:
    """Esito del Task B (coerenza rielaborazione/trascritto grezzo)."""

    def __init__(self, noul_probability: float, is_high_confidence_drift: bool):
        self.noul_probability = noul_probability
        self.is_high_confidence_drift = is_high_confidence_drift


from rt.services.unit_prefilter import cached


@cached("task_a")
def run_jev_task_a(unit: DraftUnit, jev_cfg: JevConfig, lesson_dir: str) -> Optional[JevTaskAVerdict]:
    """
    Chiede a Jev la domanda configurata per il prefiltro errori (predefinita: gravità degli
    errori scientifici), vedendo SOLO il testo rielaborato (mai il trascritto grezzo, per non
    contaminare il giudizio con considerazioni sulla fedeltà ASR, di competenza del Task B),
    e mappa la risposta su "salta la review" / "esegui la review".
    Ritorna None se la chiamata fallisce: fallback prudente, nessuno skip verrà applicato.
    """
    from rt.services import jev_mapping
    name = jev_mapping.QUESTION_NAMES["prefilter"]
    try:
        decision = jev_mapping.effective_decision("prefilter", jev_cfg)
        resp = call_jev(
            state=jev_mapping.state_for("prefilter", unit.title, unit.content),
            questions={name: jev_mapping.build_question(decision)},
            job_name="jev_task_a",
            unit_id=unit.unit_id,
            lesson_dir=lesson_dir,
            model=jev_cfg.model,
            credential=jev_cfg.credential,
            base_url=jev_cfg.base_url,
            timeout_seconds=jev_cfg.timeout_seconds,
        )
    except (JevError, ValidationError, ValueError, TypeError):
        # Risposta malformata o chiamata fallita: fallback prudente, la review LLM si fa.
        return None

    answer = resp.answers.get(name)
    if answer is None or answer.type != decision.type:
        return None
    result = jev_mapping.evaluate("prefilter", decision, answer)
    should_skip = result.outcome == "skip_review"
    if answer.type == "choice":
        choice, confidence = answer.choice, answer.confidence
    else:
        # noul/score non hanno una scelta: si riporta l'esito come nelle versioni precedenti.
        choice = "corretta" if should_skip else "errore_grave"
        confidence = 1 - answer.noul if answer.type == "noul" else answer.confidence
    return JevTaskAVerdict(choice=choice, confidence=confidence, should_skip_expensive_llm=should_skip,
                           label=result.label, outcome=result.outcome, answer=result.answer)


@cached("task_b")
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
    except (JevError, ValidationError, ValueError, TypeError):
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
        f"Il classificatore di pre-screening ha rilevato con probabilità {verdict.noul_probability:.2f} "
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


def _review_unit(client: LLMClient, unit: DraftUnit, idx: int, total_units: int, seg_by_id: dict,
                 st_issues_by_unit: Dict[str, List[ScienceIssue]], all_science_issues: List[ScienceIssue],
                 _cfg, lesson_dir: str, asr_llm: bool, shadow_jev: bool, ctx: "Optional[RunContext]" = None,
                 jev_log: Optional[Dict[str, Any]] = None, parent_context: Optional[str] = None) -> str:
    """Critica di una unità: aggiunge le sue issue ad all_science_issues (errori LLM rilanciati)."""
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
    from rt.core.config import classifier_job, classifier_jev
    prefilter = classifier_job(_cfg, "prefilter")
    drift = classifier_job(_cfg, "drift")
    if prefilter.mode in ("observe", "pipeline") or drift.mode in ("observe", "pipeline"):
        verdict_a = run_jev_task_a(unit, classifier_jev(_cfg, "prefilter"), lesson_dir) if prefilter.mode in ("observe", "pipeline") else None
        verdict_b = run_jev_task_b(unit, source_context, classifier_jev(_cfg, "drift"), lesson_dir) if drift.mode in ("observe", "pipeline") else None
        if verdict_a is not None:
            # Risposta completa (tutte le probabilità) nei log e nel risultato del job.
            if jev_log is not None:
                jev_log[unit.unit_id] = verdict_a.as_dict()
            if ctx is not None:
                from rt.services.jev_mapping import DecisionResult, describe
                ctx.emit(Notice(message=f"Classificatore prefiltro {unit.unit_id}: " + describe(DecisionResult(
                    label=verdict_a.label, outcome=verdict_a.outcome, rule=None, answer=verdict_a.answer))))

        if not shadow_jev:
            if drift.mode == "pipeline" and verdict_b is not None and verdict_b.is_high_confidence_drift:
                all_science_issues.append(build_rewrite_drift_issue(unit, verdict_b))
            if prefilter.mode == "pipeline" and verdict_a is not None and verdict_a.should_skip_expensive_llm:
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
            parent_context=parent_context,
        )

        unit_title = unit.title.strip() if getattr(unit, "title", None) else ""
        if len(unit_title) > 28:
            unit_title = unit_title[:25] + "..."
        unit_label = f"unit {idx}/{total_units} ({unit.unit_id}: {unit_title})" if unit_title else f"unit {idx}/{total_units} ({unit.unit_id})"

        prompt = append_extra(lesson_dir, "review", prompt)
        for iss in _validated_review_issues(client, unit, prompt, lesson_dir, unit_label):
            iss.unit_id = unit.unit_id
            if iss.segment_id and iss.segment_id not in unit.source_segment_ids:
                LOG.warning("Segmento %s fuori dall'unità %s: ricalcolo ancora review",
                            iss.segment_id, unit.unit_id)
                iss.segment_id = None
            if not iss.segment_id:
                iss.segment_id = _localize_claim_segment(iss.claim, unit, seg_by_id)
            all_science_issues.append(iss)

    return "skipped_by_prefilter" if skip_expensive_llm else "ok"


def run_review(lesson_dir: str, force: bool = False, force_mock: bool = False, asr_llm: bool = False, shadow_jev: bool = False, ctx: "Optional[RunContext]" = None) -> Dict[str, Any]:
    """Esegue la critica scientifica indipendente (eventi e annullamento tra unità su ctx)."""
    from rt.services.unit_relevance import refresh
    with phase_scope(ctx, "review") as scope:
        # Dentro lo scope: le chiamate JEV della rilevanza sono parte della fase (lock, errori, annullamento).
        refresh(lesson_dir, force_mock=force_mock, ctx=ctx)
        return scope.complete(_run_review(lesson_dir, force=force, force_mock=force_mock, asr_llm=asr_llm, shadow_jev=shadow_jev, ctx=ctx))


def _draft_hashes(lesson_dir: str) -> Dict[str, str]:
    """Impronte della bozza grezza: le decisioni cambiano il testo risolto ma non rendono
    un'unità da rivedere; solo riscrittura e modifiche a mano lo fanno."""
    return _unit_hashes(load_draft(lesson_dir).units)


def _unit_hashes(units) -> Dict[str, str]:
    """Impronta del testo di ogni unità revisionata: dice quali unità sono cambiate dopo la revisione."""
    import hashlib
    return {unit.unit_id: hashlib.sha256(unit.model_dump_json(exclude={"generated_at"}).encode("utf-8")).hexdigest() for unit in units}


def anchor_findings(findings: List[ScienceIssue], unit: DraftUnit, *, origin: Literal["verifica", "parte", "studio"] = "verifica") -> None:
    """Le ancore vengono dal testo esaminato, mai dalle posizioni inventate dal modello."""
    from rt.pipeline.anchors import make_anchor, find_quote
    paragraph_types = {ScienceType.ERR_ASR_ST, ScienceType.ERR_ASR_LLM, ScienceType.ERR_REWRITE_DRIFT}
    for issue in findings:
        issue.unit_id = unit.unit_id
        issue.origin = origin
        issue.status = "pending"
        if issue.type in paragraph_types:
            issue.anchor = make_anchor(unit.content, 0, len(unit.content))
        else:
            found = find_quote(unit.content, issue.claim)
            issue.anchor = make_anchor(unit.content, found.start, found.end) if found else None


def merge_unit_findings(lesson_dir: str, prior: List[ScienceIssue], generated: List[ScienceIssue],
                        units, replaced_units: set, *,
                        replace_open: Optional[Callable[[ScienceIssue], bool]] = None) -> tuple:
    """Conserva le decise, sostituisce le aperte, eredita i rifiuti sullo stesso tratto.

    replace_open permette ai chiamanti di limitare la sostituzione delle aperte
    a un tratto, conservando quelle della stessa unità fuori dal tratto.
    """
    from rt.pipeline.ledger import load_ledger
    from rt.pipeline.anchors import locate
    ledger = load_ledger(lesson_dir)
    decisions = {d.issue_id:d for d in ledger.decisions}
    checkpoint, _, _ = get_phase_checkpoint(lesson_dir, "review")
    sequence = max([int(value[4:]) for value in
                    [i.id for i in prior] + [d.issue_id for d in ledger.decisions]
                    if value.startswith("sci_") and value[4:].isdigit()] +
                   [int((checkpoint or {}).get("issue_sequence", 0))])
    kept = [i for i in prior if i.unit_id not in replaced_units or i.id in decisions
            or (replace_open is not None and not replace_open(i))]
    unit_by_id = {u.unit_id:u for u in units}
    rejections = []
    for old in prior:
        decision = decisions.get(old.id)
        unit = unit_by_id.get(old.unit_id)
        if decision and decision.decision == "rejected" and unit:
            anchor = decision.anchor or old.anchor
            found = locate(anchor, unit.content) if anchor else None
            if found:
                rejections.append((old, found))
    fresh_issues = []
    for fresh in generated:
        # Il rifiuto mantiene l'issue originale come rappresentante di quel tratto:
        # né la motivazione storica né la decisione vengono riscritte dal modello.
        if fresh.anchor and any(old.unit_id == fresh.unit_id and old.type == fresh.type and
                max(found.start, fresh.anchor.start) < min(found.end, fresh.anchor.end)
                for old, found in rejections):
            continue
        sequence += 1
        fresh.id = f"sci_{sequence:06d}"
        fresh_issues.append(fresh)
    rank = {u.unit_id:index for index, u in enumerate(units)}
    combined = sorted(kept + fresh_issues, key=lambda i:rank.get(i.unit_id, len(rank)))
    return combined, [], sequence


def _initialize_anchor_ledger(lesson_dir: str) -> None:
    """Le verifiche nuove producono già dati ancorati, non suggerimenti da migrare."""
    from rt.pipeline.ledger import load_ledger, save_ledger
    ledger = load_ledger(lesson_dir)
    if ledger.schema_version != "2.0":
        ledger.schema_version = "2.0"
        save_ledger(ledger, lesson_dir)


def manual_review_units(lesson_dir: str, units) -> set:
    """Una riscrittura successiva non eredita l'esenzione delle modifiche manuali."""
    import hashlib
    from rt.pipeline.document_edits import load_document_edits
    entries = load_document_edits(lesson_dir)["units"]
    return {u.unit_id for u in units if entries.get(u.unit_id, {}).get("edited") and
            (not entries[u.unit_id].get("edited_hash") or entries[u.unit_id]["edited_hash"] ==
             hashlib.sha256(u.content.encode("utf-8")).hexdigest())}


def _only_manual_edits(lesson_dir: str, units, eligible_ids) -> bool:
    """True se dopo la revisione sono cambiate solo unità corrette a mano nell'anteprima (il
    testo scritto dall'utente, decisioni comprese): segmenti, versione della fase e unità da
    rivedere sono gli stessi. Allora la review non riparte e issue e decisioni restano."""
    from rt.core.idempotency import PROCESSOR_VERSIONS, compute_file_sha256 as file_hash
    from rt.core.manifest import load_manifest
    from rt.pipeline.document_edits import edited_unit_ids
    manifest = load_manifest(lesson_dir)
    record = ((getattr(manifest, "phase_records", {}) or {}).get("review") or {}) if manifest else {}
    reviewed = record.get("unit_hashes")
    if record.get("status") not in (PhaseStatus.VALID.value, PhaseStatus.STALE.value) or not isinstance(reviewed, dict):
        return False
    if record.get("processor_version") != PROCESSOR_VERSIONS.get("review"):
        return False
    segments = (record.get("input_hashes") or {}).get("segments.json")
    if not segments or segments != file_hash(lesson_path(lesson_dir, "segments.json")):
        return False
    current = _unit_hashes(units)
    if set(current) != set(reviewed):
        return False
    changed = {uid for uid, digest in current.items() if reviewed.get(uid) != digest}
    if not changed or not changed <= manual_review_units(lesson_dir, units):
        return False
    eligible_before = record.get("eligible_units")
    if isinstance(eligible_before, list) and set(eligible_before) - changed != set(eligible_ids) - changed:
        return False
    return True


def parent_unit_context(units, unit_id: str) -> Optional[str]:
    """Le altre subunità della stessa unità (stesso prefisso: 2.1 → 2.x), come testo di contesto."""
    if "." not in unit_id:
        return None
    parent = unit_id.rsplit(".", 1)[0]
    siblings = [u for u in units if u.unit_id != unit_id and u.unit_id.rsplit(".", 1)[0] == parent and "." in u.unit_id]
    if not siblings:
        return None
    return "\n\n".join(f"{u.unit_id} {(u.title or '').strip()}\n{u.content}" for u in siblings)


def run_review_unit(lesson_dir: str, unit_id: str, force_mock: bool = False, parent_context: bool = False, force: bool = False) -> Dict[str, Any]:
    """Refresh just one unit, retaining other issues and their stable IDs/decisions. Con
    parent_context il revisore riceve anche le altre subunità della stessa unità."""
    from rt.services.unit_relevance import refresh, included
    refresh(lesson_dir, force_mock=force_mock)
    draft = load_resolved_draft(lesson_dir)
    unit = next((item for item in draft.units if item.unit_id == unit_id), None)
    if unit is None:
        raise ValueError(f"Unità {unit_id} non presente nella bozza.")
    if not included(lesson_dir, unit):
        return {"status": "skipped", "unit": unit_id, "reason": "Unità priva di contenuto didattico"}
    registry = load_review_units(lesson_dir)
    checkpoint, _, _ = get_phase_checkpoint(lesson_dir, "review")
    entry = registry.get(unit_id) or {}
    digest = entry.get("text_hash") or ((checkpoint or {}).get("unit_hashes") or {}).get(unit_id)
    known = bool(entry) or unit_id in ((checkpoint or {}).get("completed_items") or [])
    raw_hashes = _draft_hashes(lesson_dir)
    if not force and known and entry.get("result") != "failed" and digest == raw_hashes.get(unit_id):
        return {"status": "skipped", "unit": unit_id, "reason": "già verificata", "issues": entry.get("issues", 0)}
    segments = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in segments.segments}
    cfg = load_config()
    stats = detect_statistical_asr_risks(lesson_dir=lesson_dir,
        k=cfg.review.asr_statistical_k, floor=cfg.review.asr_statistical_floor)
    prior = load_science_issues(lesson_dir)
    _initialize_anchor_ledger(lesson_dir)
    generated = []
    client = LLMClient(force_mock=force_mock)
    try:
        result = _review_unit(client, unit, 1, 1, seg_by_id,
                     {unit_id: [issue for issue in stats if issue.unit_id == unit_id]},
                     generated, cfg, lesson_dir, False, cfg.jev.shadow,
                     parent_context=parent_unit_context(draft.units, unit_id) if parent_context else None)
    except Exception as exc:
        record_review_unit(lesson_dir, unit, cfg, client, 0, "failed", str(exc), text_hash=raw_hashes.get(unit_id))
        raise
    generated.extend(issue for issue in stats if issue.unit_id == unit_id)
    anchor_findings(generated, unit)
    from rt.core.lesson_lock import lesson_lock
    with lesson_lock(lesson_dir):
        combined, orphaned, sequence = merge_unit_findings(lesson_dir, load_science_issues(lesson_dir), generated, draft.units, {unit_id})
        save_science_issues(combined, lesson_dir)
        record_review_unit(lesson_dir, unit, cfg, client, len(generated), "issues" if generated else result,
                           text_hash=raw_hashes.get(unit_id))
        checkpoint, status_before, _ = get_phase_checkpoint(lesson_dir, "review")
        current = raw_hashes
        reviewed = (checkpoint or {}).get("unit_hashes")
        completed = list(checkpoint.get("completed_items") or []) if checkpoint else []
        # Il checkpoint prende l'impronta della bozza di adesso: resta "fatta" solo un'unità
        # rivista su questo stesso testo. Le altre unità cambiate (riscritte dopo la revisione)
        # tornano da rivedere, invece di risultare valide senza che nessuno le abbia guardate.
        if isinstance(reviewed, dict):
            completed = [item for item in completed if reviewed.get(item) == current.get(item)]
        elif status_before not in (PhaseStatus.VALID, PhaseStatus.PARTIAL):
            completed = []  # checkpoint di una versione precedente e bozza cambiata: nessuna certezza
        if unit_id not in completed:
            completed.append(unit_id)
        record_phase_checkpoint(lesson_dir=lesson_dir, phase_name="review",
            source_fingerprint=compute_source_fingerprint(lesson_dir, "review"),
            artifact_fingerprints={"science_issues.json": compute_file_sha256(get_science_issues_path(lesson_dir))},
            completed_items=completed,
            metadata={"unit_hashes": {item: current[item] for item in completed if item in current},
                      "issue_sequence": sequence})
        if set(completed) >= set(current):
            record_phase_fingerprint(lesson_dir, "review", compute_source_fingerprint(lesson_dir, "review"),
                {"science_issues.json": compute_file_sha256(get_science_issues_path(lesson_dir))},
                metadata={"unit_hashes": current})
    return {"unit": unit_id, "issues": len(generated), "other_issues_preserved": len(prior) - sum(i.unit_id == unit_id for i in prior),
            "orphaned_decisions": orphaned}


class _MockReviewOrder:
    """Il mock conserva il budget storico e l'ordine delle risposte della lezione.

    La sincronizzazione riguarda solo la generazione finta, mai il modello reale.
    Le unità escluse o fallite liberano comunque quelle successive.
    """
    def __init__(self, units):
        import threading
        self.units = units
        self.finished = set()
        self.condition = threading.Condition()

    def wait(self, unit_id):
        before = self.units[:self.units.index(unit_id)]
        with self.condition:
            self.condition.wait_for(lambda: all(uid in self.finished for uid in before))

    def complete(self, unit_id):
        with self.condition:
            self.finished.add(unit_id)
            self.condition.notify_all()


def _parallel_units(work, run, parallel, stop):
    """Al massimo parallel chiamate avviate; le risposte passano al thread chiamante.

    La coda conserva l'ordine di completamento. Quando stop diventa vero non
    partono nuove unità, ma si aspettano e si raccolgono quelle già avviate.
    """
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from queue import Queue
    finished = Queue()
    remaining = iter(work)
    pending = set()
    exhausted = False
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while pending or not exhausted:
            while not exhausted and len(pending) < parallel and not stop():
                item = next(remaining, None)
                if item is None:
                    exhausted = True
                    break
                future = pool.submit(copy_context().run, run, *item)
                pending.add(future)
                future.add_done_callback(finished.put)
            if not pending:
                break
            future = finished.get()
            pending.remove(future)
            yield future.result()


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
    draft = load_resolved_draft(lesson_dir)
    raw_draft = load_draft(lesson_dir)
    phase_status, reason = check_phase_status(lesson_dir, "review")
    registry = load_review_units(lesson_dir)
    checkpoint, _, _ = get_phase_checkpoint(lesson_dir, "review")
    prior_hashes = (checkpoint or {}).get("unit_hashes") or {}
    current_hashes = _unit_hashes(raw_draft.units)
    current_text = all((registry.get(uid, {}).get("text_hash") or prior_hashes.get(uid)) == digest
                       for uid, digest in current_hashes.items())
    # Anche le unità sparite devono attraversare la conservazione delle decise.
    old_ids = set(prior_hashes)
    if (phase_status == PhaseStatus.VALID and not force and current_text and old_ids <= set(current_hashes)
            and not any(e.get("result") == "failed" for e in registry.values())):
        all_science_issues = load_science_issues(lesson_dir)
        from rt.pipeline.ledger import get_pending_issues
        _, pending_sci = get_pending_issues(lesson_dir)
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
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in segments_data.segments}

    _cfg = load_config()
    from rt.services.unit_relevance import included, included_ids
    eligible_ids = included_ids(lesson_dir, draft.units)
    st_issues_all = detect_statistical_asr_risks(
        lesson_dir=lesson_dir,
        k=_cfg.review.asr_statistical_k,
        floor=_cfg.review.asr_statistical_floor,
    )
    st_issues_all = [issue for issue in st_issues_all if not issue.unit_id or issue.unit_id in eligible_ids]
    st_issues_by_unit: Dict[str, List[ScienceIssue]] = {}
    for st_iss in st_issues_all:
        if st_iss.unit_id:
            st_issues_by_unit.setdefault(st_iss.unit_id, []).append(st_iss)

    # Testo corretto a mano nell'anteprima dopo la revisione (per esempio per chiudere un'issue):
    # la review resta valida con le sue issue e decisioni, invece di ripartire da zero (4.2.3b3.2).
    if not force and phase_status == PhaseStatus.STALE and _only_manual_edits(lesson_dir, raw_draft.units, eligible_ids):
        all_science_issues = load_science_issues(lesson_dir)
        record_phase_fingerprint(
            lesson_dir=lesson_dir, phase_name="review",
            source_fingerprint=compute_source_fingerprint(lesson_dir, "review"),
            artifact_fingerprints={"science_issues.json": compute_file_sha256(get_science_issues_path(lesson_dir))},
            metadata={"unit_hashes": _unit_hashes(raw_draft.units), "eligible_units": sorted(eligible_ids)},
        )
        if ctx is not None:
            ctx.emit(Notice(level="info", message="Revisione già fatta: il testo è cambiato solo nelle unità "
                                                  "corrette a mano, issue e decisioni restano."))
        from rt.pipeline.ledger import get_pending_issues
        _, pending_sci = get_pending_issues(lesson_dir)
        return {
            "status": "review_completed", "action": "SKIP", "skipped": True,
            "reason": "testo modificato solo a mano dopo la revisione",
            "total_science_issues": len(all_science_issues),
            "concettuale_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_CONCETTUALE),
            "asr_statistical_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_ST),
            "asr_llm_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_ASR_LLM),
            "rewrite_drift_issues": sum(1 for x in all_science_issues if x.type == ScienceType.ERR_REWRITE_DRIFT),
            "next_state": (WorkflowState.HUMAN_REVIEW_REQUIRED.value if pending_sci
                           else WorkflowState.READY_TO_BUILD.value),
            "issues_path": get_science_issues_path(lesson_dir),
        }

    all_science_issues = load_science_issues(lesson_dir)
    # Una scaletta nuova elimina soltanto le issue aperte delle unità sparite.
    # Le decisioni e le relative issue restano leggibili e da riconfermare.
    from rt.pipeline.ledger import load_ledger
    decided_ids = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    draft_ids = {u.unit_id for u in draft.units}
    retained = [i for i in all_science_issues if not i.unit_id or i.unit_id in draft_ids or i.id in decided_ids]
    if len(retained) != len(all_science_issues):
        all_science_issues = retained
        save_science_issues(all_science_issues, lesson_dir)
    _initialize_anchor_ledger(lesson_dir)
    if not fs.isfile(get_science_issues_path(lesson_dir)):
        save_science_issues(all_science_issues, lesson_dir)
    ckpt, ckpt_status, _ = get_phase_checkpoint(lesson_dir, "review")
    from rt.pipeline.document_edits import edited_unit_ids
    current_hashes = _unit_hashes(raw_draft.units)
    prior_hashes = (ckpt or {}).get("unit_hashes") or {}
    completed = set((ckpt or {}).get("completed_items") or [])
    manual = manual_review_units(lesson_dir, raw_draft.units)
    reviewed_unit_ids = []
    for unit in draft.units:
        entry = registry.get(unit.unit_id) or {}
        digest = entry.get("text_hash") or prior_hashes.get(unit.unit_id)
        known = bool(entry) or unit.unit_id in completed
        failed = entry.get("result") == "failed"
        newly_included = entry.get("result") == "excluded" and unit.unit_id in eligible_ids
        if not force and known and not failed and not newly_included and (digest == current_hashes[unit.unit_id] or unit.unit_id in manual):
            reviewed_unit_ids.append(unit.unit_id)
    client = LLMClient(force_mock=force_mock)
    reviewed_set = set(reviewed_unit_ids)
    unit_hashes = current_hashes
    total_units = len(draft.units)
    failures = UnitFailureTracker()
    stopped_early = False
    fatal_error = None
    jev_prefilter: Dict[str, Any] = {}

    work = [(idx, unit) for idx, unit in enumerate(draft.units, start=1)
            if force or unit.unit_id not in reviewed_set]

    mock_order = _MockReviewOrder([unit.unit_id for _, unit in work])
    mock_calls = {}

    pending_units = {unit.unit_id for _, unit in work}
    if ctx:
        ctx.emit(ReviewUnitsQueued(pending_units=sorted(pending_units)))

    def examine(idx, unit):
        # Client separati; soltanto il budget del mock resta quello della lezione.
        client = None
        reporter = ListReporter()
        child = RunContext(lesson_dir=lesson_dir, reporter=reporter,
                           telemetry=ctx.telemetry, cancel_token=ctx.cancel_token) if ctx else None
        generated, prefilter = [], {}
        result, error = "excluded", None
        try:
            client = LLMClient(force_mock=force_mock)
            client._mock_issue_calls = mock_calls
            client._mock_review_wait = lambda: mock_order.wait(unit.unit_id)
            from contextlib import nullcontext
            with child.activate() if child else nullcontext():
                if unit.unit_id in eligible_ids:
                    result = _review_unit(client, unit, idx, total_units, seg_by_id, st_issues_by_unit, generated,
                                          _cfg, lesson_dir, asr_llm, shadow_jev, ctx=child, jev_log=prefilter)
                elif child:
                    child.emit(Notice(level="info", message=f"Unità {unit.unit_id} esclusa dalla review: priva di contenuto didattico."))
        except Exception as exc:
            error = exc
        finally:
            mock_order.complete(unit.unit_id)
        return idx, unit, client, generated, result, reporter.events, prefilter, error

    if ctx:
        ctx.check_cancelled()
    for idx, unit, client, generated, unit_result, events, prefilter, exc in _parallel_units(
            work, examine, _cfg.review.parallel_units,
            lambda: stopped_early or fatal_error is not None or bool(ctx and ctx.cancel_token.cancelled)):
        unit_title = unit.title.strip() if getattr(unit, "title", None) else ""
        jev_prefilter.update(prefilter)
        if ctx:
            for event in events:
                ctx.emit(event)
            ctx.progress("review", current=len(reviewed_set) + len(failures.failures) + 1, total=total_units,
                         message=f"{unit.unit_id} {unit_title}".strip(), unit_id=unit.unit_id,
                         unit_title=unit_title or None, failed=len(failures.failures))
        if exc is not None:
            from rt.services.context import RunCancelled
            if isinstance(exc, RunCancelled) and ctx and ctx.cancel_token.cancelled:
                continue
            if not is_unit_failure(exc):
                # Ferma gli invii, ma salva anche le altre unità già partite.
                fatal_error = fatal_error or exc
                if client is not None:
                    record_review_unit(lesson_dir, unit, _cfg, client, 0, "failed", str(exc),
                                       text_hash=unit_hashes.get(unit.unit_id))
                continue
            failure = failures.failed(unit.unit_id, f"{idx}/{total_units} ({unit.unit_id}{': ' + unit_title if unit_title else ''})", exc)
            record_review_unit(lesson_dir, unit, _cfg, client, 0, "failed", failure.message,
                               text_hash=unit_hashes.get(unit.unit_id))
            LOG.error("Review unità %s non riuscita: %s", unit.unit_id, failure.message)
            if ctx:
                ctx.emit(Notice(level="warning", message=f"Revisione dell'unità {failure.label} non riuscita: {failure.message}"))
                pending_units.discard(unit.unit_id)
                ctx.emit(ReviewUnitDone(unit_id=unit.unit_id, issues=0, pending_units=sorted(pending_units)))
            if failures.too_many():
                stopped_early = True
            continue
        failures.succeeded()

        if not asr_llm:
            generated.extend(st_issues_by_unit.get(unit.unit_id, []))
        anchor_findings(generated, unit)
        from rt.core.lesson_lock import lesson_lock
        with lesson_lock(lesson_dir):
            all_science_issues, _, sequence = merge_unit_findings(
                lesson_dir, load_science_issues(lesson_dir), generated, draft.units, {unit.unit_id})
            save_science_issues(all_science_issues, lesson_dir)
            record_review_unit(lesson_dir, unit, _cfg, client, len(generated), "issues" if generated else unit_result,
                               text_hash=unit_hashes.get(unit.unit_id))

            # Commit atomico nel checkpoint
            if unit.unit_id not in reviewed_set:
                reviewed_unit_ids.append(unit.unit_id)
                reviewed_set.add(unit.unit_id)
            reviewed_unit_ids = [u.unit_id for u in draft.units if u.unit_id in reviewed_set]

            source_fp = compute_source_fingerprint(lesson_dir, "review")
            sci_hash = compute_file_sha256(get_science_issues_path(lesson_dir))
            record_phase_checkpoint(
                lesson_dir=lesson_dir,
                phase_name="review",
                source_fingerprint=source_fp,
                artifact_fingerprints={"science_issues.json": sci_hash},
                completed_items=reviewed_unit_ids,
                metadata={"unit_hashes": {uid: unit_hashes[uid] for uid in reviewed_unit_ids if uid in unit_hashes},
                          "issue_sequence": sequence},
            )
        if ctx:
            pending_units.discard(unit.unit_id)
            ctx.emit(ReviewUnitDone(unit_id=unit.unit_id, issues=len(generated), pending_units=sorted(pending_units)))

    if ctx:
        ctx.check_cancelled()

    if fatal_error is not None:
        raise fatal_error

    # Finalizzazione se tutte le unità del draft sono state esaminate
    all_draft_unit_ids = [u.unit_id for u in draft.units]
    is_fully_reviewed = all(uid in reviewed_set for uid in all_draft_unit_ids)
    if failures.failures:
        # Le unità non riuscite restano nel manifest: lo stato della fase le mostra e
        # una nuova run rifà solo quelle (e le eventuali non ancora esaminate).
        sci_path = get_science_issues_path(lesson_dir)
        record_phase_checkpoint(
            lesson_dir=lesson_dir,
            phase_name="review",
            source_fingerprint=compute_source_fingerprint(lesson_dir, "review"),
            artifact_fingerprints={"science_issues.json": compute_file_sha256(sci_path)} if fs.isfile(sci_path) else None,
            completed_items=reviewed_unit_ids,
            metadata={"failed_units": failures.as_dicts()},
        )

    if is_fully_reviewed:
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
            metadata={**_provenance, "unit_hashes": unit_hashes, "eligible_units": sorted(eligible_ids)},
        )
        if (force or phase_status == PhaseStatus.STALE) and (old_sci_hash is None or old_sci_hash != sci_hash):
            mark_downstream_stale(lesson_dir, "review")

        from rt.pipeline.ledger import get_pending_issues
        _, pending_sci = get_pending_issues(lesson_dir)

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
        "issues_path": get_science_issues_path(lesson_dir),
        "completed_units": len(reviewed_set & set(all_draft_unit_ids)),
        "expected_units": len(all_draft_unit_ids),
        "failed_units": failures.as_dicts(),
        "stopped_early": stopped_early,
        **({"jev_prefilter": jev_prefilter} if jev_prefilter else {}),
    }
