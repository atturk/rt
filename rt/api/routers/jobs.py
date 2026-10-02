"""Job: importazione audio, pipeline e fasi, immagini, prova credenziali; stato, annullamento
ed eventi live (Server-Sent Events). I job li esegue 'rt worker'."""
import asyncio
import json
import os
import shutil
import time
import uuid
from typing import AsyncIterator, Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job, job_accepted, job_view, queue
from rt.storage import fs

router = APIRouter(tags=["job"])


@router.get("/uploads", response_model=List[schemas.UploadInventoryItem], summary="Upload temporanei attivi, riferiti e orfani")
def get_uploads(_actor: Actor):
    from rt.services.upload_cleanup import list_uploads
    return list_uploads()


@router.delete("/uploads/{upload_id}", status_code=204, summary="Elimina un upload non più in uso dopo conferma esplicita")
def delete_orphan_upload(upload_id: str, _actor: Actor, include_referenced: bool = False):
    from rt.services.upload_cleanup import delete_orphan
    delete_orphan(upload_id, include_referenced=include_referenced)

MAX_UPLOAD_ENV = "RT_API_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 2048
CHUNK = 1024 * 1024
IMAGE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}
SSE_KEEPALIVE_SECONDS = 15.0
SSE_POLL_SECONDS = 0.5
# Lo stream di tutti i job (GET /events) si chiude dopo questo tempo e il browser lo riapre
# da solo con Last-Event-ID, senza perdere eventi: nessuna connessione resta aperta per sempre.
SSE_APP_STREAM_SECONDS = 300.0


def _max_upload_bytes() -> int:
    try:
        return int(float(os.environ.get(MAX_UPLOAD_ENV, DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024)
    except ValueError:
        return DEFAULT_MAX_UPLOAD_MB * 1024 * 1024


def _upload_dir() -> str:
    """Cartella temporanea per i file caricati, sullo stesso disco dei media delle lezioni."""
    from rt.services.lesson_service import work_dir
    path = os.path.join(work_dir(), "uploads", uuid.uuid4().hex)
    os.makedirs(path, mode=0o700)
    return path


def _save_uploads(files: List[UploadFile], allowed: set, target: str, prefix: str = "") -> List[str]:
    """Salva i file a blocchi con limite di dimensione complessiva; solo estensioni ammesse,
    solo il nome base (nessun percorso dal client). prefix distingue file omonimi salvati con
    chiamate diverse nella stessa cartella."""
    limit, total, saved = _max_upload_bytes(), 0, []
    seen = set()
    for upload in files:
        name = os.path.basename((upload.filename or "").replace("\\", "/")).strip()
        if not name or name.startswith(".") or os.path.splitext(name)[1].lower() not in allowed:
            raise ApiError(415, "unsupported_media_type", f"Tipo di file non ammesso: {name or '(senza nome)'}.")
        if name.casefold() in seen:
            raise ApiError(422, "duplicate_filename", f"Due file hanno lo stesso nome: {name}. Rinomina uno dei file prima di importare.")
        seen.add(name.casefold())
        path = os.path.join(target, prefix + name)
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

MAX_ZIP_ARCHIVES = 20
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")


def _zip_signature_ok(path: str) -> bool:
    with open(path, "rb") as stream:
        return stream.read(4) in ZIP_SIGNATURES


@router.post("/lessons/import-zip", response_model=schemas.JobAccepted, status_code=202,
             summary="Importa più archivi completi come nuove lezioni (job import_lesson_zips)")
def import_lesson_zips(actor: Actor, archives: List[UploadFile] = File(...)):
    """Salva gli archivi e accoda il job: estrazione e controlli completi li fa 'rt worker'.
    Qui solo i controlli immediati (nome, dimensione, firma ZIP): un archivio che non li
    supera finisce tra i rifiutati del risultato senza fermare gli altri."""
    if len(archives) > MAX_ZIP_ARCHIVES:
        raise ApiError(413, "too_many_archives", f"Importa al massimo {MAX_ZIP_ARCHIVES} archivi alla volta.")
    target = _upload_dir()

    def _go():
        entries = []
        for index, archive in enumerate(archives):
            filename = os.path.basename((archive.filename or "").replace("\\", "/"))
            entry = {"file": filename, "path": None, "reason": None}
            entries.append(entry)
            if not filename.lower().endswith(".zip"):
                entry["reason"] = "Serve un archivio ZIP."
                continue
            try:
                # Ogni archivio è indipendente (limite di dimensione compreso): il prefisso
                # evita che due archivi con lo stesso nome si sovrascrivano.
                path = _save_uploads([archive], {".zip"}, target, prefix=f"{index:02d}-")[0]
            except ApiError as exc:
                entry["reason"] = exc.message
                _remove_partial(os.path.join(target, f"{index:02d}-{filename.strip()}"))
                continue
            if not _zip_signature_ok(path):
                entry["reason"] = "Archivio ZIP non valido."
                os.unlink(path)
                continue
            entry["path"] = path
        if not any(entry["path"] for entry in entries):
            reasons = "; ".join(f"{e['file'] or '(senza nome)'}: {e['reason']}" for e in entries)
            raise ApiError(422, "invalid_archive", f"Nessun archivio valido da importare ({reasons})",
                           {"results": [{"file": e["file"], "status": "rejected", "reason": e["reason"]} for e in entries]})
        return enqueue_job("import_lesson_zips", None, {"archives": entries, "upload_dir": target}, actor)
    return _with_upload_cleanup(target, _go)


def _remove_partial(path: str) -> None:
    if os.path.isfile(path):
        os.unlink(path)


@router.post("/lessons", response_model=schemas.JobAccepted, status_code=202,
             summary="Importa una lezione da audio (upload): job ingest_audio, o run_pipeline con run=true")
def create_lesson(
    actor: Actor,
    audio: List[UploadFile] = File(..., description="Uno o più file audio della stessa lezione"),
    date: str = Form(..., description="Data della lezione (YYYY-MM-DD o formati accettati da 'rt setup')"),
    materia: str = Form(...),
    argomenti: str = Form(""),
    docente: str = Form("", description="Nome del docente (facoltativo)"),
    run: bool = Form(False, description="True: esegue tutta la pipeline dopo l'importazione (come 'rt run audio')"),
    mock: bool = Form(False),
    with_review: bool = Form(False),
    auto_accept: bool = Form(False),
):
    from rt.pipeline.setup import SUPPORTED_AUDIO_EXTENSIONS
    from rt.services.lesson_service import lessons_root
    target = _upload_dir()

    def _go():
        paths = _save_uploads(audio, SUPPORTED_AUDIO_EXTENSIONS, target)
        options = {"date": date, "materia": materia, "argomenti": argomenti or None, "docente": docente.strip() or None,
                   "dest_dir": lessons_root(),
                   "mock": mock, "with_review": with_review, "auto_accept": auto_accept, "channel": "terminal"}
        # run=true: tutta la pipeline dall'audio (come 'rt run audio'); altrimenti solo setup
        return enqueue_job("run_pipeline" if run else "ingest_audio", None,
                           {"inputs": paths, "options": options, "upload_dir": target}, actor)
    return _with_upload_cleanup(target, _go)


@router.post("/lessons/{lesson_id}/jobs", response_model=schemas.JobAccepted, status_code=202,
             summary="Avvia la pipeline o una fase sulla lezione (come 'rt run' o 'rt <fase>')")
def start_job(lesson_id: int, body: schemas.JobRequest, lesson_dir: LessonDir, actor: Actor):
    if body.mock_fail_once and not body.mock:
        raise ApiError(422, "validation_error", "mock_fail_once vale solo in modalità prova (mock).")
    if body.extra_prompt is not None and (body.type != "run_phase" or body.phase not in ("outline", "rewrite", "review")):
        raise ApiError(422, "validation_error", "Le istruzioni aggiuntive sono disponibili solo per outline, rewrite e review.")
    extra = {"mock_fail_once": body.mock_fail_once} if body.mock_fail_once else {}
    if body.type == "run_phase":
        if not body.phase:
            raise ApiError(422, "validation_error", "Indica la fase da eseguire.")
        options = {"force": body.force, "mock": body.mock, "rename": body.rename}
        prompt_payload = {"extra_prompt": body.extra_prompt} if body.extra_prompt is not None else {}
        if body.unit or body.units:
            if body.phase not in ("rewrite", "review"):
                raise ApiError(422, "validation_error", "L'unità si indica solo per rewrite o review.")
            units = list(dict.fromkeys(body.units or [body.unit]))
            if not units or any(not unit or not unit.strip() for unit in units):
                raise ApiError(422, "validation_error", "Seleziona unità valide.")
            return enqueue_job("rewrite_unit" if body.phase == "rewrite" else "review_unit", lesson_dir,
                               {"units": units, "options": options, **prompt_payload}, actor)
        return enqueue_job("run_phase", lesson_dir, {"phase": body.phase, "options": options, **extra, **prompt_payload}, actor)
    options = {"force": body.force, "mock": body.mock, "with_review": body.with_review,
               "auto_accept": body.auto_accept, "rename": body.rename, "channel": "terminal"}
    return enqueue_job("run_pipeline", lesson_dir, {"inputs": [lesson_dir], "options": options, **extra}, actor)


@router.post("/lessons/{lesson_id}/images", response_model=schemas.JobAccepted, status_code=202,
             summary="Integra slide/foto caricate e/o immagini dal web (come 'rt add-images')")
def add_images(
    lesson_id: int, lesson_dir: LessonDir, actor: Actor,
    files: Optional[List[UploadFile]] = File(None, description="PDF o immagini"),
    web_search: Optional[int] = Form(None, ge=1, le=10, description="Immagini da cercare sul web per ogni unità"),
    units: Optional[List[str]] = Form(None, description="Unità per cui cercare sul web (id dell'outline); vuoto = tutte"),
    mock: bool = Form(False),
):
    from rt.services.images_service import ImagesError, check_web_search
    if not files and not web_search:
        raise ApiError(422, "validation_error", "Carica almeno un file o chiedi una ricerca web.")
    unit_ids = [u.strip() for u in units or [] if u.strip()] or None
    if web_search:
        try:
            check_web_search(lesson_dir, unit_ids, mock=mock)
        except ImagesError as exc:
            raise ApiError(exc.status, exc.code, str(exc))
    target = _upload_dir() if files else None

    def _go():
        input_path = None
        if files:
            saved = _save_uploads(files, IMAGE_SUFFIXES, target)
            # un PDF da solo si passa com'è; le immagini come cartella (come 'rt add-images -i')
            single_pdf = len(saved) == 1 and saved[0].lower().endswith(".pdf")
            input_path = saved[0] if single_pdf else target
        payload = {"input_path": input_path, "web_search_count": web_search, "unit_ids": unit_ids if web_search else None,
                   "mock": mock, "upload_dir": target}
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
    return enqueue_job("telegram_listen_topics", None, {"seconds": 20,
                         "existing_daemon": is_daemon_running()}, actor)


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


@router.post("/jobs/{job_id}/close", response_model=schemas.Job,
             summary="Chiude un job in attesa di una decisione senza annullarlo (come 'rt jobs close')",
             description="Il job finisce (succeeded, result.closed con il messaggio); le issue restano da "
                         "valutare in Revisione o la scaletta da approvare, e decidere dopo non fa ripartire "
                         "la pipeline. 409 job_not_closable se il job non è in attesa di una decisione "
                         "che abbia una sua schermata.")
def close_job(job_id: str, _actor: Actor):
    from rt.services.jobs import JobError
    _get(job_id)
    try:
        return job_view(queue().close_waiting(job_id))
    except JobError as exc:
        raise ApiError(409, "job_not_closable", str(exc))


@router.post("/jobs/{job_id}/retry", response_model=schemas.JobAccepted, status_code=202,
             summary="Riprova un job fallito: job nuovo con lo stesso tipo e payload (retry_of), che riparte dalla fase fallita")
def retry_job(job_id: str, actor: Actor):
    from rt.services.jobs import JobAlreadyRetried, JobError, LessonHasActiveJob
    info = _get(job_id)
    if info.state == "failed" and not (info.lesson_path and fs.isdir(info.lesson_path)):
        # Nessuna lezione ancora creata (es. fallito durante l'importazione): servono i file caricati
        inputs = [p for p in (info.payload.get("inputs") or []) if isinstance(p, str)]
        if inputs and not all(os.path.exists(p) for p in inputs):
            raise ApiError(409, "retry_unavailable", "I file caricati non ci sono più: importa di nuovo la lezione.")
    try:
        new_id = queue().retry(job_id, created_by=actor)
    except LessonHasActiveJob as exc:
        raise ApiError(409, "lesson_busy", str(exc), {"job_id": exc.job_id})
    except JobAlreadyRetried as exc:
        raise ApiError(409, "already_retried", str(exc), {"job_id": exc.job_id})
    except JobError as exc:
        raise ApiError(409, "job_not_retryable", str(exc))
    return job_accepted(new_id)


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


def _app_events(after: int, lessons: Dict[str, Optional[int]]) -> List[Tuple[int, str]]:
    """Blocchi SSE degli eventi di tutti i job dopo after. Solo chi e cosa (job, tipo del job,
    lezione, tipo dell'evento): la web app rilegge dall'API le query interessate."""
    from rt.services.lesson_service import lesson_id_for_dir
    blocks = []
    for event, job_type, lesson_path in queue().events_since(after):
        # in cache solo se trovata: un'importazione crea la cartella della lezione a metà job
        if lessons.get(event.job_id) is None:
            lessons[event.job_id] = lesson_id_for_dir(lesson_path) if lesson_path and fs.isdir(lesson_path) else None
        data = json.dumps({"id": event.id, "job_id": event.job_id, "job_type": job_type,
                           "lesson_id": lessons[event.job_id], "type": event.type})
        blocks.append((event.id, f"id: {event.id}\nevent: job\ndata: {data}\n\n"))
    return blocks


async def app_sse_stream(after: int, keepalive: float = SSE_KEEPALIVE_SECONDS, poll: float = SSE_POLL_SECONDS,
                         lifetime: Optional[float] = None) -> AsyncIterator[str]:
    """Eventi di tutti i job dopo after come SSE (evento 'job'), per il canale live della web
    app. L'id di partenza va subito al browser, così una riconnessione (Last-Event-ID) riprende
    senza buchi. Asincrono: mentre aspetta non tiene un thread."""
    lifetime = SSE_APP_STREAM_SECONDS if lifetime is None else lifetime
    cursor = after
    lessons: Dict[str, Optional[int]] = {}
    yield f"retry: 3000\nid: {cursor}\n\n"
    start = last_sent = time.monotonic()
    while time.monotonic() - start < lifetime:
        blocks = await run_in_threadpool(_app_events, cursor, lessons)
        for cursor, block in blocks:
            yield block
        now = time.monotonic()
        if blocks:
            last_sent = now
            continue
        if now - last_sent >= keepalive:
            yield ": keepalive\n\n"
            last_sent = now
        await asyncio.sleep(poll)


@router.get("/events", summary="Eventi live di tutti i job (Server-Sent Events per la web app; riprende da Last-Event-ID)",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
async def stream_app_events(_actor: Actor,
                            after: Optional[int] = Query(None, ge=0, description="Id dell'ultimo evento già ricevuto (senza: da adesso)"),
                            last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")):
    start = after
    if last_event_id and last_event_id.strip().isdigit():
        start = max(start or 0, int(last_event_id.strip()))
    if start is None:
        # Il punto di partenza si fissa prima di rispondere: quello che la pagina rilegge
        # all'apertura dello stream (onopen) è già successivo, quindi niente buchi.
        start = await run_in_threadpool(lambda: queue().last_event_id())
    return StreamingResponse(app_sse_stream(start), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/workers", response_model=List[schemas.WorkerInfo], summary="Worker attivi ('rt worker')")
def list_workers(_actor: Actor):
    return queue().live_workers()
