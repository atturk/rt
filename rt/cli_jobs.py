"""
rt.cli_jobs
Adattatore CLI della coda dei job (fase D): 'rt worker' esegue i job, 'rt jobs' li elenca,
mostra e annulla. La logica sta in rt.services.jobs e rt.services.worker.
"""
import argparse
import json
import os
import sys
from typing import Any, Dict

from rt.db.engine import DatabaseUnavailable


def configure_worker_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--once", action="store_true", help="Esegue al massimo un job e termina")
    p.add_argument("--concurrency", type=int, default=1, help="Job eseguiti in parallelo (thread, default 1)")
    p.add_argument("--types", default=None, help="Tipi di job da eseguire, separati da virgola (default: tutti)")
    p.add_argument("--lease", type=int, default=None, help="Durata del lease in secondi (default 60)")
    p.add_argument("--poll", type=float, default=1.0, help="Attesa tra due controlli della coda vuota (secondi)")


def configure_jobs_parser(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="jobs_command", required=False, title="Sottocomandi")
    p_list = sub.add_parser("list", help="Elenca i job recenti (default)")
    p_list.add_argument("--state", default=None, help="Filtra per stato (queued, running, waiting_for_decision, ...)")
    p_list.add_argument("--limit", type=int, default=20)
    p_show = sub.add_parser("show", help="Mostra un job e i suoi eventi")
    p_show.add_argument("job_id")
    p_show.add_argument("--json", action="store_true", help="Output JSON")
    p_cancel = sub.add_parser("cancel", help="Annulla un job (quello in esecuzione si ferma al prossimo punto sicuro)")
    p_cancel.add_argument("job_id")


def _queue():
    from rt.services.jobs import get_job_queue
    try:
        return get_job_queue()
    except DatabaseUnavailable as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_worker(args: argparse.Namespace) -> None:
    from rt.services.jobs import DEFAULT_LEASE_SECONDS
    from rt.services.worker import Worker, registered_handlers, run_workers

    handlers = registered_handlers()
    types = [t.strip() for t in args.types.split(",") if t.strip()] if args.types else sorted(handlers)
    unknown = [t for t in types if t not in handlers]
    if unknown:
        print(f"❌ Tipi di job sconosciuti: {', '.join(unknown)} (disponibili: {', '.join(sorted(handlers))})", file=sys.stderr)
        sys.exit(2)
    _queue()  # verifica subito il DB, con messaggio chiaro
    kwargs: Dict[str, Any] = {
        "job_types": types,
        "lease_seconds": args.lease or DEFAULT_LEASE_SECONDS,
        "poll_interval": args.poll,
        "on_message": lambda msg: print(msg, flush=True),
    }
    if args.once:
        done = Worker(_queue(), **kwargs).run(once=True)
        if not done:
            print("Nessun job in coda.")
        return
    _stop_on_signals()
    print(f"👷 Worker RT avviato (pid {os.getpid()}, job: {', '.join(types)}). Ctrl+C per fermarlo.", flush=True)
    try:
        run_workers(_queue, concurrency=max(1, args.concurrency), **kwargs)
    except KeyboardInterrupt:
        print("\n⏹ Worker fermato: i job in corso tornano in coda.", file=sys.stderr)


def _stop_on_signals() -> None:
    """SIGTERM (launchd, kill) e SIGINT fermano il worker come Ctrl+C: il job in corso torna
    subito in coda invece di aspettare la scadenza del lease."""
    import signal

    def _interrupt(signum, frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _interrupt)
        except (ValueError, OSError):  # non nel thread principale
            pass


def _fmt_job(job) -> str:
    where = os.path.basename(job.lesson_path) if job.lesson_path else "-"
    progress = ""
    if job.progress and job.state == "running":
        p = job.progress
        progress = f" [{p.get('phase', '')}" + (f" {p.get('current')}/{p.get('total')}" if p.get("total") else "") + "]"
    return f"{job.id[:12]}  {job.state:<21} {job.type:<16} {where}{progress}"


def cmd_jobs(args: argparse.Namespace) -> None:
    queue = _queue()
    command = getattr(args, "jobs_command", None) or "list"
    if command == "list":
        jobs = queue.list(state=getattr(args, "state", None), limit=getattr(args, "limit", 20))
        if not jobs:
            print("Nessun job.")
        for job in jobs:
            print(_fmt_job(job))
        workers = queue.live_workers()
        print(f"\nWorker attivi: {len(workers)}" + ("" if workers else " (avvia 'rt worker' per eseguire i job in coda)"))
        return
    job = _find(queue, args.job_id)
    if command == "cancel":
        job = queue.cancel(job.id)
        print(f"Job {job.id[:12]}: {job.state}" + (" (annullamento richiesto)" if job.state == "running" else ""))
        return
    events = queue.events(job.id)
    if args.json:
        print(json.dumps({"job": job.to_dict(), "events": [e.to_dict() for e in events]}, ensure_ascii=False, indent=2))
        return
    print(_fmt_job(job))
    if job.error:
        print(f"Errore: {job.error}")
    if job.decision:
        print(f"In attesa di: {job.decision.get('kind')}")
    for e in events:
        detail = e.payload.get("message") or e.payload.get("phase") or e.payload.get("state") or ""
        print(f"  {e.id:>6} {e.type:<22} {detail}")


def _find(queue, prefix: str):
    job = queue.get(prefix)
    if job is not None:
        return job
    matches = [j for j in queue.list(limit=500) if j.id.startswith(prefix)]
    if len(matches) != 1:
        print(f"❌ Job '{prefix}' {'ambiguo' if matches else 'non trovato'}.", file=sys.stderr)
        sys.exit(1)
    return matches[0]


# ---------------------------------------------------------------- rt run --queue

def _render_event(event) -> None:
    p = event.payload
    t = event.type
    if t == "phase_started":
        print(f"▶ {p.get('phase')}", flush=True)
    elif t == "phase_progress" and p.get("total"):
        print(f"   {p.get('current')}/{p.get('total')} {p.get('message', '')}".rstrip(), flush=True)
    elif t == "phase_completed":
        print(f"{'⏭' if p.get('skipped') else '✔'} {p.get('phase')}", flush=True)
    elif t == "phase_failed":
        print(f"❌ {p.get('phase')}: {p.get('message')}", flush=True)
    elif t == "notice":
        print(p.get("message", ""), flush=True)
    elif t == "job_started" and p.get("attempt", 1) > 1:
        print(f"↻ Ripreso da un worker (tentativo {p['attempt']})", flush=True)


def _answer_decision(job, options, decisions) -> bool:
    """Chiede in terminale la decisione su cui il job è fermo. True se è stata presa (il job
    è tornato in coda), False se il job resta in attesa."""
    from rt.services import outline_service
    from rt.services.jobs import resume_waiting_jobs
    from rt.services.review_service import is_review_complete

    kind = (job.decision or {}).get("kind")
    lesson_dir = (job.decision or {}).get("payload", {}).get("lesson_dir") or job.lesson_path
    if kind == "outline_approval":
        decisions.approve_outline(lesson_dir, force=options.force, force_mock=options.mock)
        if outline_service.is_outline_approved(lesson_dir):
            resume_waiting_jobs(lesson_dir, "outline_approval")
            return True
    elif kind == "science_issue":
        from rt.services.pipeline_service import _resolve_channel
        channel = _resolve_channel(options.channel)
        decisions.review_science_issues(lesson_dir, channel, "all" if options.auto_accept else None)
        if is_review_complete(lesson_dir):
            resume_waiting_jobs(lesson_dir, "science_issue")
            return True
    elif kind == "setup_metadata":
        missing = ", ".join((job.decision or {}).get("payload", {}).get("missing") or [])
        print(f"⏸ Mancano i metadati della lezione ({missing}): rilancia con -d/-m/-a.", file=sys.stderr)
        return False
    print(f"⏸ Il job {job.id[:12]} resta in attesa di una decisione ({kind}).")
    return False


def run_queued(raw_inputs, options, decisions) -> None:
    """'rt run --queue': accoda la pipeline e ne segue il progresso dagli eventi del job.
    Le decisioni (outline, issue) si prendono qui come in 'rt run'; Ctrl+C smette di seguire
    ma il job continua nel worker."""
    from rt.services.job_handlers import RUN_PIPELINE, pipeline_payload
    from rt.services.pipeline_service import is_audio_input

    queue = _queue()
    lesson = None if is_audio_input(raw_inputs) else raw_inputs[0]
    job_id = queue.enqueue(RUN_PIPELINE, lesson, pipeline_payload(raw_inputs, options), created_by="cli")
    print(f"📥 Job {job_id[:12]} in coda.", flush=True)
    if not queue.live_workers(RUN_PIPELINE):
        print("⚠️  Nessun worker attivo: il job partirà quando avvii 'rt worker'.", flush=True)
    cursor = 0
    try:
        while True:
            for event in queue.stream_events(job_id, cursor, poll_interval=0.5):
                cursor = event.id
                _render_event(event)
            job = queue.get(job_id)
            if job.state == "succeeded":
                print(f"✅ Job completato: {job.result.get('lesson_dir') or ''}".rstrip(), flush=True)
                return
            if job.state in ("failed", "cancelled"):
                print(f"❌ Job {job.state}" + (f": {job.error}" if job.error else ""), file=sys.stderr)
                sys.exit(1)
            if job.state == "waiting_for_decision" and not _answer_decision(job, options, decisions):
                return
    except KeyboardInterrupt:
        print(f"\n⏹ Smetto di seguire il job: continua nel worker ('rt jobs show {job_id[:12]}').", file=sys.stderr)
        sys.exit(130)
