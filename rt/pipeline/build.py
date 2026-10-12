"""
rt.pipeline.build
Deterministic Final Builder e Renderer per il workflow RT.
VINCOLO FONDAMENTALE DI ARCHITETTURA:
I timestamp visualizzati nei documenti (es. '36:30') NON sono accettati dall'LLM,
ma derivati matematicamente ed esclusivamente dal segmento ASR corrispondente:
segments[unit.start_segment_id].start_seconds -> format_timestamp().
"""

from rt.core.lesson_lock import lesson_locked

import os
import re
from typing import Dict, List, Optional, Any
from rt.core.models import (
    Outline, Draft, SegmentsData, Segment,
    ScienceIssue, DecisionLedger
)
from rt.core.timestamp import format_timestamp
from rt.core.encoding import fix_mojibake
from rt.core.lesson_paths import lesson_path
from rt.services.context import RunContext, phase_scope
from rt.storage import fs


class BuildError(Exception):
    pass


def render_pre_elaborato_md(
    outline: Outline,
    draft: Draft,
    segments_data: SegmentsData,
    date: str,
    subject: str,
    topics: str,
    science_issues: Optional[List[ScienceIssue]] = None
) -> str:
    """
    Renderizza pre-elaborato.md con traccia temporale rigorosa e marker di revisione.
    TUTTI i timestamp di inizio unità sono ricavati da segments_data.
    """
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    draft_by_unit_id = {u.unit_id: u for u in draft.units}
    
    # Prepara frontmatter YAML
    topics_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topics_list:
        topics_list = [topics]
    yaml_topics = "\n".join(f"  - '{t}'" for t in topics_list)
    
    lines = [
        "---",
        f"titolo: '{outline.lesson_title}'",
        f"materia: '{subject.upper()}'",
        f"data: '{date}'",
        "argomenti:",
        yaml_topics,
        "---",
        "",
        f"# Pre-elaborato - [{date}] {subject.upper()} - {outline.lesson_title}",
        "",
        "> Documento di lavoro con tracciamento temporale e marker di revisione.",
        ""
    ]
    
    sci_by_seg: Dict[str, List[ScienceIssue]] = {}
    if science_issues:
        for s_iss in science_issues:
            if s_iss.segment_id:
                sci_by_seg.setdefault(s_iss.segment_id, []).append(s_iss)
    
    err_counter = 1
    
    for macro in outline.macro_sections:
        lines.append(f"## {macro.id}. {macro.title}\n")
        
        for unit in macro.units:
            start_seg = seg_by_id.get(unit.start_segment_id)
            if not start_seg:
                raise BuildError(f"Segmento di inizio '{unit.start_segment_id}' inesistente per unità '{unit.id}'")
            
            # DERIVAZIONE DETERMINISTICA DEL TIMESTAMP
            derived_timestamp = format_timestamp(start_seg.start_seconds)
            
            lines.append(f"### {unit.id} {unit.title}")
            lines.append(f"{derived_timestamp}\n")
            
            draft_unit = draft_by_unit_id.get(unit.id)
            unit_content = draft_unit.content.strip() if draft_unit else "_Contenuto in attesa di rielaborazione._"
            
            # Inserimento controllato dei marker
            unit_markers = []
            if draft_unit:
                for s_id in draft_unit.source_segment_ids:
                    # Errori concettuali
                    for sci in sci_by_seg.get(s_id, []):
                        if getattr(sci.type, "value", sci.type) == "ERR_CONCETTUALE":
                            seg_item = seg_by_id.get(s_id)
                            tc = format_timestamp(seg_item.start_seconds) if seg_item else derived_timestamp
                            unit_markers.append(f"(⁉️ ERR{err_counter} {tc})")
                            err_counter += 1
            
            if unit_markers:
                unit_content += " " + " ".join(unit_markers)
                
            lines.append(unit_content)
            lines.append("")
            
    return "\n".join(lines)


def clean_unit_content(content: str) -> str:
    """Testo di un'unità come compare nel documento: senza marker residui e con gli spazi
    compattati. Le righe vuote fra paragrafi restano (anche quelle scritte nell'anteprima)."""
    content = re.sub(r"\s*\(\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+.*?\)", "", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = re.sub(r"[ \t]*\n[ \t]*", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def render_rielaborato_md(
    outline: Outline,
    draft: Draft,
    segments_data: SegmentsData,
    date: str,
    subject: str,
    topics: str,
    images_by_macro: Optional[Dict[str, List[dict]]] = None,
    edits: Optional[Dict[str, Any]] = None,
    enrichment_by_unit: Optional[Dict[str, List[str]]] = None,
) -> str:
    """
    Renderizza rielaborato.md pulito e pronto per lo studio/Obsidian/Telegram.
    I timestamp derivano sempre da segments_data. edits: modifiche fatte a mano
    nell'anteprima (titoli e segmento d'inizio delle unità, rt.pipeline.document_edits).
    """
    from rt.pipeline.document_edits import macro_title, unit_start_segment, unit_title
    edits = edits or {}
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    draft_by_unit_id = {u.unit_id: u for u in draft.units}
    
    topics_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topics_list:
        topics_list = [topics]
    yaml_topics = "\n".join(f"  - '{t}'" for t in topics_list)
    
    lines = [
        "---",
        f"titolo: '{outline.lesson_title}'",
        f"materia: '{subject.upper()}'",
        f"data: '{date}'",
        "argomenti:",
        yaml_topics,
        "---",
        # niente titolo H1: data, materia e titolo sono già nel nome del file e nel
        # frontmatter (Obsidian li mostrerebbe due volte)
        "",
    ]
    
    for macro in outline.macro_sections:
        lines.append(f"## {macro.id}. {macro_title(edits, macro.id, macro.title)}\n")
        
        macro_id_str = str(macro.id)
        if images_by_macro and macro_id_str in images_by_macro and images_by_macro[macro_id_str]:
            # link Markdown uno sotto l'altro: la formattazione la sceglie l'utente
            for img in images_by_macro[macro_id_str]:
                alt = img.get("alt_text", "")
                lines.append(f"![{alt}]({img['filename']})")
            lines.append("")
        
        for unit in macro.units:
            start_seg_id = unit_start_segment(edits, unit.id, unit.start_segment_id)
            start_seg = seg_by_id.get(start_seg_id)
            if not start_seg:
                raise BuildError(f"Segmento di inizio '{start_seg_id}' inesistente per unità '{unit.id}'")
            
            # DERIVAZIONE DETERMINISTICA DEL TIMESTAMP
            derived_timestamp = format_timestamp(start_seg.start_seconds)
            
            lines.append(f"### {unit.id} {unit_title(edits, unit.id, unit.title)}")
            lines.append(f"{derived_timestamp}\n")
            
            draft_unit = draft_by_unit_id.get(unit.id)
            content = draft_unit.content.strip() if draft_unit else ""
            
            content = clean_unit_content(content)
            
            lines.append(content)
            lines.append("")
            if enrichment_by_unit:
                lines.extend(enrichment_by_unit.get(str(unit.id), []))
            
    return "\n".join(lines)


def render_errori_concettuali_md(
    science_issues: List[ScienceIssue],
    segments_data: SegmentsData,
    date: str,
    subject: str,
    ledger: Optional[DecisionLedger] = None
) -> str:
    """Renderizza Errori concettuali.md (ERR_CONCETTUALE)."""
    seg_by_id = {s.id: s for s in segments_data.segments}
    decisions_map = {d.issue_id: d for d in (ledger.decisions if ledger else [])}
    concettuali_issues = [s for s in science_issues if getattr(s.type, "value", s.type) == "ERR_CONCETTUALE"]
    
    lines = [
        f"# Errori Concettuali - [{date}] {subject.upper()}",
        "",
        "> Registro delle incongruenze scientifiche ed errori concettuali, con correzioni e spunti per chiarimenti.",
        ""
    ]
    
    if not concettuali_issues:
        lines.append("_Nessun errore concettuale rilevato._\n")
        return "\n".join(lines)
        
    for iss in concettuali_issues:
        seg = seg_by_id.get(iss.segment_id) if iss.segment_id else None
        tc = seg.start_formatted if seg else "N/D"
        status = decisions_map[iss.id].decision if iss.id in decisions_map else iss.status
        
        lines.append(f"### {iss.id} ({tc}) - Gravità: {iss.severity.value.upper()}")
        lines.append(f"- **Affermazione**: \"{iss.claim}\"")
        lines.append(f"- **Spiegazione scientifica**: {iss.reason}")
        if iss.suggested_fix:
            lines.append(f"- **Correzione proposta**: {iss.suggested_fix}")
        if iss.diplomatic_question:
            lines.append(f"- **Domanda diplomatica**: *\"{iss.diplomatic_question}\"*")
        lines.append(f"- **Stato revisione**: `{status}`\n")
        
    return "\n".join(lines)


def _atomic_write_text(filepath: str, content: str) -> None:
    clean_content = fix_mojibake(content)
    tmp_path = filepath + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        f.write(clean_content)
    fs.replace(tmp_path, filepath)


def render_lesson_documents(lesson_dir: str) -> Dict[str, Any]:
    """Documenti della lezione come li scrive il build, calcolati dai file attuali (bozza,
    decisioni della revisione, immagini posizionate) senza scrivere nulla. È anche
    l'anteprima: quello che l'utente vede prima del build è quello che il build produce."""
    from rt.core.state import read_info_yaml
    from rt.core.segments import load_segments_json
    from rt.pipeline.image_placement import images_for_document
    from rt.pipeline.outline import load_outline
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review import load_science_issues
    from rt.pipeline.ledger import load_ledger, apply_decisions_to_draft
    from rt.pipeline.document_edits import load_document_edits, edited_unit_dates

    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    raw_topics = info.get("argomenti")

    outline = load_outline(lesson_dir)
    if info.get("titolo_personalizzato") == "true":
        outline = outline.model_copy(update={"lesson_title": info.get("titolo") or outline.lesson_title})
    topics_replaced = False
    if (not raw_topics or not str(raw_topics).strip()) and outline.generated_topics:
        topics_val = ", ".join(outline.generated_topics)
        topics_replaced = True
    else:
        topics_val = raw_topics or "Argomenti"

    safe_title = re.sub(r'[/\\:*?"<>|]', ' ', outline.lesson_title)
    safe_title = re.sub(r'\s+', ' ', safe_title).strip()

    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    ledger = load_ledger(lesson_dir)
    science_issues = load_science_issues(lesson_dir)
    # Applicazione deterministica del decision ledger
    edits = load_document_edits(lesson_dir)
    edited = edited_unit_dates(lesson_dir)
    resolved_draft = apply_decisions_to_draft(draft, ledger, science_issues, edited)
    images_by_macro, _carousel = images_for_document(lesson_dir, outline)
    from rt.services.enrichment_service import document_blocks

    return {
        "outline": outline,
        "date": date_val,
        "subject": subject_val,
        "topics": topics_val,
        "topics_replaced": topics_replaced,
        "safe_title": safe_title,
        "named_filename": f"[{date_val}] {subject_val.upper()} - {safe_title}.md",
        "pre_elaborato": render_pre_elaborato_md(
            outline=outline, draft=resolved_draft, segments_data=segments_data, date=date_val,
            subject=subject_val, topics=topics_val, science_issues=science_issues),
        "rielaborato": render_rielaborato_md(
            outline=outline, draft=resolved_draft, segments_data=segments_data, date=date_val,
            subject=subject_val, topics=topics_val, images_by_macro=images_by_macro, edits=edits,
            enrichment_by_unit=document_blocks(lesson_dir)),
        "errori_concettuali": render_errori_concettuali_md(science_issues, segments_data, date_val, subject_val, ledger),
    }


def _write_rendered_documents(lesson_dir: str, docs: Dict[str, Any]) -> str:
    """Il chiamante tiene il lock per l'intero snapshot e tutte le sostituzioni atomiche."""
    named_path = os.path.join(lesson_dir, docs["named_filename"])
    for name, value in (("pre-elaborato.md", "pre_elaborato"), ("rielaborato.md", "rielaborato"),
                        ("Errori concettuali.md", "errori_concettuali")):
        _atomic_write_text(lesson_path(lesson_dir, name), docs[value])
    _atomic_write_text(named_path, docs["rielaborato"])
    return named_path


@lesson_locked
def write_automatic_documents(lesson_dir: str) -> Dict[str, Any]:
    """Aggiorna il build senza finalizzare una verifica incompleta o ancora da decidere."""
    from rt.core.idempotency import (compute_source_fingerprint, compute_file_sha256,
                                    record_phase_fingerprint, upstream_acknowledgement)
    from rt.core.manifest import init_or_update_manifest
    from rt.core.state import update_info_yaml, compute_effective_workflow_state
    docs = render_lesson_documents(lesson_dir)
    named_path = _write_rendered_documents(lesson_dir, docs)
    info_updates = {"titolo": docs["outline"].lesson_title}
    if docs["topics_replaced"]:
        info_updates["argomenti"] = docs["topics"]
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    update_info_yaml(yaml_path, info_updates)
    acknowledged = upstream_acknowledgement(lesson_dir, "build")
    metadata = {"automatic_documents": True}
    if acknowledged:
        metadata["upstream_acknowledged"] = acknowledged
    record_phase_fingerprint(lesson_dir, "build", compute_source_fingerprint(lesson_dir, "build"),
        {name: compute_file_sha256(lesson_path(lesson_dir, name))
         for name in ("pre-elaborato.md", "rielaborato.md", "Errori concettuali.md")}, metadata=metadata)
    state = compute_effective_workflow_state(lesson_dir)
    if state:
        update_info_yaml(yaml_path, {"fase_corrente": state.value, "stato": state.value})
        init_or_update_manifest(lesson_dir=lesson_dir, lesson_id=os.path.basename(os.path.abspath(lesson_dir)),
            date=docs["date"], subject=docs["subject"], topics=docs["topics"], current_state=state.value)
    return {"status": "updated", "skipped": False, "lesson_dir": lesson_dir,
            "rielaborato": lesson_path(lesson_dir, "rielaborato.md"),
            "errori_concettuali": lesson_path(lesson_dir, "Errori concettuali.md"), "named_file": named_path}


def run_build(lesson_dir: str, force: bool = False, rename_folder: bool = False, ctx: "Optional[RunContext]" = None) -> Dict[str, Any]:
    """Scrive subito i documenti. rename_folder resta leggibile ma non sposta più la lezione."""
    with phase_scope(ctx, "build") as scope:
        return scope.complete(_run_build(lesson_dir, force=force, rename_folder=rename_folder))


def _run_build(lesson_dir: str, force: bool = False, rename_folder: bool = False) -> Dict[str, Any]:
    """
    Esegue la finalizzazione deterministica della lezione.
    Assembla tutti i documenti Markdown finali applicando il Decision Ledger.
    """
    from rt.core.state import update_info_yaml, transition_to, WorkflowState
    from rt.core.manifest import init_or_update_manifest
    from rt.core.idempotency import (
        PhaseStatus,
        check_phase_status,
        compute_source_fingerprint,
        compute_file_sha256,
        record_phase_fingerprint,
        upstream_acknowledgement,
    )
    
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    docs = render_lesson_documents(lesson_dir)
    outline = docs["outline"]
    date_val, subject_val, topics_val = docs["date"], docs["subject"], docs["topics"]
    topics_replaced = docs["topics_replaced"]
    named_filename = docs["named_filename"]
    named_filepath = os.path.join(lesson_dir, named_filename)

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "build")
    from rt.services.documents_service import documents_pending
    from rt.core.manifest import load_manifest, save_manifest
    current_manifest = load_manifest(lesson_dir)
    previous_automatic = bool(current_manifest and current_manifest.phase_records.get("build", {}).get("automatic_documents"))
    if phase_status == PhaseStatus.VALID and not force and fs.isfile(named_filepath) and not documents_pending(lesson_dir) and not previous_automatic:
        current_dir = lesson_dir
        return {
            "status": "completed",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "lesson_dir": current_dir,
            "pre_elaborato": lesson_path(current_dir, "pre-elaborato.md"),
            "rielaborato": lesson_path(current_dir, "rielaborato.md"),
            "named_file": named_filepath,
            "errori_concettuali": lesson_path(current_dir, "Errori concettuali.md"),
            "telemetry_summary": lesson_path(current_dir, "telemetry_summary.json")
        }

    action = "FORCE" if force else "RUN"

    # Scrittura atomica di pre-elaborato.md, rielaborato.md (con le immagini posizionate),
    # Errori concettuali.md e della copia intitolata di rielaborato.md
    named_filepath = _write_rendered_documents(lesson_dir, docs)

    current_dir = lesson_dir
    # 7. Registrazione fingerprint build. Le fasi a monte non aggiornate in questo momento
    # (es. scaletta STALE dopo un cambio di materia) sono "confermate": il documento appena
    # scritto riflette i file attuali e resta valido finché quelle fasi non cambiano ancora.
    source_fp = compute_source_fingerprint(current_dir, "build")
    acknowledged = upstream_acknowledgement(current_dir, "build")
    metadata = {"upstream_acknowledged": acknowledged} if acknowledged else {}
    # rt build ripristina lo stesso registro storico anche dopo un job automatico.
    current_manifest = load_manifest(current_dir)
    if current_manifest and current_manifest.phase_records.get("build", {}).get("automatic_documents"):
        build_record = current_manifest.phase_records["build"]
        build_record.pop("automatic_documents", None)
        build_record["artifact_fingerprints"] = {}
        save_manifest(current_manifest, current_dir)
    record_phase_fingerprint(
        lesson_dir=current_dir,
        phase_name="build",
        source_fingerprint=source_fp,
        artifact_fingerprints={
            "rielaborato.md": compute_file_sha256(lesson_path(current_dir, "rielaborato.md"))
        },
        metadata=metadata or None,
    )

    # 8. Aggiornamento stato e manifest
    transition_to(yaml_path, WorkflowState.COMPLETED, allow_force=force)
    info_updates = {
        "titolo": outline.lesson_title,
        "fase_corrente": "completato",
        "stato": "completato",
    }
    if topics_replaced:
        info_updates["argomenti"] = topics_val
    update_info_yaml(yaml_path, info_updates)

    init_or_update_manifest(
        lesson_dir=current_dir,
        lesson_id=os.path.basename(os.path.abspath(current_dir)),
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        current_state=WorkflowState.COMPLETED.value
    )

    # 9. Persistenza atomica della telemetria su disco
    from rt.llm.telemetry import current_telemetry
    telemetry_file = lesson_path(current_dir, "telemetry_summary.json")
    current_telemetry().export_to_file(telemetry_file)
    from rt.services.documents_service import mark_documents_written
    mark_documents_written(current_dir)

    return {
        "status": "completed",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "lesson_dir": current_dir,
        "pre_elaborato": lesson_path(current_dir, "pre-elaborato.md"),
        "rielaborato": lesson_path(current_dir, "rielaborato.md"),
        "named_file": named_filepath,
        "errori_concettuali": lesson_path(current_dir, "Errori concettuali.md"),
        "telemetry_summary": telemetry_file
    }
