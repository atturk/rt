"""
rt.cli
CLI unificata per il workflow accademico RT.
Comandi disponibili:
  rt config             (wizard interattivo di configurazione guidata)
  rt run                <cartella> [--mock]
  rt setup              --audio <file> --date <YYYY-MM-DD> --materia <nome>
  rt prepare            <cartella>
  rt outline            <cartella> [--mock]
  rt rewrite            <cartella> [--unit <id>] [--mock]
  rt review             <cartella> [--mock]
  rt recall             <cartella>
  rt build              <cartella> [--no-rename] (rinomina la cartella col titolo finale, attivo di default)
  rt status             <cartella>
  rt telegram-daemon    [--state-dir <path>]

Comandi diagnostici (uso avanzato):
  rt validate-outline   <cartella>
  rt validate-draft     <cartella>
"""

import sys
import os
import argparse
import json
import re
from typing import Dict, Any, List, Optional, Tuple

from rt.core.config import load_env_file, _default_project_root
from rt.core.state import read_info_yaml, transition_to, WorkflowState
from rt.core.encoding import fix_mojibake

from rt.core.manifest import load_manifest
from rt.core.lesson_paths import lesson_path
from rt.core.segments import load_segments_json
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.outline_review import confirm_or_revise_outline
from rt.pipeline.validator import validate_outline, validate_draft
from rt.pipeline.rewrite import run_rewrite, load_draft, get_draft_path
from rt.pipeline.review import run_review, load_science_issues
from rt.pipeline.issue_review import run_interactive_review
from rt.pipeline.ledger import load_ledger
from rt.pipeline.build import run_build



def _has_real_config_source() -> bool:
    """Vero se esiste una sorgente di configurazione reale (cartella config/) nella
    working directory corrente o nella project root reale. Usata dai comandi CLI che
    eseguono lavoro LLM reale per evitare di procedere silenziosamente con i default hardcoded."""
    if os.path.isdir(os.path.join(os.getcwd(), "config")):
        return True
    return os.path.isdir(os.path.join(_default_project_root(), "config"))


def _job_has_configured_route(job_cfg) -> bool:
    """Vero se il job ha almeno una route primaria con provider/model impostati."""
    return bool(job_cfg and job_cfg.primary and job_cfg.primary.is_configured)


def _job_config_hint(job_name: str) -> str:
    """Messaggio di errore per un job non configurato: la sottocartella di config/ in cui
    si trova il suo file .yaml è a scelta libera (vedi rt.core.config.find_job_yaml_paths),
    quindi punta al percorso reale se il file esiste già, altrimenti a config/ in generale."""
    from rt.core.config import find_job_yaml_paths
    paths = find_job_yaml_paths(os.path.join(os.getcwd(), "config"))
    existing = paths.get(job_name)
    where = os.path.relpath(existing, os.getcwd()) if existing else f"config/{job_name}.yaml (in qualunque sottocartella di config/)"
    return (
        f"❌ Il job '{job_name}' non ha alcun provider configurato in {where}.\n"
        f"   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
        f"   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
        f"   in {where}. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa."
    )


def _ensure_config_ready(required_jobs: List[str]) -> Any:
    """Verifica che esista una sorgente di configurazione reale e che tutti i job in required_jobs
    abbiano una route primaria configurata. Se manca la sorgente o un job non è configurato,
    stampa il messaggio d'errore appropriato su stderr ed esce con sys.exit(1). Restituisce l'oggetto RTConfig."""
    if not _has_real_config_source():
        print(
            "❌ Nessuna configurazione trovata (cartella 'config/' mancante).\n"
            "   Copia 'config.example/' in 'config/' e personalizza i modelli prima di eseguire questo comando:\n"
            "   cp -r config.example config",
            file=sys.stderr
        )
        sys.exit(1)

    from rt.core.config import load_config
    cfg = load_config()

    missing = [j for j in required_jobs if not _job_has_configured_route(cfg.jobs.get(j))]
    if missing:
        if len(missing) == 1:
            print(_job_config_hint(missing[0]), file=sys.stderr)
        else:
            print(
                f"❌ I seguenti job non hanno un provider configurato: {', '.join(missing)}.\n"
                "   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
                "   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
                "   nei rispettivi file config/<job>.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
                file=sys.stderr
            )
        sys.exit(1)

    return cfg


def _print_phase_action(
    phase_name: str,
    res: Dict[str, Any],
    step: Optional[int] = None,
    total_steps: Optional[int] = None,
    description: Optional[str] = None,
    details: Optional[str] = None,
):
    action = res.get("action", "RUN")
    reason = res.get("reason", "")
    skipped = res.get("skipped", False) or action == "SKIP"

    if step is not None and total_steps is not None:
        header_desc = f" ({description})" if description else ""
        print(f"\n[{step}/{total_steps}] {phase_name.upper()}{header_desc}...")
        if skipped:
            msg = details if details else f"{phase_name} già valido ({reason})"
            print(f"⏩ [SKIP] {msg}")
        elif action == "FORCE":
            msg = details if details else f"{phase_name} completato (rigenerazione forzata)."
            print(f"✔ [FORCE] {msg}")
        else:
            msg = details if details else f"{phase_name} completato."
            print(f"✔ {msg}")
    else:
        if action == "SKIP":
            print(f"\n[SKIP] {phase_name}\nReason: {reason}\n")
        elif action == "FORCE":
            print(f"\n[FORCE] {phase_name}\nReason: {reason}\n✔ {phase_name} completato (rigenerazione forzata).\n")
        else:
            print(f"\n[RUN] {phase_name}\nReason: {reason}\n✔ {phase_name} completato.\n")


def cmd_prepare(args):
    force = getattr(args, "force", False)
    res = run_prepare(args.lesson_dir, force=force)
    _print_phase_action("prepare", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_outline(args):
    if not getattr(args, "mock", False):
        _ensure_config_ready(["outline"])
    force = getattr(args, "force", False)
    res = run_outline(args.lesson_dir, force=force, force_mock=args.mock)
    _print_phase_action("outline", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))

    confirm_or_revise_outline(args.lesson_dir, force=force, force_mock=args.mock)


def cmd_validate_outline(args):
    outline = load_outline(args.lesson_dir)
    seg_data = load_segments_json(os.path.join(args.lesson_dir, "segments.json"))
    res = validate_outline(outline, seg_data)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_rewrite(args):
    if not getattr(args, "mock", False):
        _ensure_config_ready(["rewrite"])
    force = getattr(args, "force", False)
    res = run_rewrite(args.lesson_dir, target_unit_id=args.unit, force=force, force_mock=args.mock)
    label = f"rewrite unit {args.unit}" if args.unit else "rewrite"
    _print_phase_action(label, res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_validate_draft(args):
    outline = load_outline(args.lesson_dir)
    draft = load_draft(args.lesson_dir)
    seg_data = load_segments_json(os.path.join(args.lesson_dir, "segments.json"))
    res = validate_draft(draft, outline, seg_data)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def _get_lesson_title_for_notify(lesson_dir: str) -> str:
    try:
        from rt.pipeline.outline import load_outline
        return load_outline(lesson_dir).lesson_title
    except Exception:
        return os.path.basename(os.path.abspath(lesson_dir))


def cmd_review(args):
    if not getattr(args, "mock", False):
        _ensure_config_ready(["review"])
    if getattr(args, "reset", False):
        from rt.pipeline.ledger import purge_decisions_by_prefix
        removed = purge_decisions_by_prefix(args.lesson_dir, prefix="sci_")
        print(f"🔄 Reset: rimosse {removed} decisioni scientifiche precedenti (le issue esistenti restano invariate).")

    force = getattr(args, "force", False)
    res = run_review(args.lesson_dir, force=force, force_mock=args.mock)
    _print_phase_action("review", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))
    
    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if not res.get("skipped") and channel == "telegram":
        from rt.telegram.notify import notify_issues_ready
        notify_issues_ready(args.lesson_dir, "science", res.get("total_science_issues", 0))

    auto_accept = getattr(args, "auto_accept", None)
    history = getattr(args, "history", False)
    run_interactive_review(args.lesson_dir, "science", channel=channel, auto_accept=auto_accept, history=history)


def cmd_recall(args):
    if getattr(args, "check", False) is True:
        from rt.pipeline.recall_session import run_stale_recall_check
        run_stale_recall_check(args.lesson_dir)
        return

    reset_val = getattr(args, "reset", None)
    if isinstance(reset_val, str) and reset_val in ("all", "quiz", "mirata", "vasta"):
        from rt.pipeline.recall import purge_recall_by_type
        from rt.core.models import RecallQuestionType
        qtype = None if reset_val == "all" else RecallQuestionType(reset_val)
        count = purge_recall_by_type(args.lesson_dir, qtype)
        type_str = reset_val if reset_val != "all" else "tutti i tipi"
        print(f"🗑 Rimossi {count} elementi di recall per {type_str} da '{args.lesson_dir}'.")
        return

    from rt.core.idempotency import check_phase_status, PhaseStatus

    status, reason = check_phase_status(args.lesson_dir, "rewrite")
    if status != PhaseStatus.VALID:
        print(
            f"❌ La lezione non ha un draft valido ({reason}).\n"
            f"   Il recall pesca le domande dal draft: esegui prima 'rt rewrite \"{args.lesson_dir}\"'.",
            file=sys.stderr
        )
        sys.exit(1)

    order = getattr(args, "order", "alternato")
    style = getattr(args, "style", None)
    force_mock = getattr(args, "mock", False)

    if not force_mock:
        cfg = _ensure_config_ready([])
        from rt.telegram import recall_preferences
        effective_style = style or recall_preferences.get_active_style(cfg.telegram.state_dir)
        jobs_needed = [f"recall_{effective_style}"]
        if effective_style in ("mirata", "vasta"):
            jobs_needed.append(f"recall_eval_{effective_style}")
        _ensure_config_ready(jobs_needed)

    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    from rt.pipeline.recall_session import start_recall_via_telegram, run_recall_terminal_session
    if channel == "telegram":
        start_recall_via_telegram(args.lesson_dir, order=order, style=style, force_mock=force_mock)
    else:
        run_recall_terminal_session(args.lesson_dir, order=order, style=style, force_mock=force_mock)





def cmd_add_images(args):
    if not getattr(args, "input", None) and not getattr(args, "web_search", None):
        print("❌ Nessuna sorgente di immagini indicata. Usa -i <pdf_o_cartella> e/o --web-search N.", file=sys.stderr)
        sys.exit(1)
    if not getattr(args, "mock", False):
        _ensure_config_ready(["image_description", "image_unit_judge"])
    from rt.pipeline.add_images import run_add_images
    try:
        res = run_add_images(
            args.lesson_dir,
            input_path=args.input,
            web_search_count=args.web_search,
            carousel=args.carousel,
            force_mock=args.mock,
        )
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ {res['images_added']} immagini aggiunte, {len(res['macros_with_images'])} sezioni coinvolte.")
    print(f"  - {res['deliverable_md']}")


def _normalize_with_review(value) -> Tuple[bool, bool]:
    """Ritorna (run_asr, run_sci). ASR rimosso, run_sci = bool(value)."""
    if not value:
        return False, False
    return False, True


def normalize_review_cli_args(argv: List[str]) -> List[str]:
    """
    Normalizza gli argomenti della CLI per supportare sintassi flessibili.
    """
    known_commands = {"review"}
    if not any(cmd in argv for cmd in known_commands):
        return argv
    known_levels = {"all"}
    flags = {"--auto-accept"}
    new_argv = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in flags:
            new_argv.append(arg)
            if i + 1 < len(argv) and argv[i + 1].lower() in known_levels:
                new_argv.append(argv[i + 1].lower())
                i += 2
                continue
            else:
                new_argv.append("all")
                i += 1
                continue
        new_argv.append(arg)
        i += 1
    return new_argv


def cmd_build(args):
    force = getattr(args, "force", False)
    res = run_build(args.lesson_dir, force=force, rename_folder=args.rename)
    _print_phase_action("build", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))

    final_dir = res.get("lesson_dir") or args.lesson_dir
    from rt.telegram.notify import notify_build_completed
    notify_build_completed(final_dir, res, lesson_title=_get_lesson_title_for_notify(final_dir))


def cmd_setup(args):
    """Setup nativo per l'ingest di file audio, trascrizione macparakeet-cli e metadati."""
    from rt.pipeline.setup import run_setup, SetupError, DEFAULT_MODEL
    try:
        res = run_setup(
            audio=args.audio,
            date=args.date,
            materia=args.materia,
            argomenti=args.argomenti,
            dest_dir=args.dest_dir,
            model=getattr(args, "model", None) or DEFAULT_MODEL,
            skip_transcribe=args.skip_transcribe,
            force=args.force,
            mock_asr=args.mock,
            interactive=True
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
    except SetupError as e:
        print(f"❌ Errore Setup: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    from rt.core.idempotency import check_phase_status
    from rt.core.state import compute_effective_workflow_state
    from rt.core.models import ScienceType
    lesson_dir = args.lesson_dir
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path) if os.path.isfile(yaml_path) else {}
    manifest = load_manifest(lesson_dir)
    
    ledger = load_ledger(lesson_dir)
    sci_issues = load_science_issues(lesson_dir)
    decisions = ledger.decisions
    decided_ids = {d.issue_id for d in decisions}

    sci_docente = sum(1 for x in sci_issues if x.type == ScienceType.ERR_DOCENTE)
    sci_reconstruction = sum(1 for x in sci_issues if x.type == ScienceType.ERR_RECONSTRUCTION)
    sci_check = sum(1 for x in sci_issues if x.type == ScienceType.SCIENCE_CHECK)

    dec_accepted = sum(1 for d in decisions if d.decision == "accepted")
    dec_rejected = sum(1 for d in decisions if d.decision == "rejected")
    dec_edited = sum(1 for d in decisions if d.decision == "edited")
    dec_auto = sum(1 for d in decisions if getattr(d, "resolved_by", "").startswith("auto") or getattr(d, "resolved_by", "") == "cli_auto")
    dec_user = len(decisions) - dec_auto

    pending_sci = [x for x in sci_issues if x.id not in decided_ids]
    total_pending = len(pending_sci)

    effective_state = compute_effective_workflow_state(lesson_dir)
    recorded_state = info.get("fase_corrente", "non_inizializzata")

    phases = ["prepare", "outline", "rewrite", "review", "build"]
    phase_statuses = {}

    print(f"\n📊 STATO WORKFLOW RT 2.0: {os.path.abspath(lesson_dir)}")
    if effective_state and effective_state.value != recorded_state:
        print(f"Stato registrato (info.yaml): {recorded_state}")
        print(f"Stato effettivo calcolato:    {effective_state.value} (disallineato da modifiche upstream o review)")
    else:
        print(f"Stato globale (WorkflowState): {recorded_state}")

    print("\nFreschezza Fasi / Artefatti:")
    for ph in phases:
        st, reason = check_phase_status(lesson_dir, ph)
        phase_statuses[ph] = {
            "status": st.value,
            "reason": reason
        }
        print(f"  [{st.value:<7}] {ph:<15} - {reason}")
    print()

    if getattr(args, "issues", False):
        print("=" * 60)
        print("🔍 REPORT DIAGNOSTICO DETTAGLIATO ISSUE & DECISION LEDGER")
        print("=" * 60)
        print(f"Science Issues ({len(sci_issues)} totali):")
        print(f"  ERR_DOCENTE:                {sci_docente}")
        print(f"  ERR_RECONSTRUCTION:         {sci_reconstruction}")
        print(f"  SCIENCE_CHECK:              {sci_check}")
        print()
        print(f"Decision Ledger ({len(decisions)} registrate):")
        print(f"  accepted:                   {dec_accepted}")
        print(f"  rejected:                   {dec_rejected}")
        print(f"  edited:                     {dec_edited}")
        print(f"  auto-applied:               {dec_auto}")
        print(f"  user/manual:                {dec_user}")
        print()
        print(f"Stato di Risoluzione:")
        print(f"  Totale issue rilevate:      {len(sci_issues)}")
        print(f"  Decisioni archiviate:       {len(decisions)}")
        print(f"  Anomalie pendenti:          {total_pending} (Science: {len(pending_sci)})")
        print("=" * 60 + "\n")
    
    res = {
        "lesson_dir": os.path.abspath(lesson_dir),
        "fase_corrente": recorded_state,
        "stato_effettivo": effective_state.value if effective_state else recorded_state,
        "materia": info.get("materia"),
        "data": info.get("data"),
        "titolo": info.get("titolo"),
        "segment_count": manifest.segment_count if manifest else 0,
        "science_issues_total": len(sci_issues),
        "decisions_recorded": len(ledger.decisions),
        "pending_issues_total": total_pending,
        "phase_statuses": phase_statuses
    }
    if getattr(args, "issues", False):
        res["issues_breakdown"] = {
            "science": {"err_docente": sci_docente, "err_reconstruction": sci_reconstruction, "science_check": sci_check},
            "decisions": {"total": len(decisions), "accepted": dec_accepted, "rejected": dec_rejected, "edited": dec_edited, "auto_applied": dec_auto, "user": dec_user},
            "pending": {"total": total_pending, "science": len(pending_sci)}
        }
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))




def cmd_run(args):
    """Pipeline end-to-end completa con idempotenza, cost protection e supporto audio/cartella."""
    from rt.pipeline.setup import is_audio_file, run_setup, SetupError, DEFAULT_MODEL

    raw_inputs = args.input if isinstance(args.input, list) else [args.input]
    first_input = raw_inputs[0] if raw_inputs else ""
    force = getattr(args, "force", False)
    mock_mode = getattr(args, "mock", False)
    with_review = bool(getattr(args, "with_review", True))

    if not mock_mode:
        required = ["outline", "rewrite"]
        if with_review:
            required.append("review")
        _ensure_config_ready(required)

    is_audio_input = any(is_audio_file(x) for x in raw_inputs)
    total_steps = (6 if is_audio_input else 4) + int(with_review)

    if is_audio_input:
        print("\n" + "=" * 60)
        print("🎙️  RT 2.0 — PIPELINE END-TO-END DA SORGENTE AUDIO")
        print("=" * 60)
        print(f"File audio in ingresso: {', '.join(os.path.basename(x) for x in raw_inputs)}")

        step_offset = 2

        print(f"\n[1/{total_steps}] SETUP / AUDIO INGEST (Inizializzazione cartella e metadati)...")
        try:
            setup_res = run_setup(
                audio=raw_inputs,
                date=getattr(args, "date", None),
                materia=getattr(args, "materia", None),
                argomenti=getattr(args, "argomenti", None),
                dest_dir=getattr(args, "dest_dir", None),
                model=getattr(args, "model", None) or DEFAULT_MODEL,
                skip_transcribe=getattr(args, "skip_transcribe", False),
                force=force,
                mock_asr=mock_mode,
                interactive=True,
                on_progress=print
            )
            lesson_dir = setup_res["lesson_dir"]
        except SetupError as se:
            print(f"❌ Errore durante l'ingest audio: {se}", file=sys.stderr)
            sys.exit(1)

        if mock_mode:
            print(f"\n[2/{total_steps}] MACWHISPER TRANSCRIPTION (ASR Timecoded)...")
            print("⏩ [MOCK ASR] Trascrizione deterministica generata offline a costo zero.")
        elif getattr(args, "skip_transcribe", False):
            print(f"\n[2/{total_steps}] MACWHISPER TRANSCRIPTION (ASR Timecoded)...")
            print("⚠️  [SKIP] Trascrizione saltata (--skip-transcribe). Stato impostato su METADATA_ONLY.")
            print("La pipeline si arresta qui. Esegui la trascrizione per procedere con 'rt prepare'.")
            return
        else:
            print(f"✔ Trascrizione completata: {setup_res.get('trascritto_json')}")
    else:
        lesson_dir = first_input
        print("\n" + "=" * 60)
        print(f"🚀 RT 2.0 — PIPELINE END-TO-END PER: {lesson_dir}")
        print("=" * 60)

        step_offset = 0

    prep_res = run_prepare(lesson_dir, force=force)
    prep_details = f"Segmenti già validi ({prep_res['segment_count']} segmenti, {prep_res['duration_seconds']:.1f}s)" if prep_res.get("skipped") else f"Segmenti estratti: {prep_res['segment_count']} ({prep_res['duration_seconds']:.1f}s)"
    _print_phase_action("prepare", prep_res, step=step_offset + 1, total_steps=total_steps, description="Parsing deterministico segmenti", details=prep_details)

    out_res = run_outline(lesson_dir, force=force, force_mock=mock_mode)
    out_details = f"Outline già valida ({out_res['validation_report']['units_count']} unità didattiche, 0 chiamate LLM)" if out_res.get("skipped") else f"Outline validata: {out_res['validation_report']['units_count']} unità didattiche ({out_res['validation_report']['coverage_percentage']}% copertura)"
    _print_phase_action("outline", out_res, step=step_offset + 2, total_steps=total_steps, description="Scaletta gerarchica didattica", details=out_details)

    confirm_or_revise_outline(lesson_dir, force=force, force_mock=mock_mode)

    rew_res = run_rewrite(lesson_dir, force=force, force_mock=mock_mode)
    rew_details = f"Draft già valido ({rew_res['total_units']} unità verificate, 0 chiamate LLM)" if rew_res.get("skipped") else f"Rielaborate {rew_res['processed_units']}/{rew_res['total_units']} unità. Provenance verificata."
    _print_phase_action("rewrite", rew_res, step=step_offset + 3, total_steps=total_steps, description="Rielaborazione fluida a finestre con provenance", details=rew_details)

    next_step = step_offset + 4
    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if with_review:
        sci_res = run_review(lesson_dir, force=force, force_mock=mock_mode)
        sci_details = f"Review scientifica già completata ({sci_res['total_science_issues']} issue note, 0 chiamate LLM)" if sci_res.get("skipped") else f"Issue scientifiche: {sci_res['total_science_issues']} (Docente: {sci_res['docente_issues']}, Ricostruzione: {sci_res['reconstruction_issues']}, Check: {sci_res['science_checks']})"
        _print_phase_action("review", sci_res, step=next_step, total_steps=total_steps, description="Critic indipendente su docente e allucinazioni", details=sci_details)

        auto_accept_val = "all" if getattr(args, "auto_accept", False) else None
        if not run_interactive_review(lesson_dir, "science", channel=channel, auto_accept=auto_accept_val):
            print(f"\n⏸  In attesa che la revisione scientifica venga completata (Telegram, oppure esegui 'rt review \"{lesson_dir}\"' da terminale). "
                  f"Esegui poi 'rt build \"{lesson_dir}\"' per finalizzare.")
            return
        next_step += 1

    build_step_num = next_step

    bld_res = run_build(lesson_dir, force=force, rename_folder=args.rename)
    bld_details = "Documenti finali già generati e aggiornati." if bld_res.get("skipped") else (
        "File finali generati con successo:\n"
        f"  - Rielaborato: {bld_res['rielaborato']}\n"
        f"  - Pre-elaborato: {bld_res['pre_elaborato']}\n"
        f"  - Errori concettuali: {bld_res['errori_concettuali']}\n"
        f"  - Problemi scientifici: {bld_res['problemi_scientifici']}"
    )
    _print_phase_action("build", bld_res, step=build_step_num, total_steps=total_steps, description="Finalizzazione deterministica Markdown", details=bld_details)
    print("\n✨ PIPELINE COMPLETATA CON SUCCESSO!")

    if not mock_mode:
        from rt.telegram.notify import notify_build_completed
        final_dir = bld_res.get("lesson_dir") or lesson_dir
        notify_build_completed(final_dir, bld_res, lesson_title=_get_lesson_title_for_notify(final_dir))

    from rt.llm.telemetry import GLOBAL_TELEMETRY
    summary = GLOBAL_TELEMETRY.get_summary()
    if summary["total_requests"] > 0:
        print("\n" + "=" * 60)
        print("💰 RIEPILOGO COSTI SESSIONE")
        print("=" * 60)
        for job_name, job_stats in summary["by_job"].items():
            print(f"  {job_name:<16} {job_stats['requests']:>3} richieste  ${job_stats['estimated_cost_usd']:.6f}")
        print(f"  {'TOTALE':<16}     ${summary['total_estimated_cost_usd']:.6f}")
        print("=" * 60)


def cmd_telegram_daemon(args):
    from rt.telegram.daemon import run_daemon
    run_daemon(state_dir=getattr(args, "state_dir", None))


class RTHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            orig_subactions = action._get_subactions
            action._get_subactions = lambda: [a for a in orig_subactions() if a.help != argparse.SUPPRESS]
            res = super()._format_action(action)
            action._get_subactions = orig_subactions
            return res
        return super()._format_action(action)


def cmd_config(args: argparse.Namespace) -> None:
    if getattr(args, "models", False):
        from rt.pipeline.configure import run_models_management
        run_models_management()
    elif getattr(args, "telegram", False):
        from rt.pipeline.configure import run_telegram_only
        run_telegram_only()
    elif getattr(args, "topics", False):
        from rt.pipeline.configure import run_topics_management
        run_topics_management()
    else:
        from rt.pipeline.configure import run_config_wizard
        run_config_wizard()


def main():
    load_env_file(override=True)
    from rt.pipeline.setup import DEFAULT_MODEL, configure_setup_parser
    epilog_text = (
        "Comandi diagnostici (uso avanzato):\n"
        "  validate-outline    Valida deterministicamente l'outline\n"
        "  validate-draft      Valida il draft rielaborato"
    )
    parser = argparse.ArgumentParser(
        prog="rt",
        description="Academic Lecture Transcription & Reconstruction Workflow",
        epilog=epilog_text,
        formatter_class=RTHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # config
    p_cfg = subparsers.add_parser("config", help="Wizard interattivo di configurazione guidata (provider LLM, Telegram, STT, pricing)")
    from rt.pipeline.configure import configure_config_parser
    configure_config_parser(p_cfg)
    p_cfg.set_defaults(func=cmd_config)

    # run
    p_run = subparsers.add_parser("run", help="Esegue l'intera pipeline end-to-end (accetta file audio o cartella lezione)")
    p_run.add_argument("input", nargs="+", help="File audio (.m4a, .wav...) o cartella lezione esistente")
    p_run.add_argument("-d", "--date", help="Data della lezione (se input è audio)")
    p_run.add_argument("-m", "--materia", help="Nome della materia (se input è audio)")
    p_run.add_argument("-a", "--argomenti", help="Argomenti trattati (se input è audio)")
    p_run.add_argument("-o", "--dest-dir", help="Directory base di destinazione per nuova lezione")
    p_run.add_argument("--model", default=DEFAULT_MODEL, help=f"Modello macparakeet-cli per trascrizione (default: {DEFAULT_MODEL})")
    p_run.add_argument("--skip-transcribe", action="store_true", help="Salta trascrizione e crea segnaposto METADATA_ONLY")
    p_run.add_argument("--force", action="store_true", help="Forza l'intera pipeline ignorando i risultati precedenti")
    p_run.add_argument("--mock", action="store_true", help="Usa mock deterministico per ASR e LLM")
    p_run.add_argument(
        "--with-review", nargs="?", const="all", choices=["all", "asr", "science"], default=None,
        dest="with_review",
        help="Include anche la review nella run."
    )
    p_run.add_argument("--auto-accept", action="store_true", help="Auto-accetta revisioni senza blocchi interattivi")
    p_run.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_run.add_argument("--channel", choices=["terminal", "telegram"], default=None,
                        help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)")
    p_run.set_defaults(func=cmd_run)

    # setup
    p_set = subparsers.add_parser("setup", help="Esegue l'ingest di file audio, trascrizione macparakeet-cli e metadati")
    configure_setup_parser(p_set)
    p_set.set_defaults(func=cmd_setup)

    # prepare
    p_prep = subparsers.add_parser("prepare", help="Valida cartella ed estrae segmenti temporali")
    p_prep.add_argument("lesson_dir", help="Directory della lezione")
    p_prep.add_argument("--force", action="store_true", help="Forza la ripreparazione ignorando gli artefatti esistenti")
    p_prep.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_prep.set_defaults(func=cmd_prepare)

    # outline
    p_out = subparsers.add_parser("outline", help="Genera outline strutturata con LLM")
    p_out.add_argument("lesson_dir", help="Directory della lezione")
    p_out.add_argument("--force", action="store_true", help="Forza la rigenerazione dell'outline")
    p_out.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_out.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_out.set_defaults(func=cmd_outline)

    # rewrite
    p_rew = subparsers.add_parser("rewrite", help="Rielabora le unità didattiche a finestre con provenance")
    p_rew.add_argument("lesson_dir", help="Directory della lezione")
    p_rew.add_argument("--unit", help="ID specifica unità da rielaborare")
    p_rew.add_argument("--force", action="store_true", help="Forza la rielaborazione (o la sola unità indicata)")
    p_rew.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_rew.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rew.set_defaults(func=cmd_rewrite)

    # review
    p_rsci = subparsers.add_parser("review", help="Science critic indipendente e revisione")
    p_rsci.add_argument("lesson_dir", help="Directory della lezione")
    p_rsci.add_argument("--force", action="store_true", help="Forza la riesecuzione della critica scientifica")
    p_rsci.add_argument("--reset", action="store_true", help="Reimposta come pendenti le decisioni scientifiche esistenti senza rigenerare le issue (debug/test)")
    p_rsci.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_rsci.add_argument(
        "--auto-accept",
        dest="auto_accept",
        default=None,
        help="Auto-accetta le proposte scientifiche ('all' per accettare tutto)."
    )
    p_rsci.add_argument(
        "--history",
        action="store_true",
        help="Mostra anche le issue già decise per una eventuale rivalutazione (solo terminale)"
    )
    p_rsci.add_argument(
        "--channel",
        choices=["terminal", "telegram"],
        default=None,
        help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)"
    )
    p_rsci.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rsci.set_defaults(func=cmd_review)

    # recall
    p_recall = subparsers.add_parser("recall", help="Sessione di active recall (quiz/mirata/vasta) su una lezione già rielaborata")
    p_recall.add_argument("lesson_dir", help="Directory della lezione")
    p_recall.add_argument("--order", choices=["sequenziale", "alternato", "casuale"], default="alternato",
                           help="Ordine di proposta delle domande per questa sessione (default: alternato)")
    p_recall.add_argument("--channel", choices=["terminal", "telegram"], default=None,
                           help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)")
    p_recall.add_argument("--style", choices=["quiz", "mirata", "vasta"], default=None,
                           help="Tipo di domanda per questa sessione; se passato, aggiorna anche lo stile attivo globale (default: stile attivo corrente)")
    p_recall.add_argument(
        "--reset", nargs="?", const="all", choices=["all", "quiz", "mirata", "vasta"], default=None,
        help="Resetta le domande/risposte di recall già effettuate: senza valore o 'all' azzera "
             "tutto, 'quiz'/'mirata'/'vasta' azzera solo quel tipo."
    )
    p_recall.add_argument("--check", action="store_true", help="Revisione interattiva da terminale delle domande stale per modifica dell'unità")
    p_recall.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM reale)")
    p_recall.set_defaults(func=cmd_recall)

    # build
    p_bld = subparsers.add_parser("build", help="Finalizzazione deterministica dei Markdown")
    p_bld.add_argument("lesson_dir", help="Directory della lezione")
    p_bld.add_argument("--force", action="store_true", help="Forza la rigenerazione di tutti i Markdown")
    p_bld.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_bld.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_bld.set_defaults(func=cmd_build)

    # add-images
    p_addimg = subparsers.add_parser("add-images", help="Integra slide/foto (o immagini trovate sul web) nel documento finale, per macro-sezione")
    p_addimg.add_argument("lesson_dir", help="Directory della lezione")
    p_addimg.add_argument("-i", "--input", default=None, help="Percorso a un file PDF di slide o una cartella di foto")
    p_addimg.add_argument(
        "--web-search", nargs="?", const=5, type=int, default=None,
        help="Cerca e integra N immagini dal web via SearXNG (default 5 se il flag è usato senza valore). "
             "Combinabile con -i. Richiede 'searxng_base_url' configurato in config/general.yaml."
    )
    p_addimg.add_argument("--carousel", action="store_true", help="Raggruppa le immagini di ogni sezione in un blocco carosello (plugin Obsidian napkin-notes) invece di righe immagine singole")
    p_addimg.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM/vision reale)")
    p_addimg.set_defaults(func=cmd_add_images)

    # status
    p_stat = subparsers.add_parser("status", help="Mostra lo stato della lezione")
    p_stat.add_argument("lesson_dir", help="Directory della lezione")
    p_stat.add_argument("--issues", action="store_true", help="Mostra report diagnostico dettagliato delle issue e del ledger")
    p_stat.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo dello stato")
    p_stat.set_defaults(func=cmd_status)

    # telegram-daemon
    p_tgd = subparsers.add_parser("telegram-daemon", help="Avvia il daemon Telegram persistente per bottoni/feedback")
    p_tgd.add_argument("--state-dir", default=None, help="Override della cartella di stato Telegram (default: da config)")
    p_tgd.set_defaults(func=cmd_telegram_daemon)

    # validate-outline
    p_vout = subparsers.add_parser("validate-outline", help=argparse.SUPPRESS)
    p_vout.add_argument("lesson_dir", help="Directory della lezione")
    p_vout.set_defaults(func=cmd_validate_outline)

    # validate-draft
    p_vdr = subparsers.add_parser("validate-draft", help=argparse.SUPPRESS)
    p_vdr.add_argument("lesson_dir", help="Directory della lezione")
    p_vdr.set_defaults(func=cmd_validate_draft)

    normalized_argv = normalize_review_cli_args(sys.argv[1:])
    args = parser.parse_args(normalized_argv)
    from rt.llm.errors import LLMFailure
    from pydantic import ValidationError
    try:
        args.func(args)
    except ValidationError as e:
        print("\n" + "=" * 60, file=sys.stderr)
        print("❌ Errore nella configurazione in 'config/'", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"\n{e}\n", file=sys.stderr)
        print(
            "Correggi il file YAML indicato in 'config/' e riprova. "
            "Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi corretta.",
            file=sys.stderr
        )
        sys.exit(1)
    except LLMFailure as e:
        print("\n" + "=" * 60, file=sys.stderr)
        print("❌ ESECUZIONE INTERROTTA: errore LLM non recuperabile", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"\n{e}\n", file=sys.stderr)
        failure_class = getattr(e, "failure_class", None)
        if failure_class:
            print(f"Classe di errore: {failure_class}", file=sys.stderr)
        provider = getattr(e, "provider", None)
        model = getattr(e, "model", None)
        if provider or model:
            print(f"Provider/modello: {provider or '?'} / {model or '?'}", file=sys.stderr)
        print(
            "\nLa pipeline non ha trovato (o non ha configurato) una route alternativa per "
            "questo errore. Puoi:\n"
            "  - Rilanciare lo stesso comando: la pipeline riprende dal checkpoint salvato e, "
            "trattandosi spesso di provider stocastici (es. 'openrouter/free'), un nuovo tentativo "
            "può avere esito diverso;\n"
            "  - Modificare i file in 'config/' per il job coinvolto (es. aumentare 'max_output_chars', "
            "cambiare modello, o aggiungere un blocco 'fallback' se disponibile un'alternativa).\n",
            file=sys.stderr
        )
        sys.exit(1)
    except KeyboardInterrupt:
        # Chi solleva volontariamente Ctrl+C (es. l'attesa di conferma outline via
        # Telegram) stampa già un messaggio specifico prima di ri-sollevare: qui si
        # esce solo in modo pulito, senza traceback, con il codice di uscita POSIX
        # convenzionale per SIGINT.
        print("\n⏹ Interrotto dall'utente.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()

