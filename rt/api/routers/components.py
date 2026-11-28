"""Stato e gestione dei componenti scaricabili di RT (modello STT e browser per le catture)."""
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError, ErrorResponse
from rt.core import components

router = APIRouter(tags=["componenti"])


class ComponentStatus(BaseModel):
    id: Literal["transcription", "macparakeet", "browser"]
    name: str
    description: str
    detail: str
    required: bool
    state: Literal["not_downloaded", "downloading", "paused", "ready", "error"]
    downloaded_bytes: int = Field(0, ge=0)
    total_bytes: Optional[int] = Field(None, ge=0)
    approx_bytes: int = Field(ge=0)
    percent: Optional[int] = Field(None, ge=0, le=100)
    eta_seconds: Optional[float] = None
    eta_label: Optional[str] = None
    error: Optional[str] = None
    available: bool = True
    unavailable_reason: Optional[str] = None
    system_browser: Optional[str] = None
    in_use: Optional[Literal["component", "system"]] = None


def _handle_error(exc: components.ComponentError) -> ApiError:
    if isinstance(exc, components.ComponentNotFound):
        return ApiError(404, "component_not_found", str(exc))
    if isinstance(exc, components.ComponentUnavailable):
        return ApiError(409, "component_unavailable", str(exc))
    if isinstance(exc, components.ComponentBusy):
        return ApiError(409, "component_busy", str(exc))
    return ApiError(500, "component_error", str(exc))


@router.get("/components", response_model=list[ComponentStatus],
            summary="Stato e avanzamento dei componenti scaricabili di RT")
def list_components_endpoint(_actor: Actor) -> list[ComponentStatus]:
    return [ComponentStatus(**item) for item in components.list_components()]


@router.post("/components/{component_id}/download", response_model=ComponentStatus, status_code=202,
             summary="Avvia o riprende il download in background di un componente",
             responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def download_component_endpoint(component_id: str, _actor: Actor) -> ComponentStatus:
    try:
        return ComponentStatus(**components.start_download(component_id))
    except components.ComponentError as exc:
        raise _handle_error(exc) from None


@router.post("/components/{component_id}/cancel", response_model=ComponentStatus,
             summary="Mette in pausa o annulla il download in corso di un componente",
             responses={404: {"model": ErrorResponse}})
def cancel_component_endpoint(component_id: str, _actor: Actor) -> ComponentStatus:
    try:
        return ComponentStatus(**components.cancel_download(component_id))
    except components.ComponentError as exc:
        raise _handle_error(exc) from None


@router.delete("/components/{component_id}", response_model=ComponentStatus,
               summary="Elimina da disco i file di un componente scaricato",
               responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def delete_component_endpoint(component_id: str, _actor: Actor) -> ComponentStatus:
    try:
        return ComponentStatus(**components.delete_component(component_id))
    except components.ComponentError as exc:
        raise _handle_error(exc) from None
