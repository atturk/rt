"""Scelta della cartella dati dalla web (RT4-FA6): finestra nativa di Finder su macOS e, in
alternativa, elenco delle sottocartelle della home per il navigatore della SPA. Solo richieste
da loopback: l'API apre finestre e legge il disco di questo computer."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError

router = APIRouter(tags=["sistema"])

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK and not host.startswith("127."):
        raise ApiError(403, "loopback_only", "Disponibile solo dal computer su cui gira RT.")


class ChooseFolderIn(BaseModel):
    start: Optional[str] = Field(None, description="Cartella da cui partire (facoltativa)")


class FolderChoice(BaseModel):
    status: Literal["chosen", "cancelled", "unavailable"] = Field(
        description="unavailable: niente finestra nativa (non macOS), la SPA usa il navigatore")
    path: Optional[str] = Field(None, description="Percorso POSIX assoluto della cartella scelta")


class FolderEntry(BaseModel):
    name: str
    path: str


class FolderListing(BaseModel):
    path: str
    parent: Optional[str] = Field(None, description="Cartella superiore; null nella home")
    home: str
    folders: List[FolderEntry]


@router.post("/system/choose-folder", response_model=FolderChoice,
             summary="Apre la finestra di Finder per scegliere una cartella (solo macOS e loopback)")
def choose_folder(body: ChooseFolderIn, request: Request, _actor: Actor):
    from rt.services.folder_picker import choose_folder as choose
    _require_loopback(request)
    return choose(body.start)


@router.get("/system/folders", response_model=FolderListing,
            summary="Sottocartelle di una cartella della home, per il navigatore della SPA (solo loopback)")
def list_folders(request: Request, _actor: Actor, path: Optional[str] = Query(None)):
    from rt.services.folder_picker import FolderAccessError, list_folders as listing
    _require_loopback(request)
    try:
        return listing(path)
    except FolderAccessError as exc:
        raise ApiError(403, "folder_not_allowed", str(exc))
