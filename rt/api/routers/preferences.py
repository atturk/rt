"""Preferenze personali condivise dai dispositivi di RT."""
import json
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response

from rt.api.deps import Actor
from rt.api.errors import ApiError
from rt.services import preferences_service

router = APIRouter(tags=["preferenze"])
PreferenceName = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
MAX_BYTES = 16 * 1024


@router.get("/preferences", response_model=dict[str, Any], summary="Tutte le preferenze personali")
def list_preferences(_actor: Actor):
    return preferences_service.list_preferences()


@router.put("/preferences/{name}", status_code=204, summary="Salva una preferenza personale JSON",
            openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {}}}}})
async def put_preference(name: PreferenceName, request: Request, _actor: Actor):
    # Anche gli spazi e le sequenze UTF-8 contano nel limite del corpo ricevuto.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise ApiError(422, "preference_too_large", "La preferenza supera 16 KB.")
    try:
        value = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(422, "invalid_preference", "Corpo JSON non valido.")
    preferences_service.save_preference(name, value)
    return Response(status_code=204)


@router.delete("/preferences/{name}", status_code=204, summary="Ripristina il predefinito della preferenza")
def delete_preference(name: PreferenceName, _actor: Actor):
    preferences_service.delete_preference(name)
    return Response(status_code=204)
