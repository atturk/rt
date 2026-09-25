"""
rt.api.deps
Dipendenze condivise dai router: autenticazione e risoluzione dell'id di una lezione.
"""
from typing import Annotated, Optional

from fastapi import Depends, Path, Request, Security
from fastapi.security import HTTPAuthorizationCredentials

from rt.api.auth import bearer_scheme, require_auth
from rt.api.errors import ApiError


def current_actor(request: Request,
                  credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)) -> str:
    return require_auth(request, credentials)


Actor = Annotated[str, Depends(current_actor)]


def lesson_dir(lesson_id: Annotated[int, Path(description="Id della lezione (da GET /lessons)")]) -> str:
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    try:
        return resolve_lesson_dir(lesson_id)
    except LessonNotFound as exc:
        raise ApiError(404, "lesson_not_found", str(exc))


LessonDir = Annotated[str, Depends(lesson_dir)]
