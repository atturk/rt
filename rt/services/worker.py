"""
rt.services.worker
Esecutore dei job della coda ('rt worker'). Il client LLM è sincrono: ogni job gira in un
thread normale con il proprio RunContext; un secondo thread rinnova il lease e controlla le
richieste di annullamento.

Un job si esegue tramite un handler registrato per il suo tipo (rt/services/job_handlers.py)
che riceve JobInfo e RunContext e restituisce un JobOutcome. Gli eventi del RunContext
diventano righe di job_events (JobEventReporter), così CLI e API seguono il progresso.
"""
import dataclasses
import logging
import os
import platform
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from rt.services.context import CancelToken, RunCancelled, RunContext
from rt.services.events import Event, PhaseCompleted, PhaseProgress, PhaseStarted
from rt.services.jobs import DEFAULT_LEASE_SECONDS, DbJobQueue, JobInfo, JobState
from rt.storage import fs

logger = logging.getLogger(__name__)


@dataclass
class JobOutcome:
    state: JobState
    result: Dict[str, Any] = field(default_factory=dict)
    decision: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    lesson_path: Optional[str] = None


JobHandler = Callable[[JobInfo, RunContext], JobOutcome]
_HANDLERS: Dict[str, JobHandler] = {}


def mock_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """'rt worker --mock': ogni job gira con l'LLM (e la STT delle risposte vocali) in mock,
    qualunque cosa chieda il client. Serve ai test end-to-end della SPA."""
    out = dict(payload or {})
    out["mock"] = True
    out["force_mock"] = True
    if isinstance(out.get("options"), dict):
        out["options"] = {**out["options"], "mock": True}
    return out


def register_handler(job_type: str, handler: JobHandler) -> None:
    _HANDLERS[job_type] = handler


def registered_handlers() -> Dict[str, JobHandler]:
    import rt.services.job_handlers  # noqa: F401 - registra i tipi standard
    import rt.services.api_jobs  # noqa: F401 - tipi usati dall'API (fase E)
    return dict(_HANDLERS)


class JobEventReporter:
    """Reporter che scrive ogni evento del motore in job_events e tiene aggiornato
    jobs.progress. Se nel frattempo è stato chiesto l'annullamento, ferma il job tramite il
    CancelToken (il motore lo controlla tra un'unità e l'altra). Un errore di scrittura non
    ferma il job (resta nei log)."""

    def __init__(self, queue: DbJobQueue, job_id: str, cancel_token: Optional[CancelToken] = None):
        self.queue = queue
        self.job_id = job_id
        self.cancel_token = cancel_token
        self._warned = False

    def emit(self, event: Event) -> None:
        progress = None
        if isinstance(event, PhaseStarted):
            progress = {"phase": event.phase, "step": event.step, "total_steps": event.total_steps}
        elif isinstance(event, PhaseProgress):
            progress = {"phase": event.phase, "current": event.current, "total": event.total, "message": event.message}
        elif isinstance(event, PhaseCompleted):
            progress = {"phase": event.phase, "completed": True, "step": event.step, "total_steps": event.total_steps}
        try:
            cancel = self.queue.add_event(self.job_id, event.type, event.model_dump(mode="json"), progress=progress)
            if cancel and self.cancel_token is not None:
                self.cancel_token.cancel()
        except Exception as exc:
            if not self._warned:
                self._warned = True
                logger.warning("Evento del job %s non salvato: %s", self.job_id, exc)


def _sanitize(message: str) -> str:
    try:
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        return GLOBAL_CREDENTIALS.sanitize_secrets(message)
    except Exception:
        return message


class _Heartbeat(threading.Thread):
    """Rinnova il lease ogni lease/3 secondi; su richiesta di annullamento o lease perso
    ferma il job tramite il CancelToken."""

    def __init__(self, queue: DbJobQueue, job_id: str, worker_id: str, lease_seconds: int, token: CancelToken):
        super().__init__(name=f"rt-heartbeat-{job_id[:8]}", daemon=True)
        self.queue, self.job_id, self.worker_id = queue, job_id, worker_id
        self.lease_seconds = lease_seconds
        self.token = token
        self.lease_lost = False
        self._stop_event = threading.Event()
        self.interval = max(0.05, lease_seconds / 3)

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            self.beat()

    def beat(self) -> None:
        try:
            hb = self.queue.heartbeat(self.job_id, self.worker_id, self.lease_seconds)
            self.queue.beat_worker(self.worker_id, self.job_id)
        except Exception as exc:  # DB occupato: si riprova al giro successivo
            logger.warning("Rinnovo del lease non riuscito per il job %s: %s", self.job_id, exc)
            return
        if not hb.lease_kept:
            self.lease_lost = True
            self.token.cancel()
        elif hb.cancel_requested:
            self.token.cancel()

    def stop(self) -> None:
        self._stop_event.set()


class Worker:
    """Preleva ed esegue job. Un Worker esegue un job alla volta; 'rt worker --concurrency N'
    avvia N Worker in thread separati."""

    def __init__(self, queue: DbJobQueue, worker_id: Optional[str] = None,
                 job_types: Optional[Sequence[str]] = None, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                 poll_interval: float = 1.0, handlers: Optional[Dict[str, JobHandler]] = None,
                 on_message: Optional[Callable[[str], None]] = None, mock: bool = False):
        self.queue = queue
        self.mock = mock
        self.handlers = dict(handlers) if handlers is not None else registered_handlers()
        self.job_types = list(job_types) if job_types else sorted(self.handlers)
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.on_message = on_message or (lambda msg: logger.info(msg))
        self._registered = False

    def register(self) -> None:
        if not self._registered:
            self.queue.register_worker(self.worker_id, socket.gethostname(), os.getpid(),
                                       platform.system().lower(), self.job_types)
            self._registered = True

    def run(self, once: bool = False, stop_event: Optional[threading.Event] = None,
            max_jobs: Optional[int] = None) -> int:
        """Ciclo del worker. once=True esegue al massimo un job e ritorna. Restituisce il
        numero di job eseguiti."""
        self.register()
        done = 0
        try:
            while not (stop_event is not None and stop_event.is_set()):
                job = self.run_once()
                if job is not None:
                    done += 1
                if once or (max_jobs is not None and done >= max_jobs):
                    break
                if job is None:
                    self.queue.beat_worker(self.worker_id)
                    if stop_event is not None:
                        stop_event.wait(self.poll_interval)
                    else:
                        time.sleep(self.poll_interval)
        finally:
            self.queue.stop_worker(self.worker_id)
        return done

    def run_once(self) -> Optional[JobInfo]:
        """Prende ed esegue un job; None se la coda è vuota."""
        self.register()
        job = self.queue.claim(self.worker_id, self.job_types, self.lease_seconds)
        if job is None:
            return None
        self.execute(job)
        return self.queue.get(job.id)

    def execute(self, job: JobInfo) -> None:
        if self.mock:
            job = dataclasses.replace(job, payload=mock_payload(job.payload))
        handler = self.handlers.get(job.type)
        if handler is None:
            self.queue.finish(job.id, self.worker_id, JobState.FAILED, error=f"Tipo di job sconosciuto: {job.type}")
            return
        lock = None
        if job.lesson_path and fs.isdir(job.lesson_path):
            from rt.core.process_lock import LessonBusy, lesson_work_lock
            lock = lesson_work_lock(job.lesson_path)
            try:
                lock.__enter__()
            except LessonBusy:
                # la lezione è in lavorazione da un 'rt run' in processo: si riprova dopo
                self.queue.release(job.id, self.worker_id, reason="lesson_busy")
                return
        token = CancelToken()
        ctx = RunContext(lesson_dir=job.lesson_path, reporter=JobEventReporter(self.queue, job.id, token), cancel_token=token)
        heartbeat = _Heartbeat(self.queue, job.id, self.worker_id, self.lease_seconds, token)
        heartbeat.beat()  # un annullamento arrivato prima dell'avvio vale subito
        heartbeat.start()
        self.on_message(f"▶ job {job.id[:8]} {job.type}" + (f" · {os.path.basename(job.lesson_path)}" if job.lesson_path else ""))
        outcome: Optional[JobOutcome] = None
        try:
            try:
                ctx.check_cancelled()
                outcome = handler(job, ctx)
            except RunCancelled:
                outcome = JobOutcome(state=JobState.CANCELLED)
            except Exception as exc:  # noqa: BLE001 - l'errore diventa lo stato del job
                logger.exception("Job %s fallito", job.id)
                outcome = JobOutcome(state=JobState.FAILED, error=_sanitize(f"{type(exc).__name__}: {exc}"))
            except BaseException:
                # Ctrl+C / arresto del worker: il job torna in coda e un altro worker lo
                # riprende dai checkpoint già salvati.
                heartbeat.stop()
                self.queue.release(job.id, self.worker_id, reason="worker_stopped")
                raise
        finally:
            heartbeat.stop()
            if lock is not None:
                lock.__exit__(None, None, None)
        if heartbeat.lease_lost:
            self.on_message(f"⚠️ job {job.id[:8]}: lease perso, il risultato non viene registrato")
            return
        self.queue.finish(job.id, self.worker_id, outcome.state, result=outcome.result, error=outcome.error,
                          decision=outcome.decision, lesson_path=outcome.lesson_path)
        self.on_message(f"■ job {job.id[:8]} {outcome.state.value}" + (f": {outcome.error}" if outcome.error else ""))


def run_workers(queue_factory: Callable[[], DbJobQueue], concurrency: int = 1, **kwargs: Any) -> None:
    """Avvia concurrency Worker in thread e attende Ctrl+C. Con concurrency=1 il worker
    gira nel thread principale."""
    if concurrency <= 1:
        Worker(queue_factory(), **kwargs).run()
        return
    stop = threading.Event()
    threads = []
    for _ in range(concurrency):
        worker = Worker(queue_factory(), **kwargs)
        t = threading.Thread(target=worker.run, kwargs={"stop_event": stop}, name=f"rt-worker-{worker.worker_id}", daemon=True)
        t.start()
        threads.append(t)
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
