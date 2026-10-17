"""
rt.cli
CLI unificata per il workflow accademico RT.
Le decisioni (scaletta, issue, recall) e la configurazione si fanno nella web ('rt web').
Comandi disponibili:
  rt run                <cartella> [--mock]
  rt setup              --audio <file> --date <YYYY-MM-DD> --materia <nome>
  rt prepare            <cartella>
  rt outline            <cartella> [--mock]
  rt rewrite            <cartella> [--unit <id>] [--mock]
  rt review             <cartella> [--unit <id>]... [--mock]
  rt recall             <cartella> [--pool | --reset | --delete | --units]
  rt build              <cartella> [--no-rename] (rinomina la cartella col titolo finale, attivo di default)
  rt status             <cartella>
  rt import             <archivio.zip>... (export completi fatti con 'rt export --all --zip')
  rt delete             <cartella> [--yes]
  rt relevance          <cartella> [--all] [--mock] (etichette JEV delle unità)

Comandi diagnostici (uso avanzato):
  rt validate-outline   <cartella>
  rt validate-draft     <cartella>
  rt validate-phase     <cartella> <fase> (segna la fase valida senza rieseguirla)
"""

import sys
import os
import argparse
import json
from typing import Dict, Any, List, Optional, Tuple

from rt.core.config import load_env_file, _default_project_root
from rt.cli_secrets import configure_secrets_parser, cmd_secrets
from rt.cli_jobs import cmd_jobs, cmd_worker, configure_jobs_parser, configure_worker_parser
from rt import cli_system
from rt.core.state import read_info_yaml

from rt.core.manifest import load_manifest
from rt.core.lesson_paths import lesson_path
from rt.core.segments import load_segments_json
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline, load_outline
from rt.pipeline.validator import validate_outline, validate_draft
from rt.pipeline.rewrite import run_rewrite, load_draft
from rt.pipeline.review import run_review, load_science_issues
from rt.pipeline.ledger import load_ledger
from rt.pipeline.build import run_build
from rt.storage import fs



def _has_real_config_source() -> bool:
    """Vero se esiste una sorgente di configurazione reale (cartella config/) nella
    working directory corrente o nella project root reale. Usata dai comandi CLI che
    eseguono lavoro LLM reale per evitare di procedere silenziosamente con i default hardcoded."""
    from rt.core.paths import config_dir
    return fs.isdir(config_dir())


def _job_has_configured_route(job_cfg) -> bool:
    """Vero se il job ha almeno una route primaria con provider/model impostati."""
    return bool(job_cfg and job_cfg.primary and job_cfg.primary.is_configured)


def _job_config_hint(job_name: str) -> str:
    """Messaggio di errore per un job non configurato: la sottocartella di config/ in cui
    si trova il suo file .yaml è a scelta libera (vedi rt.core.config.find_job_yaml_paths),
    quindi punta al percorso reale se il file esiste già, altrimenti a config/ in generale."""
    from rt.core.config import find_job_yaml_paths
    from rt.core.paths import config_dir
    paths = find_job_yaml_paths(config_dir())
    existing = paths.get(job_name)
    where = os.path.relpath(existing, os.getcwd()) if existing else f"config/{job_name}.yaml (in qualunque sottocartella di config/)"
    return (
        f"❌ Il job '{job_name}' non ha alcun provider configurato in {where}.\n"
        f"   Configuralo nella web: 'rt web', poi Impostazioni › Modelli.\n"
        f"   In alternativa, per una modifica manuale: apri config/general.yaml, dichiara una\n"
        f"   credenziale sotto 'credentials:' (nome, provider, env_var), imposta la variabile\n"
        f"   d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:' in {where}.\n"
        f"   Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa."
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
                "   Configurali nella web: 'rt web', poi Impostazioni › Modelli.\n"
                "   In alternativa, per una modifica manuale: apri config/general.yaml, dichiara una\n"
                "   credenziale sotto 'credentials:' (nome, provider, env_var), imposta la variabile\n"
                "   d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:' nei\n"
                "   rispettivi file config/<job>.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
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
    from rt.cli_reporter import format_phase_action
    print(format_phase_action(phase_name, res, step=step, total_steps=total_steps, description=description, details=details))


WEB_DECISIONS = {
    "outline_approval": "⏸ La scaletta aspetta la tua approvazione: approvala nella web ('rt web').",
    "science_issue": "⏸ Ci sono issue da decidere: decidile nella web ('rt web').",
}


def _print_pending_issues(lesson_dir: str, auto_accept: Optional[str]) -> None:
    """Dopo la review: applica l'eventuale --auto-accept e indica la web per le issue rimaste."""
    from rt.services.review_service import auto_accept_pending
    from rt.pipeline.ledger import get_pending_issues
    if auto_accept:
        accepted, remaining = auto_accept_pending(lesson_dir, auto_accept, channel="cli")
        if accepted:
            print(f"✔ Issue accettate in automatico: {len(accepted)}.")
    else:
        _, remaining = get_pending_issues(lesson_dir)
    if remaining:
        print(f"{WEB_DECISIONS['science_issue']} Da decidere: {len(remaining)}.")


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
    from rt.pipeline.outline_review import outline_needs_approval
    from rt.services.outline_service import is_outline_approved
    if outline_needs_approval(args.lesson_dir, force) and not is_outline_approved(args.lesson_dir):
        print(WEB_DECISIONS["outline_approval"])


def cmd_validate_outline(args):
    outline = load_outline(args.lesson_dir)
    seg_data = load_segments_json(lesson_path(args.lesson_dir, "segments.json"))
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
    seg_data = load_segments_json(lesson_path(args.lesson_dir, "segments.json"))
    res = validate_draft(draft, outline, seg_data)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def _get_lesson_title_for_notify(lesson_dir: str) -> str:
    try:
        from rt.pipeline.outline import load_outline
        return load_outline(lesson_dir).lesson_title
    except Exception:
        return os.path.basename(os.path.abspath(lesson_dir))


def cmd_review(args):
    if isinstance(getattr(args, "unit", None), list) and args.unit:
        _review_units(args)
        return

    from rt.core.idempotency import check_phase_status, PhaseStatus
    try:
        phase_status, _reason = check_phase_status(args.lesson_dir, "review")
    except OSError:
        # lesson_dir non scrivibile/inesistente (es. invocazione di test con un percorso
        # fittizio): non c'è nulla di reale da proteggere, procedi come se non fosse STALE.
        phase_status, _reason = PhaseStatus.MISSING, ""
    if phase_status in (PhaseStatus.STALE, PhaseStatus.INVALID):
        existing_issues = load_science_issues(args.lesson_dir)
        if existing_issues and not getattr(args, "yes", False):
            print(
                f"⚠️  La fase 'review' è {phase_status.value.upper()} e contiene {len(existing_issues)} issue già esistenti:\n"
                f"   una nuova revisione le sostituisce tutte. Rilancia con --yes per confermare.",
                file=sys.stderr)
            sys.exit(1)

    if not getattr(args, "mock", False):
        _ensure_config_ready(["review"])
    if getattr(args, "reset", False):
        from rt.pipeline.ledger import purge_decisions_by_prefix
        removed = purge_decisions_by_prefix(args.lesson_dir, prefix="sci_")
        print(f"🔄 Reset: rimosse {removed} decisioni scientifiche precedenti (le issue esistenti restano invariate).")

    force = getattr(args, "force", False)
    asr_llm = getattr(args, "asr_llm", False)
    shadow_jev = getattr(args, "shadow_jev", False)
    res = run_review(args.lesson_dir, force=force, force_mock=args.mock, asr_llm=asr_llm, shadow_jev=shadow_jev)
    _print_phase_action("review", res)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))
    _print_pending_issues(args.lesson_dir, getattr(args, "auto_accept", None))



def _review_units(args) -> None:
    """'rt review --unit': rivede solo le unità indicate (come il job review_unit della web);
    le issue delle altre unità restano con i loro id e le loro decisioni."""
    from rt.pipeline.review import run_review_unit
    if not getattr(args, "mock", False):
        _ensure_config_ready(["review"])
    present = {unit.unit_id for unit in load_draft(args.lesson_dir).units}
    results = []
    for unit in dict.fromkeys(args.unit):
        if unit not in present:
            results.append({"unit": unit, "status": "skipped", "reason": "Unità non presente nella bozza"})
            print(f"⚠️  Unità {unit} non presente nella bozza: saltata.")
            continue
        res = run_review_unit(args.lesson_dir, unit, force_mock=args.mock, force=args.force)
        results.append(res)
        if res.get("status") == "skipped":
            print(f"⚠️  Unità {unit} saltata: {res.get('reason')}.")
        else:
            print(f"✅ Revisione dell'unità {unit} completata.")
            if res.get("orphaned_decisions"):
                print(f"⚠️  {len(res['orphaned_decisions'])} decisioni riguardavano issue che la nuova revisione "
                      f"non ha ritrovato: {', '.join(res['orphaned_decisions'])}.")
    if getattr(args, "json", False):
        print(json.dumps({"phase": "review", "units": results}, ensure_ascii=False, indent=2))
    _print_pending_issues(args.lesson_dir, getattr(args, "auto_accept", None))


def cmd_recall(args):
    """Gestione del pool di domande; la sessione di recall si fa nella web."""
    reset_val = getattr(args, "reset", None)
    if isinstance(reset_val, str) and reset_val in ("all", "quiz", "mirata", "vasta"):
        from rt.pipeline.recall import purge_recall_by_type
        from rt.core.models import RecallQuestionType
        qtype = None if reset_val == "all" else RecallQuestionType(reset_val)
        count = purge_recall_by_type(args.lesson_dir, qtype)
        type_str = reset_val if reset_val != "all" else "tutti i tipi"
        print(f"🗑 Rimossi {count} elementi di recall per {type_str} da '{args.lesson_dir}'.")
        return

    delete_arg = getattr(args, "delete", None)
    if isinstance(delete_arg, str):
        from rt.services.recall_service import delete_questions
        ids = [q.strip() for q in delete_arg.split(",") if q.strip()]
        print(f"🗑 Domande eliminate: {delete_questions(args.lesson_dir, ids)} di {len(ids)} richieste.")
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

    force_mock = getattr(args, "mock", False)

    units_arg = getattr(args, "units", None)
    if isinstance(units_arg, str):
        from rt.services.recall_units import set_selection
        wanted = None if units_arg.strip().lower() == "rilevanti" else [u.strip() for u in units_arg.split(",") if u.strip()]
        rows = set_selection(args.lesson_dir, wanted)
        picked = [r["unit_id"] for r in rows if r["selected"]]
        print(f"🎯 Unità per il recaller: {len(picked)} di {len(rows)} ({', '.join(picked) or 'nessuna'}).")
    if not getattr(args, "pool", False):
        if not isinstance(units_arg, str):
            print("ℹ️  La sessione di recall si fa nella web ('rt web'): da qui si gestisce il pool "
                  "(--pool, --units, --delete, --reset).")
        return

    if not force_mock:
        _ensure_config_ready(["recall"])

    from rt.services.recall_service import generate_pool
    generated = generate_pool(args.lesson_dir, force_mock=force_mock)
    print("🧠 Pool rigenerato, domande nuove: " + ", ".join(f"{n} {t}" for t, n in generated.items()) + ".")


def cmd_add_images(args):
    if not getattr(args, "input", None) and not getattr(args, "web_search", None):
        print("❌ Nessuna sorgente di immagini indicata. Usa -i <pdf_o_cartella> e/o --web-search N.", file=sys.stderr)
        sys.exit(1)
    if not getattr(args, "mock", False):
        _ensure_config_ready(["image_description"])
    from rt.pipeline.add_images import run_add_images
    try:
        res = run_add_images(
            args.lesson_dir,
            input_path=args.input,
            web_search_count=args.web_search,
            unit_ids=[u.strip() for u in args.units.split(",") if u.strip()] if args.units else None,
            force_mock=args.mock,
        )
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ {res['images_added']} immagini posizionate, {len(res['macros_with_images'])} sezioni coinvolte.")
    if res.get("build_stale"):
        print("  Il documento finale non è più aggiornato: 'rt build' lo ricrea con le immagini.")
    else:
        print("  Le immagini sono nell'anteprima ('rt export'); 'rt build' le include nel documento finale.")


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




def cmd_setup(args):
    """Setup nativo per l'ingest di file audio, trascrizione macparakeet-cli e metadati."""
    from rt.pipeline.setup import run_setup, SetupError, SetupCancelled, DEFAULT_MODEL
    try:
        res = run_setup(
            audio=args.audio,
            date=args.date,
            materia=args.materia,
            argomenti=args.argomenti,
            docente=getattr(args, "docente", None),
            dest_dir=args.dest_dir,
            model=getattr(args, "model", None) or DEFAULT_MODEL,
            skip_transcribe=args.skip_transcribe,
            force=args.force,
            mock_asr=args.mock,
            interactive=False,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
    except SetupCancelled:
        sys.exit(0)
    except SetupError as e:
        print(f"❌ Errore Setup: {e.cli_message()}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    from rt.core.idempotency import check_phase_status
    from rt.core.state import compute_effective_workflow_state
    from rt.core.models import ScienceType
    lesson_dir = args.lesson_dir
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path) if fs.isfile(yaml_path) else {}
    manifest = load_manifest(lesson_dir)
    
    ledger = load_ledger(lesson_dir)
    sci_issues = load_science_issues(lesson_dir)
    decisions = ledger.decisions
    decided_ids = {d.issue_id for d in decisions}

    sci_concettuale = sum(1 for x in sci_issues if x.type == ScienceType.ERR_CONCETTUALE)

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
    from rt.services.review_service import build_warnings
    try:
        warnings = build_warnings(lesson_dir)
    except Exception as exc:
        warnings = [{"message": f"Controlli della revisione non riusciti: {exc}."}]
    if warnings:
        # stessa regola della web: la review non blocca il build, i suoi problemi sono avvisi
        print("Avvisi per il documento finale (non bloccano 'rt build'):")
        for w in warnings:
            print(f"  ⚠️  {w['message']}")
        print()

    if getattr(args, "issues", False):
        print("=" * 60)
        print("🔍 REPORT DIAGNOSTICO DETTAGLIATO ISSUE & DECISION LEDGER")
        print("=" * 60)
        print(f"Science Issues ({len(sci_issues)} totali):")
        print(f"  ERR_CONCETTUALE:            {sci_concettuale}")
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
        "phase_statuses": phase_statuses,
        "build_warnings": warnings,
    }
    if getattr(args, "issues", False):
        res["issues_breakdown"] = {
            "science": {"err_concettuale": sci_concettuale},
            "decisions": {"total": len(decisions), "accepted": dec_accepted, "rejected": dec_rejected, "edited": dec_edited, "auto_applied": dec_auto, "user": dec_user},
            "pending": {"total": total_pending, "science": len(pending_sci)}
        }
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_cost(args: argparse.Namespace) -> None:
    from rt.pipeline.cost import compute_lesson_cost, render_cost_report
    cost_data = compute_lesson_cost(args.lesson_dir)
    split = getattr(args, "split", False)
    if getattr(args, "json", False):
        print(json.dumps(cost_data, ensure_ascii=False, indent=2))
    else:
        print(render_cost_report(cost_data, split=split))


def _resolve_lesson_arg(value: str) -> str:
    """Lezione indicata come percorso, id del database o nome della lezione."""
    if value.isdigit() and not fs.exists(value):
        from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
        try:
            return resolve_lesson_dir(int(value))
        except (LessonNotFound, RuntimeError):
            pass
    path = os.path.abspath(os.path.expanduser(value))
    if fs.isdir(path):
        return path
    from rt.services.lesson_service import lessons_root
    candidate = os.path.join(lessons_root(), value)
    if fs.isdir(candidate):
        return candidate
    return path


def cmd_export(args: argparse.Namespace) -> None:
    """Esporta il Markdown finale (con immagini) o tutti i dati della lezione."""
    from rt.storage.export import ExportError, export_to_dir, export_zip, is_preview, zip_name
    lesson_dir = _resolve_lesson_arg(args.lesson)
    if not fs.isdir(lesson_dir):
        print(f"❌ Lezione non trovata: {args.lesson}", file=sys.stderr)
        sys.exit(1)
    scope = "all" if args.all else "final"
    out_dir = os.path.abspath(os.path.expanduser(args.output or os.getcwd()))
    try:
        if args.zip:
            os.makedirs(out_dir, exist_ok=True)
            target = os.path.join(out_dir, zip_name(lesson_dir))
            with open(target, "wb") as f:
                f.write(export_zip(lesson_dir, scope))
            written = [target]
        else:
            written = export_to_dir(lesson_dir, out_dir, scope)
    except ExportError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Esportati {len(written)} file:")
    for path in written:
        print(f"  - {path}")
    if is_preview(lesson_dir):
        print("ℹ️  Anteprima dalla bozza: il documento finale non c'è o non è aggiornato ('rt build' lo crea).")


def _service_error(exc: Exception) -> Optional[str]:
    """Messaggio per l'utente di un errore previsto dei servizi; None per un'eccezione
    inattesa, che va lasciata salire."""
    from rt.services.errors import ServiceError
    return exc.message if isinstance(exc, ServiceError) else None


def cmd_delete(args: argparse.Namespace) -> None:
    """Elimina una lezione e i suoi media (come DELETE /lessons/{id} della web)."""
    from rt.services.lesson_delete_service import delete_lesson
    from rt.services.lesson_service import LessonNotFound, lesson_id_for_dir, resolve_lesson_dir
    lesson_id = lesson_id_for_dir(_resolve_lesson_arg(args.lesson))
    try:
        lesson_dir = resolve_lesson_dir(lesson_id) if lesson_id is not None else None
    except LessonNotFound:
        lesson_dir = None
    if lesson_dir is None:
        print(f"❌ Lezione non trovata: {args.lesson}", file=sys.stderr)
        sys.exit(1)
    if not args.yes:
        try:
            answer = input(f"Eliminare definitivamente la lezione '{os.path.basename(lesson_dir)}' "
                           "con testi, audio e immagini? [s/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("s", "si", "sì", "y", "yes"):
            print("Operazione annullata.")
            return
    try:
        delete_lesson(lesson_id, lesson_dir)
    except Exception as exc:
        message = _service_error(exc)
        if message is None:
            raise
        print(f"❌ {message}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Lezione eliminata: {os.path.basename(lesson_dir)}")


def cmd_validate_phase(args: argparse.Namespace) -> None:
    """Valida a mano una fase senza rieseguirla (come POST /lessons/{id}/phases/{fase}/validate)."""
    from rt.services.phase_validation_service import validate_phase
    lesson_dir = _resolve_lesson_arg(args.lesson)
    if not fs.isdir(lesson_dir):
        print(f"❌ Lezione non trovata: {args.lesson}", file=sys.stderr)
        sys.exit(1)
    lesson_id = None
    try:
        from rt.services.lesson_service import lesson_id_for_dir
        lesson_id = lesson_id_for_dir(lesson_dir)
    except RuntimeError:
        pass  # senza database: nessun lease da controllare
    try:
        result = validate_phase(lesson_dir, args.phase, lesson_id=lesson_id, actor="cli", channel="cli")
    except Exception as exc:
        message = _service_error(exc)
        if message is None:
            raise
        print(f"❌ {message}", file=sys.stderr)
        sys.exit(1)
    if not result["changed"]:
        print(f"ℹ️  La fase {args.phase} è già valida: {result['reason']}")
        return
    print(f"✅ Fase {args.phase} validata manualmente (era {result['previous_status']}: {result['previous_reason']}).")
    print("   Le fasi a valle costruite su input diversi restano da rifare ('rt status' le mostra).")


def cmd_relevance(args: argparse.Namespace) -> None:
    """Etichette JEV per le unità nuove o cambiate, --all per tutte (come POST /lessons/{id}/relevance/run)."""
    from rt.services.unit_relevance import ensure_can_run, list_units, refresh
    lesson_dir = _resolve_lesson_arg(args.lesson)
    if not fs.isdir(lesson_dir):
        print(f"❌ Lezione non trovata: {args.lesson}", file=sys.stderr)
        sys.exit(1)
    try:
        ensure_can_run()
    except Exception as exc:
        message = _service_error(exc)
        if message is None:
            raise
        print(f"❌ {message}", file=sys.stderr)
        sys.exit(1)
    refresh(lesson_dir, force_mock=args.mock, force=args.all)
    overview = list_units(lesson_dir)
    for unit in overview["units"]:
        label = unit.get("label") or unit.get("prediction") or "nessuna etichetta"
        print(f"{unit['unit_id']}  {label}  → {unit['effective']}" + (f"  ⚠️ {unit['error']}" if unit.get("error") else ""))
    excluded = sum(1 for unit in overview["units"] if unit["effective"] != "didactic")
    print(f"✅ {len(overview['units'])} unità ({overview['mode']}), {excluded} non didattiche.")


def cmd_import(args: argparse.Namespace) -> None:
    """Importa archivi .zip completi di RT come nuove lezioni (come POST /lessons/import-zip)."""
    import zipfile
    from rt.services.lesson_import_service import import_archive
    from rt.services.lesson_service import resolve_lesson_dir
    rejected = 0
    for archive in args.archives:
        name = os.path.basename(archive)
        path = os.path.abspath(os.path.expanduser(archive))
        if not name.lower().endswith(".zip"):
            reason = "Serve un archivio ZIP."
        elif not os.path.isfile(path):
            reason = "File non trovato."
        else:
            try:
                lesson_id = import_archive(path)
                print(f"✅ {name}: importata come {os.path.basename(resolve_lesson_dir(lesson_id))} (id {lesson_id})")
                continue
            except (zipfile.BadZipFile, ValueError):
                reason = "Archivio ZIP non valido."
            except Exception as exc:
                reason = _service_error(exc)
                if reason is None:
                    raise
        rejected += 1
        print(f"❌ {name}: {reason}", file=sys.stderr)
    if rejected:
        sys.exit(1)


def cmd_run(args):
    """Pipeline end-to-end completa con idempotenza, cost protection e supporto audio/cartella."""
    from rt.pipeline.setup import SetupError, SetupCancelled, DEFAULT_MODEL
    from rt.cli_reporter import CliReporter, run_steps, format_cost_summary
    from rt.llm.telemetry import GLOBAL_TELEMETRY
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, PipelineStatus, is_audio_input, run_pipeline
    from rt.telegram.notify import TelegramBuildNotifier

    raw_inputs = args.input if isinstance(args.input, list) else [args.input]
    first_input = raw_inputs[0] if raw_inputs else ""
    mock_mode = getattr(args, "mock", False)
    with_review = bool(getattr(args, "with_review", True))

    if not mock_mode:
        required = ["outline", "rewrite"]
        if with_review:
            required.append("review")
        _ensure_config_ready(required)

    is_audio = is_audio_input(raw_inputs)
    steps, total_steps = run_steps(is_audio, with_review)

    print("\n" + "=" * 60)
    if is_audio:
        print("🎙️  RT 2.0 — PIPELINE END-TO-END DA SORGENTE AUDIO")
        print("=" * 60)
        print(f"File audio in ingresso: {', '.join(os.path.basename(x) for x in raw_inputs)}")
    else:
        print(f"🚀 RT 2.0 — PIPELINE END-TO-END PER: {first_input}")
        print("=" * 60)

    options = PipelineOptions(
        date=getattr(args, "date", None),
        materia=getattr(args, "materia", None),
        argomenti=getattr(args, "argomenti", None),
        docente=getattr(args, "docente", None),
        dest_dir=getattr(args, "dest_dir", None),
        model=getattr(args, "model", None) or DEFAULT_MODEL,
        skip_transcribe=getattr(args, "skip_transcribe", False),
        force=getattr(args, "force", False),
        mock=mock_mode,
        with_review=with_review,
        with_enrichment=getattr(args, "with_enrichment", None),
        auto_accept=bool(getattr(args, "auto_accept", False)),
        rename=getattr(args, "rename", True),
        source="cli",
    )
    if getattr(args, "queue", False):
        from rt.cli_jobs import run_queued
        run_queued(raw_inputs, options)
        return
    # La CLI usa la telemetria di processo: il riepilogo costi e i test la leggono da lì.
    ctx = RunContext(reporter=CliReporter(steps=steps, total_steps=total_steps), telemetry=GLOBAL_TELEMETRY)
    from contextlib import nullcontext
    from rt.core.process_lock import LessonBusy, lesson_work_lock
    # Stesso lock per lezione del worker: 'rt run' e un job in coda non lavorano insieme
    # sulla stessa cartella (per l'audio la cartella nasce durante il setup).
    lock = lesson_work_lock(first_input) if not is_audio and fs.isdir(first_input) else nullcontext()
    try:
        with lock:
            result = run_pipeline(raw_inputs, options, ctx, notifiers=[TelegramBuildNotifier()])
    except LessonBusy as exc:
        print(f"❌ {exc}: un job della coda la sta elaborando ('rt jobs' per vederlo).", file=sys.stderr)
        sys.exit(1)

    if result.status == PipelineStatus.FAILED:
        if isinstance(result.error, SetupCancelled):
            sys.exit(0)
        if isinstance(result.error, SetupError):
            print(f"❌ Errore durante l'ingest audio: {result.error.cli_message()}", file=sys.stderr)
            sys.exit(1)
        raise result.error
    if result.status == PipelineStatus.WAITING_FOR_DECISION:
        kind = result.decision.kind if result.decision else ""
        if kind == "setup_metadata":
            missing = ", ".join((result.decision.payload or {}).get("missing") or [])
            print(f"⏸ Mancano i metadati della lezione ({missing}): rilancia con -d/-m/-a.", file=sys.stderr)
        else:
            print(f"{WEB_DECISIONS.get(kind, '⏸ La lezione aspetta una decisione nella web (rt web).')}\n"
                  f"   Poi rilancia 'rt run \"{result.lesson_dir}\"' per completarla.")
        return
    if result.status != PipelineStatus.COMPLETED:
        return

    summary_text = format_cost_summary(GLOBAL_TELEMETRY.get_summary())
    if summary_text:
        print(summary_text)


class RTHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def _format_usage(self, usage, actions, groups, prefix):
        if usage is None and any(isinstance(a, argparse._SubParsersAction) for a in actions):
            prefix = prefix if prefix is not None else "usage: "
            return f"{prefix}rt <comando> [opzioni]\n\n"
        return super()._format_usage(usage, actions, groups, prefix)

    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            parts = []
            for subaction in self._iter_indented_subactions(action):
                if subaction.help != argparse.SUPPRESS:
                    parts.append(self._format_action(subaction))
            return self._join_parts(parts)
        return super()._format_action(action)


def cmd_db(args: argparse.Namespace) -> None:
    """Gestione del database (migrazioni)."""
    from rt.db.engine import current_revision, get_database, head_revision, resolve_database_url, sqlite_file

    url = resolve_database_url()
    if not url:
        print("Database disattivato (RT_DATABASE_URL=off o database_url: off).")
        sys.exit(1)
    shown = sqlite_file(url) or url.split("@")[-1]
    if args.db_command == "migrate-storage":
        _cmd_db_migrate_storage(args)
        return
    if args.db_command == "check":
        _cmd_db_check(args, url, shown)
        return
    if args.db_command == "upgrade":
        db = get_database(create=True, url=url)
        if db is None:
            print(f"❌ Impossibile creare o aggiornare il database: {shown}", file=sys.stderr)
            sys.exit(1)
        print(f"✅ Database aggiornato ({current_revision(db.engine)}): {shown}")
    else:
        db = get_database(url=url)
        if db is None:
            print(f"Database non ancora creato: {shown}\nEsegui 'rt db upgrade' per crearlo.")
            return
        print(f"Database: {shown}\nRevisione: {current_revision(db.engine)} (ultima: {head_revision()})")


def _cmd_db_migrate_storage(args: argparse.Namespace) -> None:
    """Sposta le lezioni in cartella nel database (testi) e in media/ (audio e immagini)."""
    from rt.core.config import load_config
    from rt.storage.migrate import migrate_storage

    root = getattr(args, "lessons_root", None) or load_config().telegram.lessons_root
    report = migrate_storage(root, dry_run=args.dry_run, on_progress=print)
    if not report.plans:
        print("✅ Nessuna lezione in cartella da migrare: sono già tutte nel database.")
        return

    def _mb(n: int) -> str:
        return f"{n / 1_000_000:.1f} MB"

    if args.dry_run:
        print(f"Lezioni da migrare: {len(report.plans)} (nessuna modifica eseguita, --dry-run)")
        for plan in report.plans:
            print(f"  - {os.path.basename(plan.lesson_dir)}: {len(plan.files)} file, "
                  f"testi {_mb(plan.text_bytes)} nel database, media {_mb(plan.media_bytes)} in media/")
            for skipped in plan.skipped:
                print(f"      ignorato: {skipped}")
        text = sum(p.text_bytes for p in report.plans)
        media = sum(p.media_bytes for p in report.plans)
        print(f"Totale: testi {_mb(text)}, media {_mb(media)}. Rilancia senza --dry-run per migrare.")
        return
    print(f"✅ Lezioni migrate nel database: {len(report.migrated)} di {len(report.plans)}")
    if report.database_backup:
        print(f"  Backup del database: {report.database_backup}")
    print(f"  Cartelle originali spostate (non cancellate) in: {os.path.join(report.backup_dir, 'lezioni')}")
    for err in report.errors:
        print(f"  ⚠️  {err}", file=sys.stderr)
    if report.errors:
        sys.exit(1)


def _cmd_db_check(args: argparse.Namespace, url: str, shown: str) -> None:
    from rt.db.engine import get_database
    db = get_database(url=url)
    if db is None:
        print(f"❌ Database non disponibile: {shown}\nEsegui 'rt db upgrade' per crearlo.", file=sys.stderr)
        sys.exit(1)
    from rt.core.config import load_config
    from rt.db.health import check_database
    issues = check_database(db, quick=getattr(args, "quick", False),
                            lessons_root=load_config().telegram.lessons_root)
    if not issues:
        print(f"✅ Integrità database e media verificata ({shown}).")
        return
    print(f"⚠️  {len(issues)} problemi nel database o nei media:")
    for d in issues:
        print(f"  - {d}")
    sys.exit(1)


# Comandi che non passano da ensure_database(): 'db' è la diagnosi del database stesso
# (deve funzionare anche con un DB rotto), 'config' e 'secrets' non toccano le lezioni e
# possono cambiare lessons_root (quindi il percorso del DB).
_COMMANDS_WITHOUT_DATABASE = {"db", "config", "secrets",
                              # fase G: la cartella dati va migrata prima di aprire il DB, e diagnosi,
                              # servizi, ripristino e disinstallazione devono funzionare con un DB rotto
                              "data", "app", "service", "doctor", "restore", "uninstall",
                              # l'app prepara da sé cartella dati e database (rt.desktop)
                              "desktop"}


def _ensure_database_or_exit(command: Optional[str]) -> None:
    """Crea/migra il DB senza scandire le cartelle; se il DB è illeggibile il
    comando si ferma con le istruzioni per ripristinarlo."""
    if command in _COMMANDS_WITHOUT_DATABASE:
        return
    from rt.db.bootstrap import ensure_database
    from rt.db.engine import DatabaseUnavailable
    try:
        ensure_database()
    except DatabaseUnavailable as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_web(args: argparse.Namespace) -> None:
    """Avvia la web app: API + worker + SPA (RT4-F8)."""
    from rt.api.launcher import run_spa
    from rt.services.service_manager import api_port
    kwargs = {"verbose": True} if getattr(args, "verbose", False) else {}
    code = run_spa(port=args.port or api_port(), open_browser=not args.no_browser, **kwargs)
    if code:
        sys.exit(code)


def cmd_logs(args: argparse.Namespace) -> None:
    """Mostra le ultime righe dei log dei servizi."""
    from rt.services.logs_service import show_logs
    show_logs(args.service, lines=args.lines, follow=args.follow)


def cmd_api(args: argparse.Namespace) -> None:
    """Avvia l'API REST (FastAPI) su loopback."""
    from rt.api.server import run
    code = run(host=args.host, port=args.port, reset_token=args.reset_token,
               no_auth=args.no_auth, dev_cors=args.dev_cors, service=getattr(args, "service", False))
    if code:
        sys.exit(code)


def build_parser() -> Tuple[argparse.ArgumentParser, Dict[str, argparse.ArgumentParser]]:
    from rt.pipeline.setup import DEFAULT_MODEL, configure_setup_parser

    epilog_text = (
        "Fasi della pipeline:\n"
        "  setup               Esegue l'ingest di file audio, trascrizione macparakeet-cli e metadati\n"
        "  prepare             Valida cartella ed estrae segmenti temporali\n"
        "  outline             Genera outline strutturata con LLM\n"
        "  rewrite             Rielabora le unità didattiche a finestre con provenance\n"
        "  build               Finalizzazione deterministica dei Markdown\n"
        "  add-images          Integra slide/foto o immagini web nel documento finale\n\n"
        "Comandi diagnostici:\n"
        "  cost                Mostra il costo stimato cumulativo di una lezione\n"
        "  export              Esporta il Markdown finale o tutti i dati di una lezione\n"
        "  import              Importa archivi .zip completi di RT come nuove lezioni\n"
        "  delete              Elimina una lezione (chiede conferma, --yes per saltarla)\n"
        "  relevance           Assegna le etichette del classificatore alle unità (--all per rifarle tutte)\n"
        "  db                  Crea, aggiorna e sincronizza il database (rt db --help)\n"
        "  validate-outline    Valida deterministicamente l'outline\n"
        "  validate-draft      Valida il draft rielaborato\n"
        "  validate-phase      Segna una fase come valida senza rieseguirla\n\n"
        "Installazione e manutenzione:\n"
        "  doctor              Controlla l'installazione e dice cosa sistemare\n"
        "  backup / restore    Backup completo (database, media, configurazione) e ripristino\n"
        "  service             Servizi in background con launchd: API e worker\n"
        "  logs                Ultime righe dei log dei servizi (--follow per seguirli)\n"
        "  data                Cartella dati di RT (~/.rt o RT_DATA_DIR)\n"
        "  app                 Passa all'app per il Mac tenendo i dati\n"
        "  uninstall           Disinstalla RT lasciando i dati\n\n"
        "Opzioni generali:\n"
        "  -v, --version       Mostra la versione corrente e verifica aggiornamenti\n"
        "  -u, --update        Aggiorna RT all'ultima versione disponibile\n"
        "  -u --beta           Passa al canale beta: aggiorna anche alle versioni di prova\n"
        "  -u --stable         Torna al canale stabile (solo versioni stabili)\n\n"
        "Esempi:\n"
        "  rt web                          Avvia la web app e apre il browser (API + worker)\n"
        "  rt api                          Avvia l'API REST locale (http://127.0.0.1:8765/docs)\n"
        "  rt run lezione.m4a              Pipeline completa da un file audio\n"
        "  rt run <cartella_lezione>       Riprende una lezione già iniziata\n"
        "  rt review <cartella_lezione>    Critica scientifica indipendente"
    )
    parser = argparse.ArgumentParser(
        prog="rt",
        description="Workflow per Rielaborazione Trascritti e Active Recall",
        epilog=epilog_text,
        formatter_class=RTHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", required=False, title="Comandi principali")

    p_web = subparsers.add_parser(
        "web", help="Avvia la web app (API, worker e interfaccia) e apre il browser già autenticato")
    p_web.add_argument("--port", type=int, default=None, help="Porta locale (default: 8765)")
    p_web.add_argument("--no-browser", action="store_true", help="Non aprire automaticamente il browser")
    p_web.add_argument("--spa", action="store_true", help=argparse.SUPPRESS)  # compatibilità: ora è il default
    p_web.add_argument("--verbose", action="store_true", help="Segui i log dei servizi già attivi fino a Ctrl+C")
    p_web.set_defaults(func=cmd_web)
    from rt.desktop import cmd_desktop, configure_parser as configure_desktop_parser
    p_desk = subparsers.add_parser("desktop", help=argparse.SUPPRESS)  # doppio clic sull'app (RT.app, menu Start)
    configure_desktop_parser(p_desk)
    p_desk.set_defaults(func=cmd_desktop)

    p_logs = subparsers.add_parser("logs", help="Mostra i log di API e worker")
    p_logs.add_argument("service", nargs="?", choices=["api", "worker"], help="Servizio (default: tutti)")
    p_logs.add_argument("--lines", type=int, default=50, help="Righe recenti per servizio (default: 50)")
    p_logs.add_argument("--follow", "-f", action="store_true", help="Segui le nuove righe fino a Ctrl+C")
    p_logs.set_defaults(func=cmd_logs)

    p_api = subparsers.add_parser("api", help="Avvia l'API REST locale (FastAPI, documentazione su /docs)")
    p_api.add_argument("--host", default="127.0.0.1", help="Indirizzo di ascolto (default: 127.0.0.1, solo questo Mac)")
    p_api.add_argument("--port", type=int, default=8765, help="Porta (default: 8765)")
    p_api.add_argument("--reset-token", action="store_true", help="Genera e mostra un nuovo token API")
    p_api.add_argument("--no-auth", action="store_true", help="Disattiva l'autenticazione (solo su 127.0.0.1)")
    p_api.add_argument("--dev-cors", action="store_true", help="Consente le richieste dalla SPA in sviluppo (localhost:5173)")
    p_api.add_argument("--service", action="store_true", help=argparse.SUPPRESS)  # avvio da launchd (rt service)
    p_api.set_defaults(func=cmd_api)

    # 1-bis. secrets
    p_sec = subparsers.add_parser("secrets", help="Chiavi API e token cifrati: init, migrate, list, set, unset, rotate")
    configure_secrets_parser(p_sec)
    p_sec.set_defaults(func=cmd_secrets)

    # 2. run
    p_run = subparsers.add_parser("run", help="Esegue l'intera pipeline end-to-end (accetta file audio o cartella lezione)")
    p_run.add_argument("input", nargs="+", help="File audio (.m4a, .wav...) o cartella lezione esistente")
    p_run.add_argument("-d", "--date", help="Data della lezione (se input è audio)")
    p_run.add_argument("-m", "--materia", help="Nome della materia (se input è audio)")
    p_run.add_argument("-a", "--argomenti", help="Argomenti trattati (se input è audio)")
    p_run.add_argument("--docente", help="Nome del docente (se input è audio, facoltativo)")
    p_run.add_argument("-o", "--dest-dir", help="Directory base di destinazione per nuova lezione")
    p_run.add_argument("--model", default=DEFAULT_MODEL, help=f"Modello macparakeet-cli per trascrizione (default: {DEFAULT_MODEL})")
    p_run.add_argument("--skip-transcribe", action="store_true", help="Salta trascrizione e crea segnaposto METADATA_ONLY")
    p_run.add_argument("--force", action="store_true", help="Forza l'intera pipeline ignorando i risultati precedenti")
    p_run.add_argument("--mock", action="store_true", help="Usa mock deterministico per ASR e LLM")
    p_run.add_argument("--queue", action="store_true", help="Accoda la pipeline al worker ('rt worker') e ne segue il progresso")
    p_run.add_argument(
        "--with-review", nargs="?", const="all", choices=["all", "asr", "science"], default=None,
        dest="with_review",
        help="Include anche la review nella run."
    )
    p_run.add_argument("--with-enrichment", action="store_true", default=None,
                       help="Esegue l'arricchimento didattico alla fine della pipeline")
    p_run.add_argument("--auto-accept", action="store_true", help="Auto-accetta revisioni senza blocchi interattivi")
    p_run.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_run.set_defaults(func=cmd_run)

    # 3. review
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
    p_rsci.add_argument("-y", "--yes", action="store_true",
                        help="Conferma la nuova revisione anche se sostituisce issue già esistenti")
    p_rsci.add_argument(
        "--asr-llm",
        action="store_true",
        help="Affida all'LLM di critica scientifica la validazione dei candidati a rischio ASR invece del solo criterio statistico (meno falsi positivi, costa di più)"
    )
    p_rsci.add_argument(
        "--shadow-jev",
        action="store_true",
        dest="shadow_jev",
        help="Esegue il pre-filtro del classificatore e ne registra il verdetto in llm_debug.log per confronto, "
             "ma non salta né genera nulla: ogni unità passa comunque per l'intera critica LLM "
             "come oggi (richiede 'jev: {enabled: true}' in config/general.yaml — no-op altrimenti)"
    )
    p_rsci.add_argument("--unit", action="append", metavar="ID",
                        help="Rivede solo questa unità (ripetibile); le issue delle altre unità restano")
    p_rsci.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rsci.set_defaults(func=cmd_review)

    # 4. recall
    p_recall = subparsers.add_parser("recall", help="Pool di domande di recall di una lezione (la sessione si fa nella web)")
    p_recall.add_argument("lesson_dir", help="Directory della lezione")
    p_recall.add_argument(
        "--reset", nargs="?", const="all", choices=["all", "quiz", "mirata", "vasta"], default=None,
        help="Resetta le domande/risposte di recall già effettuate: senza valore o 'all' azzera "
             "tutto, 'quiz'/'mirata'/'vasta' azzera solo quel tipo."
    )
    p_recall.add_argument("--units", default=None, metavar="1.1,2.3|rilevanti",
                          help="Unità da cui il recaller genera le domande (resta salvata); 'rilevanti' torna alla "
                               "selezione predefinita, le unità rilevanti per il classificatore")
    p_recall.add_argument("--pool", action="store_true",
                          help="Rigenera il pool: tutte le unità selezionate passano al recaller, che aggiunge "
                               "domande nuove a quelle già generate (che restano)")
    p_recall.add_argument("--delete", default=None, metavar="recall_000012,...",
                          help="Elimina queste domande (e le loro risposte) dal pool della lezione")
    p_recall.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM reale)")
    p_recall.set_defaults(func=cmd_recall)

    # 5. status
    p_stat = subparsers.add_parser("status", help="Mostra lo stato della lezione")
    p_stat.add_argument("lesson_dir", help="Directory della lezione")
    p_stat.add_argument("--issues", action="store_true", help="Mostra report diagnostico dettagliato delle issue e del ledger")
    p_stat.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo dello stato")
    p_stat.set_defaults(func=cmd_status)

    # worker e coda dei job (fase D)
    p_wrk = subparsers.add_parser("worker", help="Esegue i job in coda (pipeline, trascrizioni, recall) in background")
    configure_worker_parser(p_wrk)
    p_wrk.set_defaults(func=cmd_worker)
    p_jobs = subparsers.add_parser("jobs", help="Elenca, mostra e annulla i job in coda")
    configure_jobs_parser(p_jobs)
    p_jobs.set_defaults(func=cmd_jobs)

    # Fasi della pipeline (help=argparse.SUPPRESS, documentati in epilog)
    # setup
    p_set = subparsers.add_parser("setup", help=argparse.SUPPRESS, description="Esegue l'ingest di file audio, trascrizione macparakeet-cli e metadati")
    configure_setup_parser(p_set)
    p_set.set_defaults(func=cmd_setup)

    # prepare
    p_prep = subparsers.add_parser("prepare", help=argparse.SUPPRESS, description="Valida cartella ed estrae segmenti temporali")
    p_prep.add_argument("lesson_dir", help="Directory della lezione")
    p_prep.add_argument("--force", action="store_true", help="Forza la ripreparazione ignorando gli artefatti esistenti")
    p_prep.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_prep.set_defaults(func=cmd_prepare)

    # outline
    p_out = subparsers.add_parser("outline", help=argparse.SUPPRESS, description="Genera outline strutturata con LLM")
    p_out.add_argument("lesson_dir", help="Directory della lezione")
    p_out.add_argument("--force", action="store_true", help="Forza la rigenerazione dell'outline")
    p_out.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_out.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_out.set_defaults(func=cmd_outline)

    # rewrite
    p_rew = subparsers.add_parser("rewrite", help=argparse.SUPPRESS, description="Rielabora le unità didattiche a finestre con provenance")
    p_rew.add_argument("lesson_dir", help="Directory della lezione")
    p_rew.add_argument("--unit", help="ID specifica unità da rielaborare")
    p_rew.add_argument("--force", action="store_true", help="Forza la rielaborazione (o la sola unità indicata)")
    p_rew.add_argument("--mock", action="store_true", help="Usa mock deterministico")
    p_rew.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_rew.set_defaults(func=cmd_rewrite)

    # build
    p_bld = subparsers.add_parser("build", help=argparse.SUPPRESS, description="Finalizzazione deterministica dei Markdown")
    p_bld.add_argument("lesson_dir", help="Directory della lezione")
    p_bld.add_argument("--force", action="store_true", help="Forza la rigenerazione di tutti i Markdown")
    p_bld.add_argument("--rename", action=argparse.BooleanOptionalAction, default=True,
                        help="Rinomina la cartella con il titolo formale (default: attivo, --no-rename per disattivare)")
    p_bld.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_bld.set_defaults(func=cmd_build)

    # add-images
    p_addimg = subparsers.add_parser("add-images", help=argparse.SUPPRESS, description="Integra slide/foto (o immagini trovate sul web) nel documento finale, per macro-sezione")
    p_addimg.add_argument("lesson_dir", help="Directory della lezione")
    p_addimg.add_argument("-i", "--input", default=None, help="Percorso a un file PDF di slide o una cartella di foto")
    p_addimg.add_argument(
        "--web-search", nargs="?", const=3, type=int, default=None,
        help="Cerca sul web via SearXNG N immagini per ogni unità, con una ricerca per unità "
             "(default 3 se il flag è usato senza valore). Combinabile con -i. Richiede l'URL di "
             "SearXNG (web: Impostazioni › Ricerca web; oppure searxng_base_url in config/general.yaml)."
    )
    p_addimg.add_argument("--units", default=None, metavar="ID,ID",
                          help="Con --web-search: cerca solo per queste unità (id separati da virgola, es. 1.1,2.3); default tutte")
    p_addimg.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM/vision reale)")
    p_addimg.set_defaults(func=cmd_add_images)

    # validate-outline
    p_vout = subparsers.add_parser("validate-outline", help=argparse.SUPPRESS, description="Valida deterministicamente l'outline")
    p_vout.add_argument("lesson_dir", help="Directory della lezione")
    p_vout.set_defaults(func=cmd_validate_outline)

    # validate-draft
    p_vdr = subparsers.add_parser("validate-draft", help=argparse.SUPPRESS, description="Valida il draft rielaborato")
    p_vdr.add_argument("lesson_dir", help="Directory della lezione")
    p_vdr.set_defaults(func=cmd_validate_draft)

    # cost
    p_cost = subparsers.add_parser("cost", help=argparse.SUPPRESS, description="Mostra il costo stimato cumulativo di una lezione")
    p_cost.add_argument("lesson_dir", help="Directory della lezione")
    p_cost.add_argument("--split", action="store_true", help="Mostra il dettaglio completo per fase, unità e singoli tentativi")
    p_cost.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo")
    p_cost.set_defaults(func=cmd_cost)

    # db (fuori dalla mappa restituita: la palette della TUI non gestisce sotto-comandi annidati)
    p_db = subparsers.add_parser("db", help=argparse.SUPPRESS, description="Gestione del database di RT (indice lezioni, decisioni, costi, stato Telegram)")
    db_sub = p_db.add_subparsers(dest="db_command", required=True, title="Comandi database")
    db_sub.add_parser("upgrade", help="Crea il database o applica le migrazioni mancanti")
    db_sub.add_parser("status", help="Mostra percorso e revisione del database")
    p_check = db_sub.add_parser("check", help="Controlla integrità del database e dei media senza modificare dati")
    p_check.add_argument("--quick", action="store_true",
                         help="Salta i checksum dei media (controlla solo esistenza e dimensioni)")
    p_mig = db_sub.add_parser("migrate-storage", help="Sposta le lezioni in cartella nel database (testi) e in media/ (audio e immagini), con backup")
    p_mig.add_argument("--lessons-root", help="Cartella delle lezioni (default: telegram.lessons_root)")
    p_mig.add_argument("--dry-run", action="store_true", help="Mostra cosa verrebbe migrato senza modificare nulla")
    p_db.set_defaults(func=cmd_db)

    # fase G: cartella dati, servizi, backup, diagnosi, disinstallazione
    p_doc = subparsers.add_parser("doctor", help=argparse.SUPPRESS, description="Controlla l'installazione e dice cosa sistemare")
    cli_system.configure_doctor_parser(p_doc)
    p_doc.set_defaults(func=cli_system.cmd_doctor)
    p_bak = subparsers.add_parser("backup", help=argparse.SUPPRESS, description="Backup di database, media, configurazione e segreti cifrati (incrementale per i media)")
    cli_system.configure_backup_parser(p_bak)
    p_bak.set_defaults(func=cli_system.cmd_backup)
    p_rst = subparsers.add_parser("restore", help=argparse.SUPPRESS, description="Ripristina un backup fatto con 'rt backup'")
    cli_system.configure_restore_parser(p_rst)
    p_rst.set_defaults(func=cli_system.cmd_restore)
    p_svc = subparsers.add_parser("service", help=argparse.SUPPRESS, description="Servizi in background (launchd): API e worker")
    cli_system.configure_service_parser(p_svc)
    p_svc.set_defaults(func=cli_system.cmd_service)
    p_data = subparsers.add_parser("data", help=argparse.SUPPRESS, description="Cartella dati di RT (RT_DATA_DIR o ~/.rt): stato, creazione, migrazione")
    cli_system.configure_data_parser(p_data)
    p_data.set_defaults(func=cli_system.cmd_data)
    p_app = subparsers.add_parser("app", help="Passa all'app per il Mac (RT.app) tenendo i dati",
                                  description="Dalla RT da terminale all'app per il Mac: dati e impostazioni restano")
    cli_system.configure_app_parser(p_app)
    p_app.set_defaults(func=cli_system.cmd_app)
    p_uni = subparsers.add_parser("uninstall", help=argparse.SUPPRESS, description="Disinstalla RT (servizi e ambiente Python; i dati restano)")
    cli_system.configure_uninstall_parser(p_uni)
    p_uni.set_defaults(func=cli_system.cmd_uninstall)

    p_exp = subparsers.add_parser("export", help="Esporta il Markdown finale (con immagini) o tutti i dati di una lezione")
    p_exp.add_argument("lesson", help="Lezione: percorso, id o nome della lezione")
    p_exp.add_argument("-o", "--output", help="Cartella di destinazione (default: cartella corrente)")
    p_exp.add_argument("--all", action="store_true", help="Esporta tutti i file della lezione (testi, stato, audio, immagini)")
    p_exp.add_argument("--zip", action="store_true", help="Crea un archivio .zip invece di una cartella")
    p_exp.set_defaults(func=cmd_export)

    p_imp = subparsers.add_parser("import", help="Importa archivi .zip completi di RT ('rt export --all --zip') come nuove lezioni")
    p_imp.add_argument("archives", nargs="+", metavar="archivio.zip", help="Uno o più archivi .zip")
    p_imp.set_defaults(func=cmd_import)

    p_del = subparsers.add_parser("delete", help="Elimina una lezione con testi, audio e immagini (chiede conferma)")
    p_del.add_argument("lesson", help="Lezione: percorso, id o nome della lezione")
    p_del.add_argument("-y", "--yes", action="store_true", help="Non chiedere conferma")
    p_del.set_defaults(func=cmd_delete)

    p_rel = subparsers.add_parser("relevance", help="Assegna le etichette di rilevanza del classificatore alle unità nuove o cambiate")
    p_rel.add_argument("lesson", help="Lezione: percorso, id o nome della lezione")
    p_rel.add_argument("--all", action="store_true", help="Riclassifica anche le unità già etichettate")
    p_rel.add_argument("--mock", action="store_true", help="Modalità prova: nessuna chiamata al classificatore")
    p_rel.set_defaults(func=cmd_relevance)

    p_vph = subparsers.add_parser("validate-phase", help="Segna una fase come valida senza rieseguirla (es. dopo una modifica voluta)")
    p_vph.add_argument("lesson", help="Lezione: percorso, id o nome della lezione")
    p_vph.add_argument("phase", choices=["prepare", "outline", "rewrite", "review", "build"], help="Fase da validare")
    p_vph.set_defaults(func=cmd_validate_phase)

    return parser, {
        "web": p_web,
        "run": p_run,
        "review": p_rsci,
        "recall": p_recall,
        "status": p_stat,
        "setup": p_set,
        "prepare": p_prep,
        "outline": p_out,
        "rewrite": p_rew,
        "build": p_bld,
        "add-images": p_addimg,
        "validate-outline": p_vout,
        "validate-draft": p_vdr,
        "cost": p_cost,
    }


def main(argv: Optional[List[str]] = None) -> None:
    raw_args = sys.argv[1:] if argv is None else argv
    from rt.core.app_switch import forward_to_app
    forward_to_app(_default_project_root(), list(raw_args))  # cartella passata all'app
    from rt.core.bundle import apply_env, utf8_console
    utf8_console()
    apply_env()
    if raw_args and raw_args[0] in ("-v", "--version"):
        from rt.core.version import run_version
        run_version(_default_project_root())
        sys.exit(0)
    elif raw_args and raw_args[0] in ("-u", "--update"):
        from rt.core.version import run_update, BETA, STABLE
        options = {"--beta": BETA, "--stable": STABLE}
        extra = raw_args[1:]
        if len(extra) > 1 or (extra and extra[0] not in options):
            print("Uso: rt -u [--beta | --stable]", file=sys.stderr)
            sys.exit(2)
        code = run_update(_default_project_root(), options[extra[0]] if extra else None)
        sys.exit(code if isinstance(code, int) else 0)

    load_env_file(override=True)
    parser, _ = build_parser()

    normalized_argv = normalize_review_cli_args(raw_args)
    args = parser.parse_args(normalized_argv)
    _ensure_database_or_exit(args.command)
    if args.command is None:
        parser.print_help()
        return
    from rt.llm.errors import LLMFailure
    from rt.pipeline.unit_failures import PhaseIncomplete
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
    except PhaseIncomplete as e:
        print(f"\n⚠️  {e}".replace("Riprova rifà", "rilanciare lo stesso comando rifà"), file=sys.stderr)
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
