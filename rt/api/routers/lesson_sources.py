"""Fonti immutabili e aggiornamenti espliciti delle lezioni."""
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api import schemas
from rt.api.jobs import enqueue_job, queue
from rt.core.sources import Source, load_sources, add_source, remove_source
from rt.core.update_history import has_update_snapshot, undo_update
from rt.pipeline.source_update import sources_pending

router = APIRouter(tags=["lezioni"])


class SourcesView(BaseModel):
    sources: list[Source]
    has_unused_sources: bool
    can_undo: bool


class UpdateRequest(BaseModel):
    mode: Literal["extend", "rebuild"] = "extend"
    mock: bool = False


class UndoUpdateResult(BaseModel):
    status: Literal["update_undone"]


@contextmanager
def source_mutation(lesson_id, lesson_dir):
    from rt.core.process_lock import lesson_work_lock, LessonBusy
    from rt.services.document_edit_lease import assert_editable
    try:
        with lesson_work_lock(lesson_dir):
            assert_editable(lesson_id)
            busy = [job for job in queue().list(state=["queued", "running", "waiting_for_decision"],
                                               lesson_id=lesson_dir) if job.type != "documents"]
            if busy:
                raise ApiError(409, "lesson_busy", "La lezione ha un lavoro attivo o in attesa.")
            yield
    except LessonBusy:
        raise ApiError(409, "lesson_busy", "La lezione è in lavorazione.") from None


@router.get("/lessons/{lesson_id}/sources", response_model=SourcesView,
            summary="Fonti della lezione e stato delle fonti non ancora usate")
def get_sources(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return {"sources": load_sources(lesson_dir), "has_unused_sources": sources_pending(lesson_dir),
            "can_undo": has_update_snapshot(lesson_dir)}


@router.post("/lessons/{lesson_id}/sources", response_model=Source, status_code=201,
             summary="Aggiunge audio o appunti senza aggiornare la lezione")
def post_source(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                tipo: Literal["audio", "appunti"] = Form(...),
                file: Optional[UploadFile] = File(None), testo: Optional[str] = Form(None),
                ordine: Optional[int] = Form(None, ge=1)):
    from rt.api.routers.jobs import _max_upload_bytes
    from rt.pipeline.setup import SUPPORTED_AUDIO_EXTENSIONS
    import os
    if tipo == "audio":
        if file is None or testo is not None:
            raise ApiError(422, "validation_error", "Carica un file audio.")
        filename = file.filename or ""
        if os.path.splitext(filename)[1].lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ApiError(415, "unsupported_media_type", "Formato audio non supportato.")
        content = file.file.read(_max_upload_bytes() + 1)
    else:
        if testo is None or file is not None or not testo.strip():
            raise ApiError(422, "validation_error", "Inserisci il testo degli appunti.")
        filename, content = "appunti.txt", testo.encode("utf-8")
    if len(content) > _max_upload_bytes():
        raise ApiError(413, "payload_too_large", "La fonte supera la dimensione massima.")
    if not content:
        raise ApiError(422, "validation_error", "La fonte è vuota.")
    with source_mutation(lesson_id, lesson_dir):
        try:
            return add_source(lesson_dir, tipo, filename, content, ordine)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None


@router.delete("/lessons/{lesson_id}/sources/{sid}", status_code=204,
               summary="Toglie una fonte dall'elenco; la lezione cambia solo con Aggiorna")
def delete_source(lesson_id: int, sid: str, lesson_dir: LessonDir, _actor: Actor):
    with source_mutation(lesson_id, lesson_dir):
        try:
            remove_source(lesson_dir, sid)
        except KeyError:
            raise ApiError(404, "source_not_found", "Fonte non trovata.") from None


@router.post("/lessons/{lesson_id}/update", response_model=schemas.JobAccepted, status_code=202,
             summary="Aggiorna la lezione con Estendi o Ricostruisci")
def update_lesson(lesson_id: int, body: UpdateRequest, lesson_dir: LessonDir, actor: Actor):
    with source_mutation(lesson_id, lesson_dir):
        if not load_sources(lesson_dir):
            raise ApiError(422, "sources_empty", "Aggiungi almeno una fonte prima di aggiornare.")
        return enqueue_job("update_lesson", lesson_dir, body.model_dump(), actor)


@router.post("/lessons/{lesson_id}/update/undo", response_model=UndoUpdateResult,
             summary="Annulla l'ultimo aggiornamento")
def undo_lesson_update(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    with source_mutation(lesson_id, lesson_dir):
        try:
            return undo_update(lesson_dir)
        except ValueError as exc:
            raise ApiError(409, "update_snapshot_missing", str(exc)) from None
