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

from rt.services.sources_view import SourceView, LastUpdate, sources_view

router = APIRouter(tags=["lezioni"])


class SourcesView(BaseModel):
    sources: list[SourceView]
    has_unused_sources: bool
    can_undo: bool
    ultimo_aggiornamento: LastUpdate | None = None
    principale: str
    ordine_usato: list[str]
    principale_usato: str | None
    solo_ricostruzione: bool


class UpdateRequest(BaseModel):
    mode: Literal["extend", "rebuild"] = "extend"
    mock: bool = False


class UndoUpdateResult(BaseModel):
    status: Literal["update_undone"]


@contextmanager
def source_mutation(lesson_id, lesson_dir, *, allow_documents=True):
    from rt.core.process_lock import lesson_work_lock, LessonBusy
    from rt.services.document_edit_lease import assert_editable
    try:
        with lesson_work_lock(lesson_dir):
            assert_editable(lesson_id)
            busy = [job for job in queue().list(state=["queued", "running", "waiting_for_decision"],
                                               lesson_id=lesson_dir)
                    if job.type != "documents" or not allow_documents]
            if busy:
                raise ApiError(409, "lesson_busy", "La lezione ha un lavoro attivo o in attesa.")
            yield
    except LessonBusy:
        raise ApiError(409, "lesson_busy", "La lezione è in lavorazione.") from None


@router.get("/lessons/{lesson_id}/sources", response_model=SourcesView,
            summary="Fonti della lezione e stato delle fonti non ancora usate")
def get_sources(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return sources_view(lesson_dir)


@router.post("/lessons/{lesson_id}/sources", response_model=Source | list[Source], status_code=201,
             summary="Aggiunge audio, appunti o materiali senza aggiornare la lezione")
def post_source(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                tipo: Literal["audio", "appunti", "materiale"] = Form(...),
                file: Optional[list[UploadFile]] = File(None), testo: Optional[str] = Form(None),
                ordine: Optional[int] = Form(None, ge=1)):
    from rt.api.routers.jobs import _max_upload_bytes, _save_uploads, _upload_dir
    from rt.pipeline.setup import SUPPORTED_AUDIO_EXTENSIONS
    import os
    import shutil
    if tipo == "materiale":
        from rt.core.materials import MATERIAL_EXTENSIONS, page_count
        if not file or testo is not None:
            raise ApiError(422, "validation_error", "Carica almeno un materiale.")
        target = _upload_dir()
        try:
            saved = _save_uploads(file, MATERIAL_EXTENSIONS, target)
            for path in saved:
                try:
                    page_count(path)
                except Exception:
                    raise ApiError(422, "validation_error", "Materiale non leggibile.") from None
            with source_mutation(lesson_id, lesson_dir):
                return [add_source(lesson_dir, tipo, os.path.basename(path), None,
                                   None if ordine is None else ordine + i, source_path=path)
                        for i, path in enumerate(saved)]
        finally:
            shutil.rmtree(target, ignore_errors=True)
    if tipo == "audio":
        if not file or len(file) != 1 or testo is not None:
            raise ApiError(422, "validation_error", "Carica un file audio.")
        # A blocchi su disco con limite, come l'import: mai l'intero file in memoria.
        target = _upload_dir()
        try:
            saved = _save_uploads(file, SUPPORTED_AUDIO_EXTENSIONS, target)[0]
            return _add_source(lesson_id, lesson_dir, tipo, os.path.basename(saved), None, ordine, saved)
        finally:
            shutil.rmtree(target, ignore_errors=True)
    if testo is None or file is not None or not testo.strip():
        raise ApiError(422, "validation_error", "Inserisci il testo degli appunti.")
    content = testo.encode("utf-8")
    if len(content) > _max_upload_bytes():
        raise ApiError(413, "payload_too_large", "La fonte supera la dimensione massima.")
    return _add_source(lesson_id, lesson_dir, tipo, "appunti.txt", content, ordine)


def _add_source(lesson_id, lesson_dir, tipo, filename, content, ordine, source_path=None):
    with source_mutation(lesson_id, lesson_dir):
        try:
            return add_source(lesson_dir, tipo, filename, content, ordine, source_path=source_path)
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
        from rt.core.source_selection import selection
        if body.mode == "extend" and selection(lesson_dir)["solo_ricostruzione"]:
            raise ApiError(409, "rebuild_required", "Ordine o principale cambiati: usa Ricostruisci.")
        return enqueue_job("update_lesson", lesson_dir, body.model_dump(), actor)


@router.post("/lessons/{lesson_id}/update/undo", response_model=UndoUpdateResult,
             summary="Annulla l'ultimo aggiornamento")
def undo_lesson_update(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    # Annulla riscrive anche i documenti: nemmeno un job documents può essere in corso.
    with source_mutation(lesson_id, lesson_dir, allow_documents=False):
        try:
            return undo_update(lesson_dir)
        except ValueError as exc:
            raise ApiError(409, "update_snapshot_missing", str(exc)) from None


class LessonVersion(BaseModel):
    id: str
    il: str
    modo: Literal["import", "extend", "rebuild", "restore"]
    fonti_aggiunte: list[str]
    unita_nuove: int
    unita_cambiate: int
    attuale: bool


@router.get("/lessons/{lesson_id}/versions", response_model=list[LessonVersion])
def get_versions(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.core.update_history import list_versions
    return list_versions(lesson_dir)


@router.post("/lessons/{lesson_id}/versions/{vid}/restore",
             response_model=schemas.JobAccepted, status_code=202)
def post_restore_version(lesson_id: int, vid: str, lesson_dir: LessonDir, actor: Actor):
    from rt.core.update_history import list_versions
    with source_mutation(lesson_id, lesson_dir, allow_documents=False):
        if not any(v["id"] == vid for v in list_versions(lesson_dir)):
            raise ApiError(404, "version_not_found", "Versione non trovata.")
        return enqueue_job("restore_version", lesson_dir, {"version": vid}, actor)


class SourceOrder(BaseModel):
    ids: list[str]


class SourcePrimary(BaseModel):
    id: str


@router.put("/lessons/{lesson_id}/sources/order", response_model=SourcesView)
def put_source_order(lesson_id: int, body: SourceOrder, lesson_dir: LessonDir, _actor: Actor):
    from rt.core.source_selection import set_order
    with source_mutation(lesson_id, lesson_dir):
        try:
            set_order(lesson_dir, body.ids)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None
        return sources_view(lesson_dir)


@router.put("/lessons/{lesson_id}/sources/primary", response_model=SourcesView)
def put_source_primary(lesson_id: int, body: SourcePrimary, lesson_dir: LessonDir, _actor: Actor):
    from rt.core.source_selection import set_primary
    with source_mutation(lesson_id, lesson_dir):
        try:
            set_primary(lesson_dir, body.id)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None
        return sources_view(lesson_dir)
