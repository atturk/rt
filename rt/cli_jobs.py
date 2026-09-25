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
    print(f"👷 Worker RT avviato (pid {os.getpid()}, job: {', '.join(types)}). Ctrl+C per fermarlo.", flush=True)
    try:
        run_workers(_queue, concurrency=max(1, args.concurrency), **kwargs)
    except KeyboardInterrupt:
        print("\n⏹ Worker fermato: i job in corso tornano in coda.", file=sys.stderr)


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
