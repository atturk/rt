"""Archivio delle fonti, autenticato come gli altri dati della lezione."""
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.routers.images import EditorImage
from rt.core.sources import Source
from rt.services import archive_service

router = APIRouter(tags=['archivio'])


class LookupRequest(BaseModel):
    sha: list[str] = Field(max_length=100)


class ArchiveUsage(BaseModel):
    lezione_id: int | None
    titolo: str
    data: str
    pagine: list[int] | None
    materia: str


class LookupEntry(BaseModel):
    impronta: str
    pagine_totali: int | None
    usate: list[ArchiveUsage]
    da_continuare: str | None


@router.post('/archive/lookup', response_model=dict[str, LookupEntry | None])
def lookup(body: LookupRequest, _actor: Actor):
    try:
        return archive_service.lookup(body.sha)
    except ValueError:
        from rt.api.errors import ApiError
        raise ApiError(422, 'validation_error', 'Impronta non valida.') from None


class ArchiveRow(BaseModel):
    impronta: str
    nome: str
    tipo: str
    pagine_totali: int | None
    durata_s: float | None
    dimensione: int
    materie: list[str]
    usi: int
    da_continuare: str | None


class ArchivePage(BaseModel):
    numero: int
    ignorata: bool
    lezione_id: int | None


class ArchiveLesson(BaseModel):
    id: int | None
    titolo: str
    data: str
    pagine: list[int] | None


class ArchiveDetail(ArchiveRow):
    pagine: list[ArchivePage]
    lezioni: list[ArchiveLesson]
    trascrizione_inizio: str


class ArchiveSummary(BaseModel):
    file: int
    da_continuare: int


class PagesRequest(BaseModel):
    pagine: list[int] = Field(min_length=1, max_length=100000)


class IgnoreRequest(PagesRequest):
    ignorata: bool


class CropRequest(BaseModel):
    rect: list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]] = Field(min_length=4, max_length=4)
    sostituisci: bool = False


class AddToLessonRequest(BaseModel):
    lesson_id: int
    uso: Literal['guida', 'contesto', 'integra'] = 'contesto'
    pagine: list[int] | None = None
    estrai: Literal['testo', 'immagini'] = 'immagini'


class AddToMediaRequest(PagesRequest):
    lesson_id: int


# Le rotte statiche precedono quella con l'impronta.
@router.get('/archive', response_model=list[ArchiveRow])
def list_archive(_actor: Actor, materia: str | None = None, tipo: str | None = None, q: str | None = None):
    return archive_service.list_entries(materia, tipo, q)


@router.get('/archive/summary', response_model=ArchiveSummary)
def summary(_actor: Actor, materia: str | None = None):
    return archive_service.summary(materia=materia)


@router.get('/archive/{sha}', response_model=ArchiveDetail)
def detail(sha: str, _actor: Actor):
    return archive_service.detail(sha)


@router.get('/archive/{sha}/pages/{n}.png', response_class=Response, responses={200: {'content': {'image/png': {}}}})
def page_image(sha: str, n: int, _actor: Actor):
    return Response(archive_service.page_bytes(sha, n), media_type='image/png',
        headers={'Cache-Control': 'private, no-cache', 'X-Content-Type-Options': 'nosniff'})


@router.put('/archive/{sha}/ignored', response_model=ArchiveDetail)
def ignored(sha: str, body: IgnoreRequest, _actor: Actor):
    return archive_service.set_ignored(sha, body.pagine, body.ignorata)


@router.post('/archive/{sha}/pages/delete', response_model=ArchiveDetail)
def delete_pages(sha: str, body: PagesRequest, _actor: Actor):
    return archive_service.delete_pages(sha, body.pagine)


@router.post('/archive/{sha}/pages/{n}/crop', response_model=ArchiveRow)
def crop(sha: str, n: int, body: CropRequest, _actor: Actor):
    return archive_service.crop(sha, n, body.rect, body.sostituisci)


@router.delete('/archive/{sha}', status_code=204)
def delete_entry(sha: str, _actor: Actor):
    archive_service.delete_entry(sha)


@router.post('/archive/{sha}/add-to-lesson', response_model=Source, status_code=201)
def add_to_lesson(sha: str, body: AddToLessonRequest, _actor: Actor):
    return archive_service.add_to_lesson(sha, body.lesson_id, body.uso, body.pagine, body.estrai)


@router.post('/archive/{sha}/add-to-media', response_model=list[EditorImage], status_code=201)
def add_to_media(sha: str, body: AddToMediaRequest, _actor: Actor):
    return archive_service.add_to_media(sha, body.lesson_id, body.pagine)
