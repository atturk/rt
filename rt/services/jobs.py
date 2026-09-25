"""
rt.services.jobs
Coda di job persistente (fase D). La porta JobQueue è ciò che usano CLI, Telegram e API;
DbJobQueue la implementa sulle tabelle jobs/job_events del database di RT (niente Redis).

Ciclo di vita di un job:

    queued ──claim──▶ running ──▶ succeeded | failed | cancelled
       ▲                 │
       │                 ├──▶ waiting_for_decision ──resume──▶ queued
       └─lease scaduto───┘      (la decisione arriva da outline_service / review_service)

Il worker prende un job con un lease (lease_until) e lo rinnova finché lavora; se muore, il
lease scade e il job torna in coda (fino a max_attempts prese). Mentre un job è 'running'
jobs.active_lesson vale il percorso della lezione ed è UNIQUE: due job mutanti sulla stessa
lezione non possono girare insieme, garantito dal DB.
"""
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Protocol, Sequence, Union

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from rt.db.engine import Database
from rt.db.models import Job, JobEvent, Worker, utcnow
from rt.db.repositories import normalize_lesson_path
from rt.db.session import session_scope


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATES = frozenset({JobState.QUEUED.value, JobState.RUNNING.value, JobState.WAITING_FOR_DECISION.value})
TERMINAL_STATES = frozenset({JobState.SUCCEEDED.value, JobState.FAILED.value, JobState.CANCELLED.value})

DEFAULT_LEASE_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 3
WORKER_ALIVE_SECONDS = 90


class JobError(RuntimeError):
    """Operazione non valida sulla coda (job inesistente, stato incompatibile)."""


@dataclass
class JobInfo:
    id: str
    type: str
    state: str
    lesson_path: Optional[str]
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    worker_id: Optional[str] = None
    cancel_requested: bool = False
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("created_at", "started_at", "finished_at"):
            if data[key] is not None:
                data[key] = data[key].isoformat() + "Z"
        return data

    @classmethod
    def from_row(cls, row: Job) -> "JobInfo":
        return cls(
            id=row.id, type=row.type, state=row.state, lesson_path=row.lesson_path,
            payload=dict(row.payload or {}), result=row.result, error=row.error,
            progress=row.progress, decision=row.decision, attempts=row.attempts,
            max_attempts=row.max_attempts, worker_id=row.worker_id,
            cancel_requested=bool(row.cancel_requested), created_by=row.created_by,
            created_at=row.created_at, started_at=row.started_at, finished_at=row.finished_at,
        )


@dataclass
class JobEventInfo:
    id: int
    job_id: str
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if data["created_at"] is not None:
            data["created_at"] = data["created_at"].isoformat() + "Z"
        return data


@dataclass
class Heartbeat:
    lease_kept: bool
    cancel_requested: bool


LessonRef = Union[str, int, None]


class JobQueue(Protocol):
    """Porta della coda: ciò che serve a chi accoda e segue i job (CLI, Telegram, API)."""

    def enqueue(self, job_type: str, lesson_id: LessonRef = None, payload: Optional[Dict[str, Any]] = None,
                *, created_by: Optional[str] = None, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str: ...

    def cancel(self, job_id: str) -> JobInfo: ...

    def get(self, job_id: str) -> Optional[JobInfo]: ...

    def list(self, state: Optional[Union[str, Sequence[str]]] = None, lesson_id: LessonRef = None,
             limit: int = 50) -> List[JobInfo]: ...

    def events(self, job_id: str, after_id: int = 0) -> List[JobEventInfo]: ...

    def stream_events(self, job_id: str, after_id: int = 0, poll_interval: float = 0.5,
                      timeout: Optional[float] = None) -> Iterator[JobEventInfo]: ...


def json_safe(value: Any) -> Any:
    """Copia serializzabile in JSON (i risultati delle fasi contengono Path, datetime...)."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


class DbJobQueue:
    """JobQueue sul database. Oltre alla porta espone le operazioni del worker (claim,
    heartbeat, finish, release) e il registro dei worker vivi."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ riferimenti lezione

    def _lesson_path(self, session, lesson_id: LessonRef) -> Optional[str]:
        if lesson_id is None or lesson_id == "":
            return None
        if isinstance(lesson_id, int):
            from rt.db.models import Lesson
            lesson = session.get(Lesson, lesson_id)
            if lesson is None:
                raise JobError(f"Lezione {lesson_id} inesistente nel database")
            return lesson.path
        return normalize_lesson_path(str(lesson_id))

    # ------------------------------------------------------------ porta

    def enqueue(self, job_type: str, lesson_id: LessonRef = None, payload: Optional[Dict[str, Any]] = None,
                *, created_by: Optional[str] = None, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
        job_id = uuid.uuid4().hex
        with session_scope(self.db) as s:
            job = Job(id=job_id, type=job_type, state=JobState.QUEUED.value,
                      lesson_path=self._lesson_path(s, lesson_id), payload=json_safe(payload or {}),
                      attempts=0, max_attempts=max_attempts, cancel_requested=False, created_by=created_by)
            s.add(job)
            s.flush()
            s.add(JobEvent(job_id=job_id, type="job_queued", payload={"job_type": job_type}))
        return job_id

    def get(self, job_id: str) -> Optional[JobInfo]:
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            return JobInfo.from_row(row) if row is not None else None

    def list(self, state: Optional[Union[str, Sequence[str]]] = None, lesson_id: LessonRef = None,
             limit: int = 50) -> List[JobInfo]:
        with session_scope(self.db) as s:
            stmt = select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit)
            if state:
                states = [state] if isinstance(state, str) else list(state)
                stmt = stmt.where(Job.state.in_(states))
            if lesson_id is not None:
                stmt = stmt.where(Job.lesson_path == self._lesson_path(s, lesson_id))
            return [JobInfo.from_row(r) for r in s.scalars(stmt)]

    def cancel(self, job_id: str) -> JobInfo:
        """Un job in coda o in attesa di decisione si annulla subito; uno in esecuzione
        riceve la richiesta e il worker lo ferma al prossimo punto di controllo."""
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            if row is None:
                raise JobError(f"Job {job_id} inesistente")
            if row.state in TERMINAL_STATES:
                return JobInfo.from_row(row)
            if row.state == JobState.RUNNING.value:
                row.cancel_requested = True
                s.add(JobEvent(job_id=job_id, type="job_cancel_requested", payload={}))
            else:
                row.state = JobState.CANCELLED.value
                row.cancel_requested = True
                row.finished_at = utcnow()
                row.active_lesson = None
                s.add(JobEvent(job_id=job_id, type="job_finished", payload={"state": row.state}))
            return JobInfo.from_row(row)

    def events(self, job_id: str, after_id: int = 0) -> List[JobEventInfo]:
        with session_scope(self.db) as s:
            stmt = select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > after_id).order_by(JobEvent.id)
            return [JobEventInfo(id=e.id, job_id=e.job_id, type=e.type, payload=dict(e.payload or {}),
                                 created_at=e.created_at) for e in s.scalars(stmt)]

    def stream_events(self, job_id: str, after_id: int = 0, poll_interval: float = 0.5,
                      timeout: Optional[float] = None) -> Iterator[JobEventInfo]:
        """Eventi del job man mano che arrivano (polling sul DB). Si ferma quando il job è
        concluso o in attesa di decisione e non ci sono altri eventi, oppure dopo timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        cursor = after_id
        while True:
            batch = self.events(job_id, cursor)
            for event in batch:
                cursor = event.id
                yield event
            if not batch:
                job = self.get(job_id)
                if job is None or job.state in TERMINAL_STATES or job.state == JobState.WAITING_FOR_DECISION.value:
                    if not self.events(job_id, cursor):
                        return
                    continue
                if deadline is not None and time.monotonic() >= deadline:
                    return
                time.sleep(poll_interval)

    # ------------------------------------------------------------ eventi e progresso

    def add_event(self, job_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None,
                  progress: Optional[Dict[str, Any]] = None) -> bool:
        """Salva un evento (e il progresso). Restituisce True se è stato chiesto
        l'annullamento del job: chi scrive eventi a ogni unità lo scopre subito."""
        with session_scope(self.db) as s:
            s.add(JobEvent(job_id=job_id, type=event_type, payload=json_safe(payload or {})))
            if progress is not None:
                s.execute(update(Job).where(Job.id == job_id).values(progress=json_safe(progress), updated_at=utcnow()))
            return bool(s.scalar(select(Job.cancel_requested).where(Job.id == job_id)))

    # ------------------------------------------------------------ worker

    def requeue_expired(self, now: Optional[datetime] = None) -> List[str]:
        """Job 'running' con lease scaduto (worker morto): tornano in coda, o falliscono se
        hanno esaurito i tentativi. Restituisce gli id toccati."""
        now = now or utcnow()
        touched = []
        with session_scope(self.db) as s:
            stmt = select(Job).where(Job.state == JobState.RUNNING.value, Job.lease_until < now)
            for row in s.scalars(stmt):
                touched.append(row.id)
                previous = row.worker_id
                row.worker_id = None
                row.lease_until = None
                row.active_lesson = None
                if row.cancel_requested:
                    row.state = JobState.CANCELLED.value
                    row.finished_at = now
                    s.add(JobEvent(job_id=row.id, type="job_finished", payload={"state": row.state}))
                elif row.attempts >= row.max_attempts:
                    row.state = JobState.FAILED.value
                    row.finished_at = now
                    row.error = f"Worker interrotto {row.attempts} volte: job abbandonato"
                    s.add(JobEvent(job_id=row.id, type="job_finished", payload={"state": row.state, "error": row.error}))
                else:
                    row.state = JobState.QUEUED.value
                    s.add(JobEvent(job_id=row.id, type="job_requeued",
                                   payload={"reason": "lease_expired", "worker_id": previous}))
        return touched

    def claim(self, worker_id: str, job_types: Optional[Sequence[str]] = None,
              lease_seconds: int = DEFAULT_LEASE_SECONDS, now: Optional[datetime] = None) -> Optional[JobInfo]:
        """Prende il job in coda più vecchio eseguibile (tipo supportato, lezione libera).
        Su SQLite la transazione è BEGIN IMMEDIATE (un solo scrittore: l'UPDATE è
        condizionato di fatto); su Postgres SELECT ... FOR UPDATE SKIP LOCKED. In ogni caso
        il vincolo UNIQUE su active_lesson è l'ultima garanzia."""
        now = now or utcnow()
        self.requeue_expired(now)
        try:
            with session_scope(self.db) as s:
                stmt = select(Job).where(Job.state == JobState.QUEUED.value).order_by(Job.created_at, Job.id).limit(50)
                if job_types:
                    stmt = stmt.where(Job.type.in_(list(job_types)))
                if s.get_bind().dialect.name == "postgresql":
                    stmt = stmt.with_for_update(skip_locked=True)
                busy = set(s.scalars(select(Job.active_lesson).where(Job.active_lesson.is_not(None))))
                for row in s.scalars(stmt).all():
                    if row.lesson_path and row.lesson_path in busy:
                        continue
                    row.state = JobState.RUNNING.value
                    row.worker_id = worker_id
                    row.lease_until = now + timedelta(seconds=lease_seconds)
                    row.attempts += 1
                    row.started_at = row.started_at or now
                    row.active_lesson = row.lesson_path
                    s.add(JobEvent(job_id=row.id, type="job_started",
                                   payload={"worker_id": worker_id, "attempt": row.attempts}))
                    s.flush()
                    return JobInfo.from_row(row)
        except (IntegrityError, OperationalError):
            return None  # un altro worker ha preso la stessa lezione o il DB è occupato: si riprova
        return None

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Heartbeat:
        """Rinnova il lease. lease_kept=False se il job non è più di questo worker."""
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            if row is None or row.state != JobState.RUNNING.value or row.worker_id != worker_id:
                return Heartbeat(lease_kept=False, cancel_requested=bool(row and row.cancel_requested))
            row.lease_until = utcnow() + timedelta(seconds=lease_seconds)
            return Heartbeat(lease_kept=True, cancel_requested=bool(row.cancel_requested))

    def finish(self, job_id: str, worker_id: str, state: Union[JobState, str], *,
               result: Optional[Dict[str, Any]] = None, error: Optional[str] = None,
               decision: Optional[Dict[str, Any]] = None, lesson_path: Optional[str] = None) -> bool:
        """Chiude l'esecuzione (anche in waiting_for_decision). False se il lease era perso."""
        state = JobState(state).value
        now = utcnow()
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            if row is None or row.state != JobState.RUNNING.value or row.worker_id != worker_id:
                return False
            row.state = state
            row.lease_until = None
            row.active_lesson = None
            row.result = json_safe(result) if result is not None else row.result
            row.error = error
            row.decision = json_safe(decision) if decision is not None else None
            if lesson_path:
                row.lesson_path = normalize_lesson_path(lesson_path)
            if state in TERMINAL_STATES:
                row.finished_at = now
            payload: Dict[str, Any] = {"state": state}
            if error:
                payload["error"] = error
            s.add(JobEvent(job_id=job_id, type="job_finished" if state in TERMINAL_STATES else "job_waiting",
                           payload=payload))
            return True

    def release(self, job_id: str, worker_id: str, reason: str) -> bool:
        """Rimette in coda un job preso ma non eseguito (lezione occupata, worker che si
        ferma): non conta come tentativo."""
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            if row is None or row.state != JobState.RUNNING.value or row.worker_id != worker_id:
                return False
            row.state = JobState.QUEUED.value
            row.worker_id = None
            row.lease_until = None
            row.active_lesson = None
            row.attempts = max(0, row.attempts - 1)
            s.add(JobEvent(job_id=job_id, type="job_requeued", payload={"reason": reason, "worker_id": worker_id}))
            return True

    def resume(self, job_id: str, payload_update: Optional[Dict[str, Any]] = None) -> JobInfo:
        """Un job in attesa di decisione torna in coda (la decisione è stata presa)."""
        with session_scope(self.db) as s:
            row = s.get(Job, job_id)
            if row is None:
                raise JobError(f"Job {job_id} inesistente")
            if row.state != JobState.WAITING_FOR_DECISION.value:
                raise JobError(f"Job {job_id} non è in attesa di una decisione (stato: {row.state})")
            if payload_update:
                merged = dict(row.payload or {})
                for key, value in payload_update.items():
                    if isinstance(value, dict) and isinstance(merged.get(key), dict):
                        merged[key] = {**merged[key], **value}
                    else:
                        merged[key] = value
                row.payload = json_safe(merged)
            row.state = JobState.QUEUED.value
            row.decision = None
            row.attempts = 0
            s.add(JobEvent(job_id=job_id, type="job_resumed", payload={}))
            return JobInfo.from_row(row)

    # ------------------------------------------------------------ registro dei worker

    def register_worker(self, worker_id: str, hostname: str, pid: int, platform: str,
                        job_types: Sequence[str]) -> None:
        now = utcnow()
        with session_scope(self.db) as s:
            row = s.get(Worker, worker_id)
            if row is None:
                row = Worker(id=worker_id)
                s.add(row)
            row.hostname, row.pid, row.platform, row.job_types = hostname, pid, platform, list(job_types)
            row.started_at, row.last_seen, row.stopped_at, row.current_job_id = now, now, None, None

    def beat_worker(self, worker_id: str, current_job_id: Optional[str] = None) -> None:
        with session_scope(self.db) as s:
            s.execute(update(Worker).where(Worker.id == worker_id)
                      .values(last_seen=utcnow(), current_job_id=current_job_id))

    def stop_worker(self, worker_id: str) -> None:
        with session_scope(self.db) as s:
            s.execute(update(Worker).where(Worker.id == worker_id)
                      .values(stopped_at=utcnow(), current_job_id=None))

    def live_workers(self, job_type: Optional[str] = None, max_age_seconds: int = WORKER_ALIVE_SECONDS) -> List[Dict[str, Any]]:
        """Worker con battito recente (e che eseguono job_type, se indicato)."""
        cutoff = utcnow() - timedelta(seconds=max_age_seconds)
        with session_scope(self.db) as s:
            rows = s.scalars(select(Worker).where(Worker.stopped_at.is_(None), Worker.last_seen >= cutoff))
            out = [{"id": w.id, "hostname": w.hostname, "pid": w.pid, "platform": w.platform,
                    "job_types": list(w.job_types or []), "current_job_id": w.current_job_id} for w in rows]
        if job_type:
            out = [w for w in out if not w["job_types"] or job_type in w["job_types"]]
        return out


def get_job_queue() -> DbJobQueue:
    """La coda del database di RT (DatabaseUnavailable/RuntimeError se il DB manca)."""
    from rt.db.engine import require_database
    return DbJobQueue(require_database())


def _optional_queue() -> Optional[DbJobQueue]:
    from rt.db.engine import get_database
    db = get_database()
    return DbJobQueue(db) if db is not None else None


def has_live_worker(job_type: Optional[str] = None, same_host: bool = False) -> bool:
    """Vero se c'è un worker vivo per job_type (sulla stessa macchina, se same_host); falso
    anche se il DB non è disponibile (chi chiama esegue allora in processo, come prima)."""
    import socket
    try:
        queue = _optional_queue()
        if queue is None:
            return False
        workers = queue.live_workers(job_type)
    except Exception:
        return False
    if same_host:
        workers = [w for w in workers if w["hostname"] == socket.gethostname()]
    return bool(workers)


class JobFailed(RuntimeError):
    """Il job accodato è fallito o è stato annullato (messaggio = errore del job)."""


def run_job_or_inline(job_type: str, lesson_id: LessonRef, payload: Dict[str, Any], inline,
                      *, created_by: Optional[str] = None, same_host: bool = False,
                      pickup_timeout: float = 30.0, poll_interval: float = 0.5) -> Dict[str, Any]:
    """Esegue un lavoro lungo tramite la coda se c'è un worker vivo, altrimenti in processo
    chiamando inline() (comportamento di prima della fase D). Bloccante: chi è in un event
    loop (daemon Telegram) la chiama in un executor. Se nessun worker prende il job entro
    pickup_timeout secondi (worker appena morto) il job viene annullato e si esegue inline.
    Restituisce il risultato del job (o {"inline": valore} quando esegue in processo)."""
    queue = _optional_queue() if has_live_worker(job_type, same_host=same_host) else None
    if queue is None:
        return {"inline": inline()}
    job_id = queue.enqueue(job_type, lesson_id, payload, created_by=created_by)
    started = time.monotonic()
    while True:
        job = queue.get(job_id)
        if job is None:
            raise JobFailed(f"Job {job_id} scomparso")
        if job.state == JobState.SUCCEEDED.value:
            return job.result or {}
        if job.state in (JobState.FAILED.value, JobState.CANCELLED.value):
            raise JobFailed(job.error or f"Job {job.state}")
        if job.state == JobState.WAITING_FOR_DECISION.value:
            return job.result or {}
        if job.state == JobState.QUEUED.value and time.monotonic() - started > pickup_timeout:
            if queue.cancel(job_id).state == JobState.CANCELLED.value:
                return {"inline": inline()}
        time.sleep(poll_interval)


def resume_waiting_jobs(lesson_dir: str, kind: str, condition=None) -> List[str]:
    """Rimette in coda i job della lezione fermi sulla decisione 'kind' (la decisione è stata
    presa: outline approvata, review completata); condition(), se data, viene valutata solo
    quando ci sono job in attesa (es. "tutte le issue decise"). Mai bloccante: senza DB o con errori non fa
    nulla. Restituisce gli id ripresi."""
    import logging
    try:
        queue = _optional_queue()
        if queue is None:
            return []
        waiting = [job for job in queue.list(state=JobState.WAITING_FOR_DECISION.value, lesson_id=lesson_dir, limit=100)
                   if (job.decision or {}).get("kind") == kind]
        if not waiting or (condition is not None and not condition()):
            return []
        resumed = []
        for job in waiting:
            queue.resume(job.id)
            resumed.append(job.id)
        return resumed
    except Exception as exc:
        logging.getLogger(__name__).warning("Ripresa dei job in attesa non riuscita: %s", exc)
        return []
