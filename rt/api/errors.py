"""
rt.api.errors
Formato uniforme degli errori: {"error": {"code": "...", "message": "...", "details": ...}}.
I messaggi passano dal sanificatore delle credenziali; le eccezioni inattese diventano un
500 generico (il dettaglio resta nel log del server, mai nella risposta).
"""
import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("rt.api")

HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
              405: "method_not_allowed", 409: "conflict", 413: "payload_too_large",
              415: "unsupported_media_type", 416: "range_not_satisfiable", 422: "validation_error",
              503: "unavailable"}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def sanitize(message: str) -> str:
    try:
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        return GLOBAL_CREDENTIALS.sanitize_secrets(str(message))
    except Exception:
        return str(message)


def error_response(status_code: int, code: str, message: str, details: Any = None, headers=None) -> JSONResponse:
    body = {"error": {"code": code, "message": sanitize(message), "details": details}}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


# Risposte d'errore documentate nell'OpenAPI di ogni router autenticato.
COMMON_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Autenticazione mancante o non valida"},
    403: {"model": ErrorResponse, "description": "CSRF non valido"},
    404: {"model": ErrorResponse, "description": "Risorsa non trovata"},
    409: {"model": ErrorResponse, "description": "Conflitto (es. job in corso sulla lezione)"},
    422: {"model": ErrorResponse, "description": "Richiesta non valida"},
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Errore"
        return error_response(exc.status_code, HTTP_CODES.get(exc.status_code, "error"), message,
                              headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        return error_response(422, "validation_error", "Richiesta non valida.", details)

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):
        logger.exception("Errore inatteso nell'API: %s", sanitize(str(exc)))
        return error_response(500, "internal_error", "Errore interno del server.")
