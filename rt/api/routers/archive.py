"""Archivio delle fonti, autenticato come gli altri dati della lezione."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from rt.api.deps import Actor
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
