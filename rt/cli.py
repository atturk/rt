"""
rt.cli
CLI unificata per il workflow accademico RT.
Comandi disponibili:
  rt prepare            <cartella>
  rt outline            <cartella> [--mock]
  rt validate-outline   <cartella>
  rt rewrite            <cartella> [--unit <id>] [--mock]
  rt validate-draft     <cartella>
  rt review-asr         <cartella> [--mock]
  rt review-science     <cartella> [--mock]
  rt review             <cartella> (revisione interattiva casi YELLOW/RED)
  rt build              <cartella> [--no-rename] (rinomina la cartella col titolo finale, attivo di default)
  rt status             <cartella>
  rt test-llm           [--config <path>] (smoke test rapido DeepSeek/OpenRouter/Google)
  rt prices-check       (confronta i prezzi configurati con il catalogo live LiteLLM)
  rt prices-lookup      <query> [--provider <p>] (cerca il prezzo live nel catalogo LiteLLM)
  rt run                <cartella> [--mock]
"""

import sys
import os
import argparse
import json
import re
from typing import Dict, Any, List, Optional

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
from rt.pipeline.review_asr import run_review_asr, load_asr_issues
from rt.pipeline.review_science import run_review_science, load_science_issues
from rt.pipeline.issue_review import run_interactive_review, should_auto_accept_asr, should_auto_accept_science
from rt.pipeline.ledger import load_ledger, record_decision, sanitize_suggested_fix
from rt.pipeline.build import run_build
from rt.core.models import ASRLevel, ASRIssue, ScienceIssue



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


def _print_phase_action(phase_name: str, res: Dict[str, Any]):
    action = res.get("action", "RUN")
    reason = res.get("reason", "")
    if action == "SKIP":
        print(f"\n[SKIP] {phase_name}\nReason: {reason}\n")
    elif action == "FORCE":
        print(f"\n[FORCE] {phase_name}\nReason: {reason}\n")
    else:
        print(f"\n[RUN] {phase_name}\nReason: {reason}\n")


def cmd_prepare(args):
    force = getattr(args, "force", False)
    res = run_prepare(args.lesson_dir, force=force)
    _print_phase_action("prepare", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_outline(args):
    if not getattr(args, "mock", False):
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
        job_cfg = cfg.jobs.get("outline")
        if not _job_has_configured_route(job_cfg):
            print(_job_config_hint("outline"), file=sys.stderr)
            sys.exit(1)
    force = getattr(args, "force", False)
    res = run_outline(args.lesson_dir, force=force, force_mock=args.mock)
    _print_phase_action("outline", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))

    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel
    confirm_or_revise_outline(args.lesson_dir, channel=channel, force=force, force_mock=args.mock)


def cmd_validate_outline(args):
    outline = load_outline(args.lesson_dir)
    seg_data = load_segments_json(os.path.join(args.lesson_dir, "segments.json"))
    res = validate_outline(outline, seg_data)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_rewrite(args):
    if not getattr(args, "mock", False):
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
        job_cfg = cfg.jobs.get("rewrite")
        if not _job_has_configured_route(job_cfg):
            print(_job_config_hint("rewrite"), file=sys.stderr)
            sys.exit(1)
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


def cmd_review_asr(args):
    if not getattr(args, "mock", False):
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
        job_cfg = cfg.jobs.get("review_asr")
        if not _job_has_configured_route(job_cfg):
            print(_job_config_hint("review_asr"), file=sys.stderr)
            sys.exit(1)
    if getattr(args, "reset", False):
        from rt.pipeline.ledger import purge_decisions_by_prefix
        removed = purge_decisions_by_prefix(args.lesson_dir, prefix="asr_")
        print(f"🔄 Reset: rimosse {removed} decisioni ASR precedenti (le issue esistenti restano invariate).")

    force = getattr(args, "force", False)
    res = run_review_asr(args.lesson_dir, force=force, force_mock=args.mock)
    _print_phase_action("review-asr", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))
    
    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if not res.get("skipped") and channel == "telegram":
        from rt.telegram.notify import notify_issues_ready
        notify_issues_ready(args.lesson_dir, "asr", res.get("total_issues", 0))

    from rt.pipeline.issue_review import run_interactive_review
    auto_accept = getattr(args, "auto_accept", None)
    history = getattr(args, "history", False)
    run_interactive_review(args.lesson_dir, "asr", channel=channel, auto_accept=auto_accept, history=history)


def cmd_review_science(args):
    if not getattr(args, "mock", False):
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
        job_cfg = cfg.jobs.get("review_science")
        if not _job_has_configured_route(job_cfg):
            print(_job_config_hint("review_science"), file=sys.stderr)
            sys.exit(1)
    if getattr(args, "reset", False):
        from rt.pipeline.ledger import purge_decisions_by_prefix
        removed = purge_decisions_by_prefix(args.lesson_dir, prefix="sci_")
        print(f"🔄 Reset: rimosse {removed} decisioni scientifiche precedenti (le issue esistenti restano invariate).")

    force = getattr(args, "force", False)
    res = run_review_science(args.lesson_dir, force=force, force_mock=args.mock)
    _print_phase_action("review-science", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))
    
    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if not res.get("skipped") and channel == "telegram":
        from rt.telegram.notify import notify_issues_ready
        notify_issues_ready(args.lesson_dir, "science", res.get("total_science_issues", 0))

    from rt.pipeline.issue_review import run_interactive_review
    auto_accept = getattr(args, "auto_accept", None)
    history = getattr(args, "history", False)
    run_interactive_review(args.lesson_dir, "science", channel=channel, auto_accept=auto_accept, history=history)


def cmd_recall(args):
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
        if not _has_real_config_source():
            print(
                "❌ Nessuna configurazione trovata (cartella 'config/' mancante).\n"
                "   Copia 'config.example/' in 'config/' e personalizza i modelli prima di eseguire questo comando:\n"
                "   cp -r config.example config",
                file=sys.stderr
            )
            sys.exit(1)

        from rt.core.config import load_config
        from rt.telegram import recall_preferences
        cfg = load_config()
        effective_style = style or recall_preferences.get_active_style(cfg.telegram.state_dir)
        jobs_needed = [f"recall_{effective_style}"]
        if effective_style in ("mirata", "vasta"):
            jobs_needed.append(f"recall_eval_{effective_style}")
        missing_jobs = [j for j in jobs_needed if not _job_has_configured_route(cfg.jobs.get(j))]
        if missing_jobs:
            print(
                f"❌ I seguenti job non hanno un provider configurato: {', '.join(missing_jobs)}.\n"
                f"   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
                f"   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
                f"   nei rispettivi file config/{{job}}.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
                file=sys.stderr
            )
            sys.exit(1)

    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    from rt.pipeline.recall_session import start_recall_via_telegram, run_recall_terminal_session
    if channel == "telegram":
        start_recall_via_telegram(args.lesson_dir, order=order, style=style, force_mock=force_mock)
    else:
        run_recall_terminal_session(args.lesson_dir, order=order, style=style, force_mock=force_mock)


from rt.pipeline.ledger import extract_context_sentence
from rt.pipeline.issue_review import should_auto_accept_asr, should_auto_accept_science




def normalize_review_cli_args(argv: List[str]) -> List[str]:
    """
    Normalizza gli argomenti della CLI per supportare sintassi flessibili come:
      --auto-accept
      --auto-accept yellow
    anche quando specificati prima o dopo il parametro posizionale lesson_dir.
    """
    known_commands = {"review-asr", "review-science"}
    if not any(cmd in argv for cmd in known_commands):
        return argv
    known_levels = {"yellow", "red", "all", "green"}
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

    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel
    if channel == "telegram":
        final_dir = res.get("lesson_dir") or args.lesson_dir
        from rt.telegram.notify import notify_build_completed
        notify_build_completed(final_dir, res, lesson_title=_get_lesson_title_for_notify(final_dir))


def cmd_setup(args):
    """Setup nativo per l'ingest di file audio, trascrizione MacWhisper e metadati."""
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
    asr_issues = load_asr_issues(lesson_dir)
    sci_issues = load_science_issues(lesson_dir)
    decisions = ledger.decisions
    decided_ids = {d.issue_id for d in decisions}

    # Calcoli dinamici (nessun valore hardcoded)
    asr_green = sum(1 for x in asr_issues if x.level == ASRLevel.GREEN)
    asr_yellow = sum(1 for x in asr_issues if x.level == ASRLevel.YELLOW)
    asr_red = sum(1 for x in asr_issues if x.level == ASRLevel.RED)

    sci_docente = sum(1 for x in sci_issues if x.type == ScienceType.ERR_DOCENTE)
    sci_reconstruction = sum(1 for x in sci_issues if x.type == ScienceType.ERR_RECONSTRUCTION)
    sci_check = sum(1 for x in sci_issues if x.type == ScienceType.SCIENCE_CHECK)

    dec_accepted = sum(1 for d in decisions if d.decision == "accepted")
    dec_rejected = sum(1 for d in decisions if d.decision == "rejected")
    dec_edited = sum(1 for d in decisions if d.decision == "edited")
    dec_auto = sum(1 for d in decisions if getattr(d, "resolved_by", "").startswith("auto") or getattr(d, "resolved_by", "") == "cli_auto")
    dec_user = len(decisions) - dec_auto

    pending_asr = [x for x in asr_issues if x.id not in decided_ids and x.level in (ASRLevel.YELLOW, ASRLevel.RED)]
    pending_sci = [x for x in sci_issues if x.id not in decided_ids]
    total_pending = len(pending_asr) + len(pending_sci)

    effective_state = compute_effective_workflow_state(lesson_dir)
    recorded_state = info.get("fase_corrente", "non_inizializzata")

    phases = ["prepare", "outline", "rewrite", "review_asr", "review_science", "build"]
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
        print(f"ASR Issues ({len(asr_issues)} totali):")
        print(f"  GREEN (auto-applicate):     {asr_green}")
        print(f"  YELLOW (coda di revisione): {asr_yellow}")
        print(f"  RED (ascolto richiesto):    {asr_red}")
        print()
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
        print(f"  Totale issue rilevate:      {len(asr_issues) + len(sci_issues)}")
        print(f"  Decisioni archiviate:       {len(decisions)}")
        print(f"  Anomalie pendenti:          {total_pending} (ASR: {len(pending_asr)}, Science: {len(pending_sci)})")
        print("=" * 60 + "\n")
    
    res = {
        "lesson_dir": os.path.abspath(lesson_dir),
        "fase_corrente": recorded_state,
        "stato_effettivo": effective_state.value if effective_state else recorded_state,
        "materia": info.get("materia"),
        "data": info.get("data"),
        "titolo": info.get("titolo"),
        "segment_count": manifest.segment_count if manifest else 0,
        "asr_issues_total": len(asr_issues),
        "science_issues_total": len(sci_issues),
        "decisions_recorded": len(ledger.decisions),
        "pending_issues_total": total_pending,
        "phase_statuses": phase_statuses
    }
    if getattr(args, "issues", False):
        res["issues_breakdown"] = {
            "asr": {"green": asr_green, "yellow": asr_yellow, "red": asr_red},
            "science": {"err_docente": sci_docente, "err_reconstruction": sci_reconstruction, "science_check": sci_check},
            "decisions": {"total": len(decisions), "accepted": dec_accepted, "rejected": dec_rejected, "edited": dec_edited, "auto_applied": dec_auto, "user": dec_user},
            "pending": {"total": total_pending, "asr": len(pending_asr), "science": len(pending_sci)}
        }
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_test_llm(args):
    """Smoke test rapido per verificare la connessione e i parametri con DeepSeek, OpenRouter o Google."""
    from rt.pipeline.smoke_test import run_smoke_test
    try:
        run_smoke_test(
            config_path=args.config,
            provider=args.provider,
            model=args.model,
            credential=getattr(args, "credential", None),
            stream=not args.no_stream if hasattr(args, "no_stream") and args.no_stream else None,
            show_monitor=not args.no_monitor if hasattr(args, "no_monitor") and args.no_monitor else None,
            verbose=True
        )
    except Exception as e:
        sys.exit(1)


def cmd_prices_check(args):
    from rt.core.config import load_config
    from rt.llm.pricing_sync import check_configured_pricing
    cfg = load_config()
    report = check_configured_pricing(cfg)
    print("\n💵 VERIFICA PREZZI CONFIGURATI vs CATALOGO LIVE (LiteLLM)\n" + "=" * 70)
    for entry in report:
        flag = "⚠ DA VERIFICARE" if entry.get("stale") else "✔"
        print(f"\n[{entry['job']}] {entry['provider']}/{entry['model']}  {flag}")
        print(f"  In uso oggi:  in=${entry['used_input_per_million']}/M  out=${entry['used_output_per_million']}/M")
        if entry["live_match"]:
            lm = entry["live_match"]
            print(f"  Live (LiteLLM, '{lm['key']}'): in=${lm['input_per_million']}/M  out=${lm['output_per_million']}/M")
            if "input_diff_pct" in entry:
                print(f"  Differenza input: {entry['input_diff_pct']}%")
        else:
            print("  Nessun match trovato nel catalogo live per questo modello.")
    print("\n" + "=" * 70)
    print("Nota: nessuna modifica è stata applicata automaticamente. Se un prezzo risulta")
    print("invecchiato, aggiornalo manualmente nella sezione 'pricing:' della configurazione in 'config/'.")

    if getattr(args, "interactive", False):
        if not _has_real_config_source():
            print(
                "❌ Nessuna configurazione trovata (cartella 'config/' mancante).\n"
                "   Impossibile applicare prezzi interattivamente senza file in 'config/'.",
                file=sys.stderr
            )
            sys.exit(1)

        applicable_entries = [e for e in report if e.get("live_match")]
        if not applicable_entries:
            print("Nessun prezzo live disponibile da applicare.")
            return

        import questionary
        from ruamel.yaml import YAML

        choices = []
        for entry in applicable_entries:
            lm = entry["live_match"]
            label = (
                f"[{entry['job']}] {entry['provider']}/{entry['model']}  "
                f"in uso: in=${entry['used_input_per_million']}/M out=${entry['used_output_per_million']}/M  →  "
                f"live: in=${lm['input_per_million']}/M out=${lm['output_per_million']}/M"
            )
            choices.append(questionary.Choice(title=label, value=entry, checked=bool(entry.get("stale"))))

        selected = questionary.checkbox(
            "Seleziona i prezzi da applicare (SPAZIO per selezionare/deselezionare la voce evidenziata, "
            "INVIO per confermare la selezione — le voci con ⚠ sono pre-selezionate, spostare il cursore "
            "da solo NON seleziona nulla):",
            choices=choices
        ).ask()

        if selected is None:
            print("Annullato, nessuna modifica applicata.")
            return

        if not selected:
            print("Nessuna voce selezionata, nessuna modifica applicata.")
            return

        print("\nStai per applicare questi prezzi:")
        for entry in selected:
            lm = entry["live_match"]
            print(f"  [{entry['job']}] {entry['provider']}/{entry['model']}  ->  in=${lm['input_per_million']}/M out=${lm['output_per_million']}/M")
        confirm = questionary.confirm(f"Confermi la scrittura in {len(set(e['job'] for e in selected))} file di config/?", default=False).ask()
        if not confirm:
            print("Annullato, nessuna modifica applicata.")
            return

        by_job: Dict[str, List[Dict[str, Any]]] = {}
        for entry in selected:
            by_job.setdefault(entry["job"], []).append(entry)

        config_dir = os.path.join(os.getcwd(), "config")
        from rt.core.config import find_job_yaml_paths
        job_paths = find_job_yaml_paths(config_dir)
        for job_name, entries in by_job.items():
            job_file = job_paths.get(job_name)
            if not job_file:
                print(f"⚠️  File non trovato per il job '{job_name}' in config/ (saltato)", file=sys.stderr)
                continue

            yaml = YAML()
            with open(job_file, "r", encoding="utf-8") as f:
                data = yaml.load(f)

            if data is None:
                data = {}

            updated_models = []
            for entry in entries:
                path = entry.get("path")
                if not path:
                    continue
                node = data
                for step in path:
                    if isinstance(node, dict) and step in node:
                        node = node[step]
                    elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
                        node = node[step]
                    else:
                        node = None
                        break

                if node is not None and isinstance(node, dict):
                    node["pricing"] = {
                        "input_per_million": entry["live_match"]["input_per_million"],
                        "output_per_million": entry["live_match"]["output_per_million"],
                    }
                    updated_models.append(f"{entry['provider']}/{entry['model']}")

            with open(job_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f)

            cnt = len(updated_models)
            s = "prezzo aggiornato" if cnt == 1 else "prezzi aggiornati"
            models_str = ", ".join(updated_models)
            rel_path = os.path.relpath(job_file, os.getcwd())
            print(f"✔ {rel_path}: {cnt} {s} ({models_str})")


def cmd_prices_lookup(args):
    from rt.llm.pricing_sync import lookup_live_price
    results = lookup_live_price(args.query, provider_hint=getattr(args, "provider", None))
    if not results:
        print(f"Nessun modello trovato per '{args.query}'.")
        return
    print(f"\nRisultati per '{args.query}':\n" + "=" * 70)
    for r in results[:20]:
        print(f"  {r['key']:<55} in=${r['input_per_million']}/M  out=${r['output_per_million']}/M  ({r['provider']})")


def cmd_run(args):
    """Pipeline end-to-end completa con idempotenza, cost protection e supporto audio/cartella."""
    from rt.pipeline.setup import is_audio_file, run_setup, SetupError, DEFAULT_MODEL

    raw_inputs = args.input if isinstance(args.input, list) else [args.input]
    first_input = raw_inputs[0] if raw_inputs else ""
    force = getattr(args, "force", False)
    mock_mode = getattr(args, "mock", False)
    with_review = getattr(args, "with_review", False)

    if not mock_mode:
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
        missing = [j for j in ("outline", "rewrite", "review_asr", "review_science")
                   if not _job_has_configured_route(cfg.jobs.get(j))]
        if missing:
            print(
                f"❌ I seguenti job non hanno un provider configurato: {', '.join(missing)}.\n"
                "   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
                "   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
                "   nei rispettivi file config/<job>.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
                file=sys.stderr
            )
            sys.exit(1)

    is_audio_input = any(is_audio_file(x) for x in raw_inputs)

    if is_audio_input:
        print("\n" + "=" * 60)
        print("🎙️  RT 2.0 — PIPELINE END-TO-END DA SORGENTE AUDIO")
        print("=" * 60)
        print(f"File audio in ingresso: {', '.join(os.path.basename(x) for x in raw_inputs)}")

        from rt.core.config import load_config as _load_cfg_for_staleness
        from rt.llm.pricing_sync import get_cache_age_days
        _cfg_staleness = _load_cfg_for_staleness()
        _staleness_days = getattr(_cfg_staleness, "pricing_staleness_warning_days", 7)
        if _staleness_days > 0:
            _cache_age = get_cache_age_days()
            if _cache_age is None or _cache_age > _staleness_days:
                print(f"ℹ️  I prezzi configurati non sono stati verificati con 'rt prices-check' da oltre {_staleness_days} giorni "
                      f"(o mai). Le stime di costo potrebbero non riflettere i prezzi reali attuali.")

        step_offset = 2
        total_steps = 8 if with_review else 6

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

        from rt.core.config import load_config as _load_cfg_for_staleness
        from rt.llm.pricing_sync import get_cache_age_days
        _cfg_staleness = _load_cfg_for_staleness()
        _staleness_days = getattr(_cfg_staleness, "pricing_staleness_warning_days", 7)
        if _staleness_days > 0:
            _cache_age = get_cache_age_days()
            if _cache_age is None or _cache_age > _staleness_days:
                print(f"ℹ️  I prezzi configurati non sono stati verificati con 'rt prices-check' da oltre {_staleness_days} giorni "
                      f"(o mai). Le stime di costo potrebbero non riflettere i prezzi reali attuali.")

        step_offset = 0
        total_steps = 6 if with_review else 4

    print(f"\n[{step_offset + 1}/{total_steps}] PREPARE (Parsing deterministico segmenti)...")
    prep_res = run_prepare(lesson_dir, force=force)
    if prep_res.get("skipped"):
        print(f"⏩ [SKIP] Segmenti già validi ({prep_res['segment_count']} segmenti, {prep_res['duration_seconds']:.1f}s)")
    else:
        print(f"✔ Segmenti estratti: {prep_res['segment_count']} ({prep_res['duration_seconds']:.1f}s)")

    print(f"\n[{step_offset + 2}/{total_steps}] OUTLINE (Scaletta gerarchica didattica)...")
    out_res = run_outline(lesson_dir, force=force, force_mock=mock_mode)
    if out_res.get("skipped"):
        print(f"⏩ [SKIP] Outline già valida ({out_res['validation_report']['units_count']} unità didattiche, 0 chiamate LLM)")
    else:
        print(f"✔ Outline validata: {out_res['validation_report']['units_count']} unità didattiche ({out_res['validation_report']['coverage_percentage']}% copertura)")

    channel = getattr(args, "channel", None)
    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel
    confirm_or_revise_outline(lesson_dir, channel=channel, force=force, force_mock=mock_mode)

    print(f"\n[{step_offset + 3}/{total_steps}] REWRITE (Rielaborazione fluida a finestre con provenance)...")
    rew_res = run_rewrite(lesson_dir, force=force, force_mock=mock_mode)
    if rew_res.get("skipped"):
        print(f"⏩ [SKIP] Draft già valido ({rew_res['total_units']} unità verificate, 0 chiamate LLM)")
    else:
        print(f"✔ Rielaborate {rew_res['processed_units']}/{rew_res['total_units']} unità. Provenance verificata.")

    if with_review:
        print(f"\n[{step_offset + 4}/{total_steps}] ASR REVIEW (Ambiguità fonetiche e Confidence Gating)...")
        asr_res = run_review_asr(lesson_dir, force=force, force_mock=mock_mode)
        if asr_res.get("skipped"):
            print(f"⏩ [SKIP] Review ASR già completata ({asr_res['total_issues']} issue note, 0 chiamate LLM)")
        else:
            print(f"✔ Issue ASR: {asr_res['total_issues']} (Verdi auto: {asr_res['green_auto_applied']}, Gialle: {asr_res['yellow_review_queue']}, Rosse: {asr_res['red_human_required']})")

        auto_accept_val = "all" if getattr(args, "auto_accept", False) else None
        asr_ok = run_interactive_review(lesson_dir, "asr", channel=channel, auto_accept=auto_accept_val)
        if not asr_ok:
            print(f"\n⏸  In attesa che la revisione ASR venga completata (Telegram, oppure esegui 'rt review-asr \"{lesson_dir}\"' da terminale). "
                  f"Esegui poi 'rt build \"{lesson_dir}\"' per finalizzare.")
            return

        print(f"\n[{step_offset + 5}/{total_steps}] SCIENCE REVIEW (Critic indipendente su docente e allucinazioni)...")
        sci_res = run_review_science(lesson_dir, force=force, force_mock=mock_mode)
        if sci_res.get("skipped"):
            print(f"⏩ [SKIP] Review scientifica già completata ({sci_res['total_science_issues']} issue note, 0 chiamate LLM)")
        else:
            print(f"✔ Issue scientifiche: {sci_res['total_science_issues']} (Docente: {sci_res['docente_issues']}, Ricostruzione: {sci_res['reconstruction_issues']}, Check: {sci_res['science_checks']})")

        sci_ok = run_interactive_review(lesson_dir, "science", channel=channel, auto_accept=auto_accept_val)
        if not sci_ok:
            print(f"\n⏸  In attesa che la revisione scientifica venga completata (Telegram, oppure esegui 'rt review-science \"{lesson_dir}\"' da terminale). "
                  f"Esegui poi 'rt build \"{lesson_dir}\"' per finalizzare.")
            return

        build_step_num = step_offset + 6
    else:
        build_step_num = step_offset + 4

    print(f"\n[{build_step_num}/{total_steps}] BUILD (Finalizzazione deterministica Markdown)...")

    bld_res = run_build(lesson_dir, force=force, rename_folder=args.rename)
    if bld_res.get("skipped"):
        print("⏩ [SKIP] Documenti finali già generati e aggiornati.")
    else:
        print("✔ File finali generati con successo:")
        print(f"  - Rielaborato: {bld_res['rielaborato']}")
        print(f"  - Pre-elaborato: {bld_res['pre_elaborato']}")
        print(f"  - Revisioni ASR: {bld_res['revisioni_asr']}")
        print(f"  - Errori concettuali: {bld_res['errori_concettuali']}")
        print(f"  - Problemi scientifici: {bld_res['problemi_scientifici']}")
    print("\n✨ PIPELINE COMPLETATA CON SUCCESSO!")

    if channel == "telegram":
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


def main():
    load_env_file(override=True)
    from rt.pipeline.setup import DEFAULT_MODEL, configure_setup_parser
    parser = argparse.ArgumentParser(prog="rt", description="Academic Lecture Transcription & Reconstruction Workflow")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    p_set = subparsers.add_parser("setup", help="Esegue l'ingest di file audio, trascrizione MacWhisper e metadati")
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
    p_out.add_argument("--channel", choices=["terminal", "telegram"], default=None,
                        help="Canale di conferma outline per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)")
    p_out.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_out.set_defaults(func=cmd_outline)

    # validate-outline
    p_vout = subparsers.add_parser("validate-outline", help="Valida deterministicamente l'outline")
    p_vout.add_argument("lesson_dir", help="Directory della lezione")
    p_vout.set_defaults(func=cmd_validate_outline)

    # rewrite
    p_rew = subparsers.add_parser("rewrite", help="Rielabora le unità didattiche a finestre con provenance")
    p_rew.add_argument("lesson_dir", help="Directory della lezione")
    p_rew.add_argument("--unit", help="ID specifica unità da rielaborare")
    p_rew.add_argument("--force", action="store_true", help="Forza la rielaborazione (o la sola unità indicata)")
    p_rew.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_rew.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rew.set_defaults(func=cmd_rewrite)

    # validate-draft
    p_vdr = subparsers.add_parser("validate-draft", help="Valida il draft rielaborato")
    p_vdr.add_argument("lesson_dir", help="Directory della lezione")
    p_vdr.set_defaults(func=cmd_validate_draft)

    # review-asr
    p_rasr = subparsers.add_parser("review-asr", help="Analisi ambiguità ASR, confidence gating e revisione")
    p_rasr.add_argument("lesson_dir", help="Directory della lezione")
    p_rasr.add_argument("--force", action="store_true", help="Forza la riesecuzione della revisione ASR")
    p_rasr.add_argument("--reset", action="store_true", help="Reimposta come pendenti le decisioni ASR esistenti senza rigenerare le issue (debug/test)")
    p_rasr.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_rasr.add_argument(
        "--auto-accept",
        dest="auto_accept",
        default=None,
        help="Auto-accetta le proposte: senza argomenti o 'all' accetta tutto. Con 'yellow' auto-accetta le gialle, con 'red' auto-accetta le rosse."
    )
    p_rasr.add_argument(
        "--history",
        action="store_true",
        help="Mostra anche le issue già decise per una eventuale rivalutazione (solo terminale)"
    )
    p_rasr.add_argument(
        "--channel",
        choices=["terminal", "telegram"],
        default=None,
        help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)"
    )
    p_rasr.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rasr.set_defaults(func=cmd_review_asr)

    # review-science
    p_rsci = subparsers.add_parser("review-science", help="Science critic indipendente e revisione")
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
    p_rsci.set_defaults(func=cmd_review_science)

    # recall
    p_recall = subparsers.add_parser("recall", help="Sessione di active recall (quiz/mirata/vasta) su una lezione già rielaborata")
    p_recall.add_argument("lesson_dir", help="Directory della lezione")
    p_recall.add_argument("--order", choices=["sequenziale", "alternato", "casuale"], default="alternato",
                           help="Ordine di proposta delle domande per questa sessione (default: alternato)")
    p_recall.add_argument("--channel", choices=["terminal", "telegram"], default=None,
                           help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)")
    p_recall.add_argument("--style", choices=["quiz", "mirata", "vasta"], default=None,
                           help="Tipo di domanda per questa sessione; se passato, aggiorna anche lo stile attivo globale (default: stile attivo corrente)")
    p_recall.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM reale)")
    p_recall.set_defaults(func=cmd_recall)

    # build
    p_bld = subparsers.add_parser("build", help="Finalizzazione deterministica dei Markdown")
    p_bld.add_argument("lesson_dir", help="Directory della lezione")
    p_bld.add_argument("--force", action="store_true", help="Forza la rigenerazione di tutti i Markdown")
    p_bld.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_bld.add_argument(
        "--channel",
        choices=["terminal", "telegram"],
        default=None,
        help="Canale per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)"
    )
    p_bld.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_bld.set_defaults(func=cmd_build)

    # status
    p_stat = subparsers.add_parser("status", help="Mostra lo stato della lezione")
    p_stat.add_argument("lesson_dir", help="Directory della lezione")
    p_stat.add_argument("--issues", action="store_true", help="Mostra report diagnostico dettagliato delle issue e del ledger")
    p_stat.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo dello stato")
    p_stat.set_defaults(func=cmd_status)

    # test-llm
    p_tllm = subparsers.add_parser("test-llm", help="Smoke test rapido per verificare DeepSeek, OpenRouter o Google")
    p_tllm.add_argument("--config", help="Percorso alternativo del file di configurazione", default=None)
    p_tllm.add_argument("--provider", help="Provider da testare (deepseek | openrouter | google)", choices=["deepseek", "openrouter", "google"], default=None)
    p_tllm.add_argument("--credential", help="Credenziale specifica da testare (es. google_1, google_2, openrouter, deepseek)", default=None)
    p_tllm.add_argument("--model", help="Modello specifico da testare (es. gemini-2.5-flash, deepseek-v4-flash, deepseek/deepseek-v4-pro)", default=None)
    p_tllm.add_argument("--no-stream", action="store_true", help="Disabilita lo streaming SSE")
    p_tllm.add_argument("--no-monitor", action="store_true", help="Disabilita il monitor progressivo da terminale")
    p_tllm.set_defaults(func=cmd_test_llm)

    # prices-check
    p_pc = subparsers.add_parser("prices-check", help="Confronta i prezzi configurati con il catalogo live LiteLLM")
    p_pc.add_argument("--interactive", action="store_true", help="Seleziona interattivamente quali prezzi live applicare ai file config/<job>.yaml")
    p_pc.set_defaults(func=cmd_prices_check)

    # prices-lookup
    p_pl = subparsers.add_parser("prices-lookup", help="Cerca il prezzo live di un modello nel catalogo LiteLLM")
    p_pl.add_argument("query", help="Stringa di ricerca (es. 'gemini-3.5-flash', 'deepseek-v4')")
    p_pl.add_argument("--provider", help="Filtra per provider LiteLLM (es. 'deepseek', 'gemini')", default=None)
    p_pl.set_defaults(func=cmd_prices_lookup)

    # run
    p_run = subparsers.add_parser("run", help="Esegue l'intera pipeline end-to-end (accetta file audio o cartella lezione)")
    p_run.add_argument("input", nargs="+", help="File audio (.m4a, .wav...) o cartella lezione esistente")
    p_run.add_argument("-d", "--date", help="Data della lezione (se input è audio)")
    p_run.add_argument("-m", "--materia", help="Nome della materia (se input è audio)")
    p_run.add_argument("-a", "--argomenti", help="Argomenti trattati (se input è audio)")
    p_run.add_argument("-o", "--dest-dir", help="Directory base di destinazione per nuova lezione")
    p_run.add_argument("--model", default=DEFAULT_MODEL, help=f"Modello MacWhisper per trascrizione (default: {DEFAULT_MODEL})")
    p_run.add_argument("--skip-transcribe", action="store_true", help="Salta trascrizione e crea segnaposto METADATA_ONLY")
    p_run.add_argument("--force", action="store_true", help="Forza l'intera pipeline ignorando i risultati precedenti")
    p_run.add_argument("--mock", action="store_true", help="Usa mock deterministico per ASR e LLM")
    p_run.add_argument("--with-review", action="store_true", dest="with_review",
                        help="Include anche generazione issue ASR/scientifiche e revisione umana nella run (comportamento monolitico precedente). Di default sono passi separati (rt review-asr / rt review-science / rt review).")
    p_run.add_argument("--auto-accept", action="store_true", help="Auto-accetta revisioni senza blocchi interattivi")
    p_run.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_run.add_argument("--channel", choices=["terminal", "telegram"], default=None,
                        help="Canale di conferma outline per questa sessione: terminale o Telegram (default: da config, altrimenti terminale)")
    p_run.set_defaults(func=cmd_run)


    # telegram-daemon
    p_tgd = subparsers.add_parser("telegram-daemon", help="Avvia il daemon Telegram persistente per bottoni/feedback")
    p_tgd.add_argument("--state-dir", default=None, help="Override della cartella di stato Telegram (default: da config)")
    p_tgd.set_defaults(func=cmd_telegram_daemon)

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

