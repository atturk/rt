"""
rt.api.app
App factory dell'API. Tutti i router stanno sotto /api/v1; solo /health e l'apertura della
sessione sono pubblici. /docs (Swagger UI) e /openapi.json sono pubblici: descrivono gli
endpoint, non contengono dati.
"""
import os
from typing import Iterable, Optional

from fastapi import FastAPI

from rt.api.errors import COMMON_RESPONSES, install_error_handlers

API_PREFIX = "/api/v1"
CORS_ENV = "RT_API_CORS_ORIGINS"

DESCRIPTION = """
API locale di RT (utente singolo). Autenticazione: premi **Authorize** e incolla il token
mostrato da `rt api` al primo avvio (header `Authorization: Bearer <token>`). Per un token
nuovo: `rt api --reset-token`.

Le operazioni lunghe (pipeline, fasi, trascrizione, immagini, recall) diventano job eseguiti
da `rt worker`: l'endpoint risponde 202 con l'id del job, il progresso arriva da
`GET /jobs/{id}/events` (Server-Sent Events).
"""


def _cors_origins(explicit: Optional[Iterable[str]]) -> list:
    if explicit is not None:
        return [o for o in explicit if o]
    return [o.strip() for o in os.environ.get(CORS_ENV, "").split(",") if o.strip()]


def create_app(auth_disabled: bool = False, cors_origins: Optional[Iterable[str]] = None) -> FastAPI:
    from rt.core.config import _default_project_root
    from rt.core.version import get_current_version
    from rt.api.routers import system

    app = FastAPI(
        title="RT API",
        version=get_current_version(_default_project_root()),
        description=DESCRIPTION,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.auth_disabled = auth_disabled
    install_error_handlers(app)

    origins = _cors_origins(cors_origins)
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Last-Event-ID"],
        )

    app.include_router(system.router, prefix=API_PREFIX)
    for router in _domain_routers():
        app.include_router(router, prefix=API_PREFIX, responses=COMMON_RESPONSES)
    return app


def _domain_routers() -> list:
    from rt.api.routers import lessons, settings
    return [lessons.router, settings.router]
