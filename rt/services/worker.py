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
from typing import Any, Callable, Dict, List, Optional, Sequence

from rt.services.context import CancelToken, RunCancelled, RunContext
from rt.services.events import Event, PhaseCompleted, PhaseProgress, PhaseStarted, ReviewUnitDone, ReviewUnitsQueued, ReviewUnitStarted
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
    progress: Optional[Dict[str, Any]] = None
    event_type: Optional[str] = None
    event_payload: Optional[Dict[str, Any]] = None


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


# Job lunghi di cui avvisare quando non riescono (le notifiche le registra chi avvia il worker:
# rt/services non conosce Telegram).
NOTIFY_FAILED_TYPES = frozenset({
    "run_pipeline", "run_phase", "ingest_audio", "ingest_sources", "ingest_notes",
    "update_lesson", "add_images", "review_unit", "review_part",
})
_JOB_NOTIFIERS: List[Any] = []


def register_job_notifier(notifier: Any) -> None:
    """notifier.job_waiting(lesson_dir, decision) e notifier.job_failed(lesson_dir, error).
    Un notifier dello stesso tipo già registrato viene sostituito."""
    _JOB_NOTIFIERS[:] = [n for n in _JOB_NOTIFIERS if type(n) is not type(notifier)] + [notifier]


def unregister_job_notifiers() -> None:
    _JOB_NOTIFIERS.clear()


def _notify_job_outcome(job: JobInfo, outcome: "JobOutcome") -> None:
    lesson_dir = outcome.lesson_path or job.lesson_path
    for notifier in list(_JOB_NOTIFIERS):
        try:
            if outcome.state == JobState.WAITING_FOR_DECISION and outcome.decision:
                notifier.job_waiting(lesson_dir, outcome.decision)
            elif outcome.state == JobState.FAILED and job.type in NOTIFY_FAILED_TYPES:
                notifier.job_failed(lesson_dir, outcome.error)
        except Exception:  # noqa: BLE001 - una notifica non cambia l'esito del job
            logger.warning("Notifica del job %s non inviata", job.id, exc_info=True)


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
        self._review_pending = None
        self._review_running = None

    def emit(self, event: Event) -> None:
        progress = None
        if isinstance(event, (ReviewUnitsQueued, ReviewUnitDone, ReviewUnitStarted)):
            self._review_pending = event.pending_units
            self._review_running = event.running_units
            progress = {"phase": "review", "pending_units": event.pending_units, "running_units": event.running_units}
            if isinstance(event, (ReviewUnitDone, ReviewUnitStarted)):
                progress["unit_id"] = event.unit_id
            if isinstance(event, ReviewUnitDone):
                progress["issues"] = event.issues
        elif isinstance(event, PhaseStarted):
            self._review_pending = None
            self._review_running = None
            progress = {"phase": event.phase, "step": event.step, "total_steps": event.total_steps}
        elif isinstance(event, PhaseProgress):
            progress = {"phase": event.phase, "current": event.current, "total": event.total, "message": event.message,
                        "unit_id": event.unit_id, "unit_title": event.unit_title, "failed": event.failed}
        elif isinstance(event, PhaseCompleted):
            progress = {"phase": event.phase, "completed": True, "partial": event.partial, "step": event.step,
                        "total_steps": event.total_steps}
        if isinstance(event, PhaseProgress) and event.phase == "review" and self._review_pending is not None:
            progress["pending_units"] = self._review_pending
            progress["running_units"] = self._review_running
        try:
            lesson_dir = getattr(event, "lesson_dir", None)
            if lesson_dir:
                self.queue.attach_lesson(self.job_id, str(lesson_dir))
            if isinstance(event, PhaseCompleted) and event.phase == "setup" and (event.result or {}).get("lesson_dir"):
                # Lezione appena creata dall'audio: il job la indica subito (non solo alla fine),
                # così la web app apre la pagina della lezione mentre la pipeline continua.
                self.queue.attach_lesson(self.job_id, str(event.result["lesson_dir"]))
            cancel = self.queue.add_event(self.job_id, event.type, event.model_dump(mode="json"), progress=progress)
            if cancel and self.cancel_token is not None:
                self.cancel_token.cancel()
        except Exception as exc:
            if not self._warned:
                self._warned = True
                logger.warning("Evento del job %s non salvato: %s", self.job_id, exc)


def job_error_message(exc: BaseException) -> str:
    """Errore del job come lo legge l'utente: i messaggi già scritti per l'interfaccia (fase
    incompleta, errori di dominio dei servizi, errori del modello spiegati) senza il nome
    della classe Python."""
    from rt.llm.errors import LLMFailure, describe_llm_failure
    from rt.pipeline.unit_failures import PhaseIncomplete
    from rt.services.errors import ServiceError
    if isinstance(exc, ServiceError):
        return exc.message
    if isinstance(exc, PhaseIncomplete):
        return str(exc)
    if isinstance(exc, LLMFailure):
        where = f" (unità {exc.unit_id})" if exc.unit_id else ""
        text = describe_llm_failure(exc)
        return f"Errore del modello{where}: {text}"
    return f"{type(exc).__name__}: {exc}"


def _sanitize(message: str) -> str:
    try:
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        return GLOBAL_CREDENTIALS.sanitize_secrets(message)
    except Exception:
        return message


CANCEL_POLL_SECONDS = 2.0
LESSON_BUSY_BACKOFF_SECONDS = 5.0


class _Heartbeat(threading.Thread):
    """Rinnova il lease ogni lease/3 secondi; su richiesta di annullamento o lease perso
    ferma il job tramite il CancelToken. L'annullamento si controlla più spesso (ogni
    CANCEL_POLL_SECONDS): dall'app deve fermare il job subito, anche a metà di una chiamata."""

    def __init__(self, queue: DbJobQueue, job_id: str, worker_id: str, lease_seconds: int, token: CancelToken):
        super().__init__(name=f"rt-heartbeat-{job_id[:8]}", daemon=True)
        self.queue, self.job_id, self.worker_id = queue, job_id, worker_id
        self.lease_seconds = lease_seconds
        self.token = token
        self.lease_lost = False
        self._stop_event = threading.Event()
        self.interval = max(0.05, lease_seconds / 3)

    def run(self) -> None:
        poll = min(self.interval, CANCEL_POLL_SECONDS)
        # Orologio di parete: il monotonic su macOS si ferma durante lo stop, e al risveglio il
        # lease scaduto va rinnovato subito, non dopo un altro intervallo.
        last_beat = time.time()
        while not self._stop_event.wait(poll):
            if abs(time.time() - last_beat) >= self.interval:
                last_beat = time.time()
                self.beat()
            elif not self.token.cancelled:
                self.poll_cancel()

    def poll_cancel(self) -> None:
        try:
            if self.queue.cancel_requested(self.job_id):
                self.token.cancel()
        except Exception as exc:  # DB occupato: ci pensa il prossimo controllo
            logger.debug("Controllo dell'annullamento non riuscito per il job %s: %s", self.job_id, exc)

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
                 on_message: Optional[Callable[[str], None]] = None, mock: bool = False,
                 stt: Optional[str] = "auto", batch_poll_interval: float = 60.0):
        from rt.services.jobs import detect_stt_capability
        self.queue = queue
        self.mock = mock
        # RT4-G1: motore di trascrizione del worker (None = non prende i job che trascrivono)
        self.stt = detect_stt_capability(stt, mock=mock)
        self.handlers = dict(handlers) if handlers is not None else registered_handlers()
        self.job_types = list(job_types) if job_types else sorted(self.handlers)
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.batch_poll_interval = max(0.05, float(batch_poll_interval))
        self.on_message = on_message or (lambda msg: logger.info(msg))
        self._registered = False
        self._last_batch_poll = 0.0
        self._last_batch_cleanup = 0.0
        self._batch_backoff_until: Dict[str, float] = {}
        self._batch_backoff_strikes: Dict[str, int] = {}

    def register(self) -> None:
        if not self._registered:
            self.queue.register_worker(self.worker_id, socket.gethostname(), os.getpid(),
                                       platform.system().lower(), self.job_types, {"stt": self.stt})
            self._registered = True

    def run(self, once: bool = False, stop_event: Optional[threading.Event] = None,
            max_jobs: Optional[int] = None) -> int:
        """Ciclo del worker. once=True esegue al massimo un job e ritorna. Restituisce il
        numero di job eseguiti."""
        self.register()
        done = 0
        try:
            while not (stop_event is not None and stop_event.is_set()):
                now_mono = time.monotonic()
                if now_mono - self._last_batch_poll >= self.batch_poll_interval:
                    self._last_batch_poll = now_mono
                    self.poll_provider_batches(now=now_mono)
                if now_mono - self._last_batch_cleanup >= 3600.0:
                    self._last_batch_cleanup = now_mono
                    try:
                        from rt.llm import deferred
                        deferred.cleanup(db=self.queue.db)
                    except Exception:
                        logger.debug("Pulizia cache batch non riuscita", exc_info=True)
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

    def poll_provider_batches(self, now: Optional[float] = None) -> int:
        """Controlla tutti i lotti batch aperti e rimette in coda i job completati o falliti."""
        from rt.llm import deferred
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        from rt.llm.errors import RateLimitFailure
        from rt.llm.providers import get_provider

        now_mono = time.monotonic() if now is None else now
        resumed = 0
        try:
            batches = deferred.open_batches(db=self.queue.db)
        except Exception as exc:
            logger.warning("Lettura dei lotti batch aperti non riuscita: %s", exc)
            return 0

        for batch in batches:
            batch_id = batch["batch_id"]
            if self._batch_backoff_until.get(batch_id, 0.0) > now_mono:
                continue
            provider_name = batch["provider"]
            cred_ref = batch.get("credential_ref")
            base_url = batch.get("base_url")
            try:
                provider = get_provider(provider_name)
                api_key = GLOBAL_CREDENTIALS.get_api_key(cred_ref) if cred_ref else None
                if not api_key:
                    default_cred = GLOBAL_CREDENTIALS.get_default_credential_for_provider(provider_name)
                    if default_cred:
                        api_key = GLOBAL_CREDENTIALS.get_api_key(default_cred)
                if not api_key:
                    logger.warning("API key mancante per controllare il lotto %s (%s)", batch_id, provider_name)
                    continue
                status, results = provider.poll_batch(batch_id, api_key=api_key, base_url=base_url)
            except RateLimitFailure as rl:
                strikes = self._batch_backoff_strikes.get(batch_id, 0) + 1
                self._batch_backoff_strikes[batch_id] = strikes
                delay = rl.retry_after if rl.retry_after and rl.retry_after > 0 else min(900.0, 60.0 * (2 ** (strikes - 1)))
                self._batch_backoff_until[batch_id] = now_mono + delay
                logger.warning("Rate limit (429) controllando il lotto %s: riprovo tra %.0fs", batch_id, delay)
                continue
            except Exception as exc:
                logger.warning("Errore controllando il lotto %s (%s): %s", batch_id, provider_name, exc)
                continue

            self._batch_backoff_until.pop(batch_id, None)
            self._batch_backoff_strikes.pop(batch_id, None)

            if status == "completed":
                affected = deferred.store_results(batch_id, results or {}, db=self.queue.db)
                try:
                    provider.cleanup_batch(batch_id, api_key=api_key, base_url=base_url)
                except Exception:
                    logger.debug("Pulizia remota lotto %s non riuscita", batch_id, exc_info=True)
                for jid in affected:
                    if not deferred.job_has_waiting_items(jid, db=self.queue.db):
                        try:
                            info = self.queue.get(jid)
                            if info and info.state == JobState.WAITING_FOR_PROVIDER.value:
                                self.queue.resume_after_provider(jid)
                                resumed += 1
                        except Exception:
                            logger.warning("Ripresa del job %s dopo lotto %s non riuscita", jid, batch_id, exc_info=True)
            elif status in ("failed", "expired", "cancelled"):
                affected = deferred.mark_batch_fallback(batch_id, error=status, db=self.queue.db)
                try:
                    provider.cleanup_batch(batch_id, api_key=api_key, base_url=base_url)
                except Exception:
                    logger.debug("Pulizia remota lotto %s non riuscita", batch_id, exc_info=True)
                for jid in affected:
                    if not deferred.job_has_waiting_items(jid, db=self.queue.db):
                        try:
                            info = self.queue.get(jid)
                            if info and info.state == JobState.WAITING_FOR_PROVIDER.value:
                                self.queue.resume_after_provider(
                                    jid,
                                    fallback_sync=True,
                                    reason=f"Lotto batch {status}: ripresa automatica in modalità sincrona",
                                )
                                resumed += 1
                        except Exception:
                            logger.warning("Ripresa in fallback del job %s dopo lotto %s non riuscita", jid, batch_id, exc_info=True)
        return resumed

    def _submit_deferred_job(self, job: JobInfo, ctx: RunContext) -> JobOutcome:
        from rt.llm import deferred
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        from rt.llm.errors import AuthenticationFailure
        from rt.llm.providers import get_provider

        pending = deferred.pending_for_job(job.id, db=self.queue.db)
        if not pending and not deferred.job_has_waiting_items(job.id, db=self.queue.db):
            raise RuntimeError("Fase differita senza richieste pendenti registrate.")

        grouped: Dict[tuple, list] = {}
        for entry in pending:
            group_key = (entry.provider, entry.model, entry.credential_ref or "", entry.base_url or "")
            grouped.setdefault(group_key, []).append(entry)

        batch_ids: List[str] = []
        providers_used: List[str] = []
        total_requests = len(pending)

        try:
            for (provider_name, model_name, cred_ref, base_url), entries in grouped.items():
                provider = get_provider(provider_name)
                api_key = GLOBAL_CREDENTIALS.get_api_key(cred_ref) if cred_ref else None
                if not api_key:
                    default_cred = GLOBAL_CREDENTIALS.get_default_credential_for_provider(provider_name)
                    if default_cred:
                        api_key = GLOBAL_CREDENTIALS.get_api_key(default_cred)
                if not api_key:
                    raise AuthenticationFailure(
                        f"API key mancante per inviare il lotto batch al provider '{provider_name}'.",
                        provider=provider_name,
                        model=model_name,
                    )
                reqs = [{"custom_id": e.key, "body": e.request} for e in entries]
                batch_id = provider.submit_batch(
                    reqs,
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url or None,
                )
                deferred.mark_submitted([e.key for e in entries], batch_id, db=self.queue.db)
                batch_ids.append(batch_id)
                if provider_name not in providers_used:
                    providers_used.append(provider_name)
        except Exception:
            deferred.delete_for_job(job.id, states=("pending",), db=self.queue.db)
            raise

        provider_label = ", ".join(providers_used) if providers_used else "provider"
        return JobOutcome(
            state=JobState.WAITING_FOR_PROVIDER,
            lesson_path=ctx.lesson_dir or job.lesson_path,
            progress={
                "phase": "batch",
                "message": "In attesa del provider (batch)",
                "requests": total_requests,
                "provider": provider_label,
            },
            event_type="job_waiting_provider",
            event_payload={
                "requests": total_requests,
                "provider": provider_label,
                "batches": batch_ids,
            },
        )

    def run_once(self) -> Optional[JobInfo]:
        """Prende ed esegue un job; None se la coda è vuota."""
        self.register()
        job = self.queue.claim(self.worker_id, self.job_types, self.lease_seconds,
                               can_transcribe=bool(self.stt))
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
        if job.type != "documents" and job.lesson_path and fs.isdir(job.lesson_path):
            from rt.core.process_lock import LessonBusy, lesson_work_lock
            lock = lesson_work_lock(job.lesson_path)
            try:
                lock.__enter__()
            except LessonBusy:
                # la lezione è in lavorazione da un 'rt run' in processo: si riprova dopo
                self.queue.release(job.id, self.worker_id, reason="lesson_busy")
                # Pausa: senza, il worker lo riprende e lo rilascia migliaia di volte al secondo.
                time.sleep(LESSON_BUSY_BACKOFF_SECONDS)
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
                from rt.llm.deferred import use_batch_fallback, use_job_id
                from rt.llm.errors import DeferredCall, DeferredPhase
                ctx.check_cancelled()
                if job.type in {'ingest_audio', 'ingest_sources', 'ingest_notes', 'run_pipeline'} and not job.lesson_path:
                    options = job.payload.get('options') or {}
                    if options.get('date') and options.get('materia') and options.get('dest_dir'):
                        from rt.services.lesson_conflicts import require_no_lesson_conflict
                        require_no_lesson_conflict(options['date'], options['materia'], options.get('ora'), options['dest_dir'])
                fallback_flag = bool((job.payload or {}).get("batch_fallback"))
                with use_job_id(job.id), use_batch_fallback(fallback_flag):
                    outcome = handler(job, ctx)
            except (DeferredCall, DeferredPhase):
                try:
                    outcome = self._submit_deferred_job(job, ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Invio batch del job %s fallito", job.id)
                    outcome = JobOutcome(state=JobState.FAILED, error=_sanitize(job_error_message(exc)))
            except RunCancelled:
                outcome = JobOutcome(state=JobState.CANCELLED)
            except Exception as exc:  # noqa: BLE001 - l'errore diventa lo stato del job
                logger.exception("Job %s fallito", job.id)
                from rt.services.errors import ServiceError
                from rt.services.lesson_conflicts import LessonConflict
                if isinstance(exc, (LessonConflict, ServiceError)) and getattr(exc, "code", None):
                    result = {"code": exc.code, "details": exc.details}
                else:
                    result = {}
                outcome = JobOutcome(state=JobState.FAILED, error=_sanitize(job_error_message(exc)), result=result)
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
                          decision=outcome.decision, lesson_path=outcome.lesson_path,
                          progress=outcome.progress, event_type=outcome.event_type,
                          event_payload=outcome.event_payload)
        from rt.llm.deferred import use_job_id
        with use_job_id(job.id):
            _notify_job_outcome(job, outcome)
        if job.type == "documents" and outcome.state == JobState.SUCCEEDED and job.lesson_path:
            from rt.services.documents_service import ensure_documents_queued
            ensure_documents_queued(job.lesson_path, self.queue)
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
