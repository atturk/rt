"""Job: importazione audio, pipeline e fasi, immagini, prova credenziali; stato, annullamento
ed eventi live (Server-Sent Events). I job li esegue 'rt worker'."""
import json
import os
import shutil
import time
import uuid
from typing import Iterator, List, Optional

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job, job_view, queue

router = APIRouter(tags=["job"])

MAX_UPLOAD_ENV = "RT_API_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 2048
CHUNK = 1024 * 1024
IMAGE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}
SSE_KEEPALIVE_SECONDS = 15.0
SSE_POLL_SECONDS = 0.5


def _max_upload_bytes() -> int:
    try:
        return int(float(os.environ.get(MAX_UPLOAD_ENV, DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024)
    except ValueError:
        return DEFAULT_MAX_UPLOAD_MB * 1024 * 1024


def _upload_dir() -> str:
    """Cartella temporanea per i file caricati, sullo stesso disco delle lezioni."""
    from rt.services.lesson_service import lessons_root
    base = lessons_root() or os.path.expanduser("~")
    path = os.path.join(base, ".rt", "uploads", uuid.uuid4().hex)
    os.makedirs(path, mode=0o700)
    return path


def _save_uploads(files: List[UploadFile], allowed: set, target: str) -> List[str]:
    """Salva i file a blocchi con limite di dimensione complessiva; solo estensioni ammesse,
    solo il nome base (nessun percorso dal client)."""
    limit, total, saved = _max_upload_bytes(), 0, []
    for upload in files:
        name = os.path.basename((upload.filename or "").replace("\\", "/")).strip()
        if not name or name.startswith(".") or os.path.splitext(name)[1].lower() not in allowed:
            raise ApiError(415, "unsupported_media_type", f"Tipo di file non ammesso: {name or '(senza nome)'}.")
        path = os.path.join(target, name)
        with open(path, "wb") as out:
            while True:
                chunk = upload.file.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ApiError(413, "payload_too_large", f"File troppo grandi (limite {limit // (1024 * 1024)} MB).")
                out.write(chunk)
        if os.path.getsize(path) == 0:
            raise ApiError(422, "empty_file", f"File vuoto: {name}.")
        saved.append(path)
    return saved


def _with_upload_cleanup(target: str, fn):
    try:
        return fn()
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


# ---------------------------------------------------------------- creazione

@router.post("/lessons", response_model=schemas.JobAccepted, status_code=202,
             summary="Importa una lezione da audio (upload): job ingest_audio, o run_pipeline con run=true")
def create_lesson(
    actor: Actor,
    audio: List[UploadFile] = File(..., description="Uno o più file audio della stessa lezione"),
    date: str = Form(..., description="Data della lezione (YYYY-MM-DD o formati accettati da 'rt setup')"),
    materia: str = Form(...),
    argomenti: str = Form(""),
    run: bool = Form(False, description="True: esegue tutta la pipeline dopo l'importazione (come 'rt run audio')"),
    mock: bool = Form(False),
    with_review: bool = Form(True),
    auto_accept: bool = Form(False),
):
    from rt.pipeline.setup import SUPPORTED_AUDIO_EXTENSIONS
    from rt.services.lesson_service import lessons_root
    target = _upload_dir()

    def _go():
        paths = _save_uploads(audio, SUPPORTED_AUDIO_EXTENSIONS, target)
        options = {"date": date, "materia": materia, "argomenti": argomenti or None, "dest_dir": lessons_root(),
                   "mock": mock, "with_review": with_review, "auto_accept": auto_accept, "channel": "terminal"}
        # run=true: tutta la pipeline dall'audio (come 'rt run audio'); altrimenti solo setup
        return enqueue_job("run_pipeline" if run else "ingest_audio", None,
                           {"inputs": paths, "options": options, "upload_dir": target}, actor)
    return _with_upload_cleanup(target, _go)


@router.post("/lessons/{lesson_id}/jobs", response_model=schemas.JobAccepted, status_code=202,
             summary="Avvia la pipeline o una fase sulla lezione (come 'rt run' o 'rt <fase>')")
def start_job(lesson_id: int, body: schemas.JobRequest, lesson_dir: LessonDir, actor: Actor):
    if body.type == "run_phase":
        if not body.phase:
            raise ApiError(422, "validation_error", "Indica la fase da eseguire.")
        options = {"force": body.force, "mock": body.mock, "rename": body.rename}
        if body.unit:
            if body.phase != "rewrite":
                raise ApiError(422, "validation_error", "L'unità si indica solo per il rewrite.")
            return enqueue_job("rewrite_unit", lesson_dir, {"unit": body.unit, "options": options}, actor)
        return enqueue_job("run_phase", lesson_dir, {"phase": body.phase, "options": options}, actor)
    options = {"force": body.force, "mock": body.mock, "with_review": body.with_review,
               "auto_accept": body.auto_accept, "rename": body.rename, "channel": "terminal"}
    return enqueue_job("run_pipeline", lesson_dir, {"inputs": [lesson_dir], "options": options}, actor)


@router.post("/lessons/{lesson_id}/images", response_model=schemas.JobAccepted, status_code=202,
             summary="Integra slide/foto caricate e/o immagini dal web (come 'rt add-images')")
def add_images(
    lesson_id: int, lesson_dir: LessonDir, actor: Actor,
    files: Optional[List[UploadFile]] = File(None, description="PDF o immagini"),
    web_search: Optional[int] = Form(None, ge=1, le=20, description="Immagini da cercare sul web"),
    carousel: bool = Form(False), mock: bool = Form(False),
):
    if not files and not web_search:
        raise ApiError(422, "validation_error", "Carica almeno un file o chiedi una ricerca web.")
    target = _upload_dir() if files else None

    def _go():
        input_path = None
        if files:
            saved = _save_uploads(files, IMAGE_SUFFIXES, target)
            # un PDF da solo si passa com'è; le immagini come cartella (come 'rt add-images -i')
            single_pdf = len(saved) == 1 and saved[0].lower().endswith(".pdf")
            input_path = saved[0] if single_pdf else target
        payload = {"input_path": input_path, "web_search_count": web_search, "carousel": carousel, "mock": mock,
                   "upload_dir": target}
        return enqueue_job("add_images", lesson_dir, payload, actor)
    return _with_upload_cleanup(target, _go) if target else _go()


@router.post("/settings/test-credential", response_model=schemas.JobAccepted, status_code=202, tags=["impostazioni"],
             summary="Prova una credenziale con una chiamata minima al provider (job; esito sanificato)")
def test_credential(body: schemas.CredentialTest, actor: Actor):
    return enqueue_job("credential_test", None, body.model_dump(), actor)


@router.post("/settings/telegram/listen-topics", response_model=schemas.JobAccepted, status_code=202, tags=["impostazioni"],
             summary="Ascolta per 20 secondi i messaggi al bot e rileva chat e topic del gruppo (job)")
def telegram_listen_topics(actor: Actor):
    from rt.telegram.daemon_status import is_daemon_running
    if is_daemon_running():
        raise ApiError(409, "telegram_daemon_running",
                       "Il bot è già in ascolto: fermalo prima di cercare nuovi topic.")
    return enqueue_job("telegram_listen_topics", None, {"seconds": 20}, actor)


# ---------------------------------------------------------------- consultazione

@router.get("/jobs", response_model=List[schemas.Job], summary="Job recenti")
def list_jobs(_actor: Actor, state: Optional[str] = Query(None), lesson_id: Optional[int] = Query(None),
              limit: int = Query(50, ge=1, le=500)):
    lesson_path = None
    if lesson_id is not None:
        from rt.api.deps import lesson_dir as resolve
        lesson_path = resolve(lesson_id)
    return [job_view(j) for j in queue().list(state=state, lesson_id=lesson_path, limit=limit)]


def _get(job_id: str):
    info = queue().get(job_id)
    if info is None:
        raise ApiError(404, "job_not_found", "Job inesistente.")
    return info


@router.get("/jobs/{job_id}", response_model=schemas.Job, summary="Stato di un job")
def get_job(job_id: str, _actor: Actor):
    return job_view(_get(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=schemas.Job,
             summary="Annulla un job (quello in esecuzione si ferma al prossimo punto sicuro)")
def cancel_job(job_id: str, _actor: Actor):
    _get(job_id)
    return job_view(queue().cancel(job_id))


@router.get("/jobs/{job_id}/events/list", response_model=List[schemas.JobEvent], summary="Eventi di un job (senza streaming)")
def list_events(job_id: str, _actor: Actor, after: int = Query(0, ge=0)):
    _get(job_id)
    return [e.to_dict() for e in queue().events(job_id, after)]


def sse_stream(job_id: str, after: int, request: Optional[Request] = None,
               keepalive: float = SSE_KEEPALIVE_SECONDS, poll: float = SSE_POLL_SECONDS) -> Iterator[str]:
    """Eventi del job come SSE (id = id dell'evento, così Last-Event-ID riprende da lì). Si
    chiude quando il job è concluso o in attesa di decisione e non restano eventi."""
    from rt.services.jobs import JobState, TERMINAL_STATES
    q = queue()
    cursor, last_sent = after, time.monotonic()
    yield "retry: 3000\n\n"
    while True:
        batch = q.events(job_id, cursor)
        for event in batch:
            cursor = event.id
            data = json.dumps(event.to_dict(), ensure_ascii=False)
            yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
            last_sent = time.monotonic()
        if batch:
            continue
        job = q.get(job_id)
        if job is None or job.state in TERMINAL_STATES or job.state == JobState.WAITING_FOR_DECISION.value:
            if not q.events(job_id, cursor):
                yield f"event: end\ndata: {json.dumps({'state': job.state if job else None})}\n\n"
                return
            continue
        if time.monotonic() - last_sent >= keepalive:
            yield ": keepalive\n\n"
            last_sent = time.monotonic()
        time.sleep(poll)


@router.get("/jobs/{job_id}/events", summary="Eventi live del job (Server-Sent Events; riprende da Last-Event-ID)",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
def stream_events(job_id: str, request: Request, _actor: Actor,
                  after: int = Query(0, ge=0, description="Id dell'ultimo evento già ricevuto"),
                  last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")):
    _get(job_id)
    start = after
    if last_event_id and last_event_id.strip().isdigit():
        start = max(start, int(last_event_id.strip()))
    return StreamingResponse(sse_stream(job_id, start, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/workers", response_model=List[schemas.WorkerInfo], summary="Worker attivi ('rt worker')")
def list_workers(_actor: Actor):
    return queue().live_workers()
