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
from typing import Dict, List, Optional, Any
from rt.core.models import (
    Outline, Draft, SegmentsData, Segment,
    ASRIssue, ScienceIssue, DecisionLedger
)
from rt.core.timestamp import format_timestamp
from rt.core.encoding import fix_mojibake
from rt.core.lesson_paths import lesson_path


class BuildError(Exception):
    pass


def render_pre_elaborato_md(
    outline: Outline,
    draft: Draft,
    segments_data: SegmentsData,
    date: str,
    subject: str,
    topics: str,
    asr_issues: Optional[List[ASRIssue]] = None,
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
    
    # Mappa issue per segmento
    asr_by_seg: Dict[str, List[ASRIssue]] = {}
    if asr_issues:
        for iss in asr_issues:
            asr_by_seg.setdefault(iss.segment_id, []).append(iss)
            
    sci_by_seg: Dict[str, List[ScienceIssue]] = {}
    if science_issues:
        for s_iss in science_issues:
            if s_iss.segment_id:
                sci_by_seg.setdefault(s_iss.segment_id, []).append(s_iss)
    
    amb_counter = 1
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
                    # Ambiguità ASR
                    for asr in asr_by_seg.get(s_id, []):
                        seg_item = seg_by_id.get(s_id)
                        tc = format_timestamp(seg_item.start_seconds) if seg_item else derived_timestamp
                        unit_markers.append(f"(⚠️ AMB{amb_counter} {tc} | ASR: \"{asr.source_text}\")")
                        amb_counter += 1
                    # Errori docente
                    for sci in sci_by_seg.get(s_id, []):
                        if sci.type == "ERR_DOCENTE":
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
    ledger: Optional[DecisionLedger] = None
) -> str:
    """
    Renderizza rielaborato.md pulito e pronto per lo studio/Obsidian/Telegram.
    Applica deterministicamente le decisioni convalidate dal ledger.
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
            
            # Applicazione deterministica del decision ledger
            if ledger and content:
                for decision in ledger.decisions:
                    if decision.decision in ("accepted", "edited") and decision.resolved_text:
                        # Se è stata specificata una sostituzione esplicita
                        pass
                        
            # Pulizia di qualsiasi eventuale marker residuo
            content = re.sub(r"\s*\(\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+.*?\)", "", content)
            content = re.sub(r"\s{2,}", " ", content).strip()
            
            lines.append(content)
            lines.append("")
            
    return "\n".join(lines)


def render_revisioni_asr_md(
    asr_issues: List[ASRIssue],
    segments_data: SegmentsData,
    date: str,
    subject: str,
    ledger: Optional[DecisionLedger] = None
) -> str:
    """Renderizza Revisioni ASR.md con timecode esatto e intervallo di ascolto."""
    seg_by_id = {s.id: s for s in segments_data.segments}
    decisions_map = {d.issue_id: d for d in (ledger.decisions if ledger else [])}
    
    lines = [
        f"# Revisioni ASR - [{date}] {subject.upper()}",
        "",
        "> Registro automatico delle ambiguità fonetiche con coordinate audio per la verifica d'ascolto.",
        "",
        "| ID | Livello | Timecode | Ascolto Audio | ASR Originale | Ipotesi Proposta | Stato |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    
    if not asr_issues:
        lines.append("\n_Nessuna ambiguità ASR rilevata._")
        return "\n".join(lines)
        
    for iss in asr_issues:
        seg = seg_by_id.get(iss.segment_id)
        if seg:
            tc = seg.start_formatted
            # Finestra d'ascolto: 5s prima e 5s dopo il segmento
            listen_start = format_timestamp(max(0.0, seg.start_seconds - 5.0))
            listen_end = format_timestamp(seg.end_seconds + 5.0)
            listen_str = f"`{listen_start} - {listen_end}`"
        else:
            tc = "N/D"
            listen_str = "N/D"
            
        status = decisions_map[iss.id].decision if iss.id in decisions_map else iss.status
        clean_orig = iss.source_text.replace("|", "/")
        clean_cand = iss.candidate.replace("|", "/")
        
        lines.append(f"| {iss.id} | {iss.level.value} | {tc} | {listen_str} | {clean_orig} | {clean_cand} | {status} |")
        
    return "\n".join(lines)


def render_errori_concettuali_md(
    science_issues: List[ScienceIssue],
    segments_data: SegmentsData,
    date: str,
    subject: str,
    ledger: Optional[DecisionLedger] = None
) -> str:
    """Renderizza Errori concettuali.md focalizzato sugli errori del docente (ERR_DOCENTE)."""
    seg_by_id = {s.id: s for s in segments_data.segments}
    decisions_map = {d.issue_id: d for d in (ledger.decisions if ledger else [])}
    docente_issues = [s for s in science_issues if s.type.value == "ERR_DOCENTE"]
    
    lines = [
        f"# Errori Concettuali e Lapsus del Docente - [{date}] {subject.upper()}",
        "",
        "> Registro delle incongruenze espresse durante la lezione, con correzioni e spunti per chiarimenti.",
        ""
    ]
    
    if not docente_issues:
        lines.append("_Nessun lapsus o errore concettuale del docente rilevato._\n")
        return "\n".join(lines)
        
    for iss in docente_issues:
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


def render_problemi_scientifici_md(
    science_issues: List[ScienceIssue],
    segments_data: SegmentsData,
    date: str,
    subject: str,
    ledger: Optional[DecisionLedger] = None
) -> str:
    """Renderizza Problemi scientifici.md (ERR_RECONSTRUCTION e SCIENCE_CHECK)."""
    seg_by_id = {s.id: s for s in segments_data.segments}
    decisions_map = {d.issue_id: d for d in (ledger.decisions if ledger else [])}
    other_issues = [s for s in science_issues if s.type.value in ("ERR_RECONSTRUCTION", "SCIENCE_CHECK")]
    
    lines = [
        f"# Revisione Scientifica e Controlli di Fedeltà - [{date}] {subject.upper()}",
        "",
        "> Registro delle verifiche scientifiche indipendenti (ricostruzioni ad alto rischio e controlli di plausibilità).",
        ""
    ]
    
    if not other_issues:
        lines.append("_Nessun problema di ricostruzione o incongruenza scientifica rilevata dal revisore._\n")
        return "\n".join(lines)
        
    for iss in other_issues:
        seg = seg_by_id.get(iss.segment_id) if iss.segment_id else None
        tc = seg.start_formatted if seg else "N/D"
        status = decisions_map[iss.id].decision if iss.id in decisions_map else iss.status
        
        lines.append(f"### {iss.id} [{iss.type.value}] ({tc}) - Gravità: {iss.severity.value.upper()}")
        lines.append(f"- **Passo in esame**: \"{iss.claim}\"")
        if iss.source_quote:
            lines.append(f"- **Citazione ASR sorgente**: \"{iss.source_quote}\"")
        lines.append(f"- **Critica scientifica**: {iss.reason}")
        if iss.suggested_fix:
            lines.append(f"- **Risoluzione raccomandata**: {iss.suggested_fix}")
        lines.append(f"- **Stato**: `{status}`\n")
        
    return "\n".join(lines)


def _atomic_write_text(filepath: str, content: str) -> None:
    clean_content = fix_mojibake(content)
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(clean_content)
    os.replace(tmp_path, filepath)


def run_build(lesson_dir: str, force: bool = False, rename_folder: bool = False) -> Dict[str, Any]:
    """
    Esegue la finalizzazione deterministica della lezione.
    Assembla tutti i documenti Markdown finali applicando il Decision Ledger.
    """
    from rt.core.state import read_info_yaml, update_info_yaml, transition_to, WorkflowState
    from rt.core.segments import load_segments_json
    from rt.core.manifest import init_or_update_manifest
    from rt.pipeline.outline import load_outline
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review_asr import load_asr_issues
    from rt.pipeline.review_science import load_science_issues
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
    topics_val = info.get("argomenti", "Argomenti")

    outline = load_outline(lesson_dir)
    safe_title = re.sub(r'[/\\:*?"<>|]', ' ', outline.lesson_title)
    safe_title = re.sub(r'\s+', ' ', safe_title).strip()
    named_filename = f"[{date_val}] {subject_val.upper()} - {safe_title}.md"
    named_filepath = os.path.join(lesson_dir, named_filename)

    # Controllo idempotenza: se valido e non forzato, SKIP immediato
    phase_status, reason = check_phase_status(lesson_dir, "build")
    if phase_status == PhaseStatus.VALID and not force and os.path.isfile(named_filepath):
        return {
            "status": "completed",
            "action": "SKIP",
            "skipped": True,
            "reason": reason,
            "lesson_dir": lesson_dir,
            "pre_elaborato": lesson_path(lesson_dir, "pre-elaborato.md"),
            "rielaborato": lesson_path(lesson_dir, "rielaborato.md"),
            "named_file": named_filepath,
            "revisioni_asr": lesson_path(lesson_dir, "Revisioni ASR.md"),
            "errori_concettuali": lesson_path(lesson_dir, "Errori concettuali.md"),
            "problemi_scientifici": lesson_path(lesson_dir, "Problemi scientifici.md"),
            "telemetry_summary": lesson_path(lesson_dir, "telemetry_summary.json")
        }

    action = "FORCE" if force else "RUN"
    
    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    ledger = load_ledger(lesson_dir)
    asr_issues = load_asr_issues(lesson_dir)
    science_issues = load_science_issues(lesson_dir)
    
    # 1. Applicazione deterministica del decision ledger
    resolved_draft = apply_decisions_to_draft(draft, ledger, asr_issues, science_issues)
    
    # 2. Generazione pre-elaborato.md (atomica)
    pre_md = render_pre_elaborato_md(
        outline=outline,
        draft=resolved_draft,
        segments_data=segments_data,
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        asr_issues=asr_issues,
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
        topics=topics_val,
        ledger=ledger
    )
    # rielaborato.md è un intermedio interno (usato per il fingerprint di idempotenza):
    # il deliverable che l'utente apre è il file col titolo formale, scritto al punto 7.
    _atomic_write_text(lesson_path(lesson_dir, "rielaborato.md"), rielab_md)

    # 4. Generazione Revisioni ASR.md (atomica)
    asr_md = render_revisioni_asr_md(asr_issues, segments_data, date_val, subject_val, ledger)
    _atomic_write_text(lesson_path(lesson_dir, "Revisioni ASR.md"), asr_md)

    # 5. Generazione Errori concettuali.md (atomica)
    err_md = render_errori_concettuali_md(science_issues, segments_data, date_val, subject_val, ledger)
    _atomic_write_text(lesson_path(lesson_dir, "Errori concettuali.md"), err_md)

    # 6. Generazione Problemi scientifici.md (atomica)
    prob_md = render_problemi_scientifici_md(science_issues, segments_data, date_val, subject_val, ledger)
    _atomic_write_text(lesson_path(lesson_dir, "Problemi scientifici.md"), prob_md)
        
    # 7. Copia intitolata di rielaborato.md con nome formale (atomica) — questo, non
    # rielaborato.md (spostato in _state/ al punto 3), è il deliverable che l'utente apre.
    _atomic_write_text(named_filepath, rielab_md)

    current_dir = lesson_dir
    # Rinomina cartella opzionale (default: attiva, vedi --no-rename in rt/cli.py) con lo
    # stesso schema data+materia+titolo del file col titolo formale, cosicché la cartella
    # smetta di portare il nome provvisorio scelto al momento del setup.
    if rename_folder:
        folder_target_name = f"[{date_val}] {subject_val.upper()} - {safe_title}"
        parent = os.path.dirname(os.path.abspath(lesson_dir))
        target_dir = os.path.join(parent, folder_target_name)
        abs_lesson_dir = os.path.abspath(lesson_dir)
        if abs_lesson_dir == target_dir:
            pass  # già nominata correttamente, nulla da fare
        elif os.path.exists(target_dir):
            print(
                f"⚠️  Impossibile rinominare la cartella in '{folder_target_name}': "
                f"esiste già un'altra cartella con quel nome in '{parent}'. "
                f"La lezione resta in '{os.path.basename(abs_lesson_dir)}'."
            )
        else:
            os.rename(lesson_dir, target_dir)
            current_dir = target_dir
            print(f"📁 Cartella rinominata: '{os.path.basename(abs_lesson_dir)}' -> '{folder_target_name}'")
            yaml_path = lesson_path(current_dir, "info.yaml")
            named_filepath = os.path.join(current_dir, named_filename)

    # 8. Registrazione fingerprint build
    source_fp = compute_source_fingerprint(current_dir, "build")
    record_phase_fingerprint(
        lesson_dir=current_dir,
        phase_name="build",
        source_fingerprint=source_fp,
        artifact_fingerprints={
            "rielaborato.md": compute_file_sha256(lesson_path(current_dir, "rielaborato.md"))
        }
    )

    # 9. Aggiornamento stato e manifest
    transition_to(yaml_path, WorkflowState.COMPLETED, allow_force=force)
    update_info_yaml(yaml_path, {
        "titolo": outline.lesson_title,
        "fase_corrente": "completato",
        "stato": "completato"
    })

    init_or_update_manifest(
        lesson_dir=current_dir,
        lesson_id=os.path.basename(os.path.abspath(current_dir)),
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        current_state=WorkflowState.COMPLETED.value
    )

    # 10. Persistenza atomica della telemetria su disco
    from rt.llm.telemetry import GLOBAL_TELEMETRY
    telemetry_file = lesson_path(current_dir, "telemetry_summary.json")
    GLOBAL_TELEMETRY.export_to_file(telemetry_file)

    return {
        "status": "completed",
        "action": action,
        "skipped": False,
        "reason": "explicit user-requested rerun" if force else reason,
        "lesson_dir": current_dir,
        "pre_elaborato": lesson_path(current_dir, "pre-elaborato.md"),
        "rielaborato": lesson_path(current_dir, "rielaborato.md"),
        "named_file": named_filepath,
        "revisioni_asr": lesson_path(current_dir, "Revisioni ASR.md"),
        "errori_concettuali": lesson_path(current_dir, "Errori concettuali.md"),
        "problemi_scientifici": lesson_path(current_dir, "Problemi scientifici.md"),
        "telemetry_summary": telemetry_file
    }
