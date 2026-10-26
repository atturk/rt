"""Fonti immutabili e aggiornamenti espliciti delle lezioni."""
from rt.services.source_mutation import source_mutation
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, model_validator

from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api import schemas
from rt.api.jobs import enqueue_job, queue
from rt.core.sources import Source, load_sources, add_source, remove_source
from rt.core.update_history import has_update_snapshot, undo_update
from rt.pipeline.source_update import sources_pending, reingest_availability

from rt.services.sources_view import SourceView, LastUpdate, sources_view

router = APIRouter(tags=["lezioni"])


class SourcesView(BaseModel):
    sources: list[SourceView]
    has_unused_sources: bool
    can_undo: bool
    reingest_available: bool
    reingest_reason: str | None = None
    ultimo_aggiornamento: LastUpdate | None = None
    principale: str
    ordine_usato: list[str]
    principale_usato: str | None
    solo_ricostruzione: bool
    fonti_tolte_usate: list[str] = []


class UpdateRequest(BaseModel):
    mode: Literal["extend", "rebuild"] = "extend"
    mock: bool = False
    reingest: bool = False
    with_review: bool = False

    @model_validator(mode="after")
    def validate_reingest_mode(self):
        if self.reingest and self.mode != "rebuild":
            raise ValueError("Per rileggere le fonti usa Ricostruisci.")
        return self


class UndoUpdateResult(BaseModel):
    status: Literal["update_undone"]


@router.get("/lessons/{lesson_id}/sources", response_model=SourcesView,
            summary="Fonti della lezione e stato delle fonti non ancora usate")
def get_sources(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return sources_view(lesson_dir)


@router.post("/lessons/{lesson_id}/sources", response_model=Source | list[Source], status_code=201,
             summary="Aggiunge audio, appunti o materiali senza aggiornare la lezione")
def post_source(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                tipo: Literal["audio", "appunti", "materiale"] = Form(...),
                file: Optional[list[UploadFile]] = File(None), testo: Optional[str] = Form(None),
                ordine: Optional[int] = Form(None, ge=1),
                unisci: bool = Form(True), pagine: Optional[str] = Form(None),
                estrai: Optional[Literal['testo', 'immagini', 'solo_immagini']] = Form(None),
                uso: Optional[Literal['guida', 'contesto', 'integra']] = Form(None)):
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
                    from rt.core.source_options import parse_pages
                    parse_pages(pagine, page_count(path))
                except Exception:
                    raise ApiError(422, "validation_error", "Materiale non leggibile.") from None
            with source_mutation(lesson_id, lesson_dir):
                if ordine is not None and ordine > len(load_sources(lesson_dir)) + 1:
                    raise ApiError(422, "validation_error", "Posizione della fonte non valida.")
                added = [add_source(lesson_dir, tipo, os.path.basename(path), None,
                                    None if ordine is None else ordine + i, source_path=path,
                                    pagine=pagine, estrai=estrai, uso=uso)
                         for i, path in enumerate(saved)]
                return added[0] if len(added) == 1 else added
        finally:
            shutil.rmtree(target, ignore_errors=True)
    if tipo == "audio":
        if not file or len(file) == 0 or testo is not None:
            raise ApiError(422, "validation_error", "Carica almeno un file audio.")
        # A blocchi su disco con limite, come l'import: mai l'intero file in memoria.
        target = _upload_dir()
        try:
            saved = _save_uploads(file, SUPPORTED_AUDIO_EXTENSIONS, target)
            if len(saved) == 1:
                return _add_source(lesson_id, lesson_dir, tipo, os.path.basename(saved[0]), None, ordine, saved[0])
            if unisci:
                from rt.pipeline.setup import merge_audio_for_transcription
                from rt.pipeline.source_update import _duration
                from rt.core.sources import format_source_duration
                parts = []
                for p in saved:
                    dur_s = None
                    try:
                        dur_s = _duration(p)
                    except Exception:
                        pass
                    parts.append({
                        "nome": os.path.basename(p),
                        "durata": format_source_duration(dur_s) if dur_s is not None else None,
                        "durata_s": dur_s,
                    })
                merged_output = os.path.join(target, "audio completo.m4a")
                try:
                    merge_audio_for_transcription(saved, merged_output)
                except Exception as exc:
                    raise ApiError(422, "validation_error", f"Impossibile unire i file audio: {exc}") from None
                return _add_source(lesson_id, lesson_dir, tipo, "audio completo.m4a", None, ordine, merged_output, parti=parts)
            else:
                with source_mutation(lesson_id, lesson_dir):
                    if ordine is not None and ordine > len(load_sources(lesson_dir)) + 1:
                        raise ApiError(422, "validation_error", "Posizione della fonte non valida.")
                    added = [add_source(lesson_dir, tipo, os.path.basename(path), None,
                                        None if ordine is None else ordine + i, source_path=path)
                             for i, path in enumerate(saved)]
                    return added[0] if len(added) == 1 else added
        finally:
            shutil.rmtree(target, ignore_errors=True)
    if testo is None or file is not None or not testo.strip():
        raise ApiError(422, "validation_error", "Inserisci il testo degli appunti.")
    content = testo.encode("utf-8")
    if len(content) > _max_upload_bytes():
        raise ApiError(413, "payload_too_large", "La fonte supera la dimensione massima.")
    return _add_source(lesson_id, lesson_dir, tipo, "appunti.txt", content, ordine)


def _add_source(lesson_id, lesson_dir, tipo, filename, content, ordine, source_path=None, parti=None):
    with source_mutation(lesson_id, lesson_dir):
        try:
            return add_source(lesson_dir, tipo, filename, content, ordine, source_path=source_path, parti=parti)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None


class SourceOptions(BaseModel):
    pagine: str | list[int] | None = None
    estrai: Literal['testo', 'immagini', 'solo_immagini'] | None = None
    uso: Literal['guida', 'contesto', 'integra'] | None = None


@router.patch('/lessons/{lesson_id}/sources/{sid}', response_model=Source)
def patch_source(lesson_id: int, sid: str, body: SourceOptions, lesson_dir: LessonDir, _actor: Actor):
    from rt.core.sources import update_source
    with source_mutation(lesson_id, lesson_dir):
        try:
            return update_source(lesson_dir, sid, **body.model_dump(exclude_unset=True))
        except KeyError:
            raise ApiError(404, 'source_not_found', 'Fonte non trovata.') from None
        except ValueError as exc:
            raise ApiError(422, 'validation_error', str(exc)) from None


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
        if body.reingest:
            available = reingest_availability(lesson_dir)
            if not available["reingest_available"]:
                raise ApiError(409, "reingest_unavailable", available["reingest_reason"])
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


@router.post("/lessons/{lesson_id}/sources/restore-removed", response_model=SourcesView,
             summary="Rimette le fonti tolte già usate nel testo corrente")
def post_restore_removed(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.core.source_selection import restore_removed_used
    with source_mutation(lesson_id, lesson_dir):
        restore_removed_used(lesson_dir)
        return sources_view(lesson_dir)
