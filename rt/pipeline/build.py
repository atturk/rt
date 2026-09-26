"""
rt.pipeline.build
Deterministic Final Builder e Renderer per il workflow RT.
VINCOLO FONDAMENTALE DI ARCHITETTURA:
I timestamp visualizzati nei documenti (es. '36:30') NON sono accettati dall'LLM,
ma derivati matematicamente ed esclusivamente dal segmento ASR corrispondente:
segments[unit.start_segment_id].start_seconds -> format_timestamp().
"""

import os
import re
import shutil
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


def render_rielaborato_md(
    outline: Outline,
    draft: Draft,
    segments_data: SegmentsData,
    date: str,
    subject: str,
    topics: str,
    images_by_macro: Optional[Dict[str, List[dict]]] = None,
) -> str:
    """
    Renderizza rielaborato.md pulito e pronto per lo studio/Obsidian/Telegram.
    I timestamp derivano sempre da segments_data.
    """
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
        "",
        f"# [{date}] {subject.upper()} - {outline.lesson_title}",
        ""
    ]
    
    for macro in outline.macro_sections:
        lines.append(f"## {macro.id}. {macro.title}\n")
        
        macro_id_str = str(macro.id)
        if images_by_macro and macro_id_str in images_by_macro and images_by_macro[macro_id_str]:
            # link Markdown uno sotto l'altro: la formattazione la sceglie l'utente
            for img in images_by_macro[macro_id_str]:
                alt = img.get("alt_text", "")
                lines.append(f"![{alt}]({img['filename']})")
            lines.append("")
        
        for unit in macro.units:
            start_seg = seg_by_id.get(unit.start_segment_id)
            if not start_seg:
                raise BuildError(f"Segmento di inizio '{unit.start_segment_id}' inesistente per unità '{unit.id}'")
            
            # DERIVAZIONE DETERMINISTICA DEL TIMESTAMP
            derived_timestamp = format_timestamp(start_seg.start_seconds)
            
            lines.append(f"### {unit.id} {unit.title}")
            lines.append(f"{derived_timestamp}\n")
            
            draft_unit = draft_by_unit_id.get(unit.id)
            content = draft_unit.content.strip() if draft_unit else ""
            
            # Pulizia di qualsiasi eventuale marker residuo
            content = re.sub(r"\s*\(\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+.*?\)", "", content)
            content = re.sub(r"\s{2,}", " ", content).strip()
            
            lines.append(content)
            lines.append("")
            
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


def _move_to_lessons_root_if_configured(current_dir: str) -> str:
    """
    Se lessons_root è configurato in general.yaml, sposta la cartella lezione
    in lessons_root (se non vi si trova già e se non vi sono collisioni).
    """
    from rt.core.config import load_config
    try:
        cfg = load_config()
        lessons_root = cfg.telegram.lessons_root if cfg and cfg.telegram else None
    except Exception:
        lessons_root = None

    if not lessons_root or not str(lessons_root).strip():
        return current_dir

    lessons_root_path = os.path.abspath(str(lessons_root).strip())
    abs_current = os.path.abspath(current_dir)
    dest_path = os.path.join(lessons_root_path, os.path.basename(abs_current))
    abs_dest = os.path.abspath(dest_path)

    if abs_current == abs_dest or os.path.dirname(abs_current) == lessons_root_path:
        return current_dir

    if fs.exists(abs_dest):
        print(
            f"⚠️  Impossibile spostare la cartella in '{dest_path}': "
            f"esiste già un'altra cartella con quel nome in '{lessons_root_path}'. "
            f"La lezione resta in '{abs_current}'."
        )
        return current_dir

    fs.makedirs(lessons_root_path, exist_ok=True)
    fs.move(abs_current, dest_path)
    print(f"📦 Cartella spostata in: '{dest_path}'")

    try:
        from rt.core.manifest import load_manifest, save_manifest
        m = load_manifest(dest_path)
        if m:
            save_manifest(m, lesson_dir=dest_path)
    except Exception:
        pass

    return dest_path


def run_build(lesson_dir: str, force: bool = False, rename_folder: bool = False, ctx: "Optional[RunContext]" = None) -> Dict[str, Any]:
    """Finalizzazione deterministica della lezione (eventi su ctx, se dato)."""
    with phase_scope(ctx, "build") as scope:
        return scope.complete(_run_build(lesson_dir, force=force, rename_folder=rename_folder))


def _run_build(lesson_dir: str, force: bool = False, rename_folder: bool = False) -> Dict[str, Any]:
    """
    Esegue la finalizzazione deterministica della lezione.
    Assembla tutti i documenti Markdown finali applicando il Decision Ledger.
    """
    from rt.core.state import read_info_yaml, update_info_yaml, transition_to, WorkflowState
    from rt.core.segments import load_segments_json
    from rt.core.manifest import init_or_update_manifest
    from rt.pipeline.outline import load_outline
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review import load_science_issues
    from rt.pipeline.ledger import load_ledger, apply_decisions_to_draft
    from rt.core.idempotency import (
        PhaseStatus,
        check_phase_status,
        compute_source_fingerprint,
        compute_file_sha256,
        record_phase_fingerprint,
    )
    
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    raw_topics = info.get("argomenti")

    outline = load_outline(lesson_dir)
    topics_replaced = False
    if (not raw_topics or not str(raw_topics).strip()) and outline.generated_topics:
        topics_val = ", ".join(outline.generated_topics)
        topics_replaced = True
    else:
        topics_val = raw_topics or "Argomenti"

    safe_title = re.sub(r'[/\\:*?"<>|]', ' ', outline.lesson_title)
    safe_title = re.sub(r'\s+', ' ', safe_title).strip()
    named_filename = f"[{date_val}] {subject_val.upper()} - {safe_title}.md"
    named_filepath = os.path.join(lesson_dir, named_filename)

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "build")
    if phase_status == PhaseStatus.VALID and not force and fs.isfile(named_filepath):
        current_dir = _move_to_lessons_root_if_configured(lesson_dir)
        named_filepath = os.path.join(current_dir, named_filename)
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
    
    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    ledger = load_ledger(lesson_dir)
    science_issues = load_science_issues(lesson_dir)
    
    # 1. Applicazione deterministica del decision ledger
    resolved_draft = apply_decisions_to_draft(draft, ledger, science_issues)
    
    # 2. Generazione pre-elaborato.md (atomica)
    pre_md = render_pre_elaborato_md(
        outline=outline,
        draft=resolved_draft,
        segments_data=segments_data,
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        science_issues=science_issues
    )
    _atomic_write_text(lesson_path(lesson_dir, "pre-elaborato.md"), pre_md)
        
    # 3. Generazione rielaborato.md (atomica)
    rielab_md = render_rielaborato_md(
        outline=outline,
        draft=resolved_draft,
        segments_data=segments_data,
        date=date_val,
        subject=subject_val,
        topics=topics_val
    )
    _atomic_write_text(lesson_path(lesson_dir, "rielaborato.md"), rielab_md)

    # 4. Generazione Errori concettuali.md (atomica)
    err_md = render_errori_concettuali_md(science_issues, segments_data, date_val, subject_val, ledger)
    _atomic_write_text(lesson_path(lesson_dir, "Errori concettuali.md"), err_md)

    # 5. Copia intitolata di rielaborato.md con nome formale (atomica)
    _atomic_write_text(named_filepath, rielab_md)

    current_dir = lesson_dir
    if rename_folder:
        folder_target_name = f"[{date_val}] {subject_val.upper()} - {safe_title}"
        parent = os.path.dirname(os.path.abspath(lesson_dir))
        target_dir = os.path.join(parent, folder_target_name)
        abs_lesson_dir = os.path.abspath(lesson_dir)
        if abs_lesson_dir == target_dir:
            pass
        elif fs.exists(target_dir):
            print(
                f"⚠️  Impossibile rinominare la cartella in '{folder_target_name}': "
                f"esiste già un'altra cartella con quel nome in '{parent}'. "
                f"La lezione resta in '{os.path.basename(abs_lesson_dir)}'."
            )
        else:
            fs.rename(lesson_dir, target_dir)
            current_dir = target_dir
            print(f"📁 Cartella rinominata: '{os.path.basename(abs_lesson_dir)}' -> '{folder_target_name}'")
            yaml_path = lesson_path(current_dir, "info.yaml")
            named_filepath = os.path.join(current_dir, named_filename)

    # Spostamento in lessons_root se configurato
    old_current_dir = current_dir
    current_dir = _move_to_lessons_root_if_configured(current_dir)
    if current_dir != old_current_dir:
        yaml_path = lesson_path(current_dir, "info.yaml")
        named_filepath = os.path.join(current_dir, named_filename)

    if os.path.abspath(current_dir) != os.path.abspath(lesson_dir):
        from rt.db.sync import relocate_lesson
        relocate_lesson(lesson_dir, current_dir)

    # 7. Registrazione fingerprint build
    source_fp = compute_source_fingerprint(current_dir, "build")
    record_phase_fingerprint(
        lesson_dir=current_dir,
        phase_name="build",
        source_fingerprint=source_fp,
        artifact_fingerprints={
            "rielaborato.md": compute_file_sha256(lesson_path(current_dir, "rielaborato.md"))
        }
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
