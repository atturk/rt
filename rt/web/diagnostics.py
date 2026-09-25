"""Diagnostica locale della web app: console, file a rotazione e richieste HTTP."""
from __future__ import annotations

from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable

from starlette.responses import FileResponse, JSONResponse, PlainTextResponse


LOG = logging.getLogger("rt.web")


def default_log_file() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "rt" / "web.log"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "rt" / "web.log"


def configure_logging(path: str | Path | None = None) -> Path:
    """Invia gli stessi eventi al terminale e a un file locale con dimensione limitata."""
    destination = Path(path or os.environ.get("RT_WEB_LOG") or default_log_file()).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(handler, "_rt_web_handler", False) for handler in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream._rt_web_handler = True
        root.addHandler(stream)
        rotating = RotatingFileHandler(destination, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        rotating.setFormatter(formatter)
        rotating._rt_web_handler = True
        root.addHandler(rotating)
        os.chmod(destination, 0o600)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    LOG.info("Diagnostica web attiva: %s", destination)
    return destination


def log_action(name: str) -> Callable:
    """Registra durata ed eccezioni dei callback che Gradio altrimenti intercetta."""
    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            LOG.info("Azione %s avviata", name)
            try:
                result = function(*args, **kwargs)
            except Exception:
                LOG.exception("Azione %s fallita dopo %.0f ms", name, (time.monotonic() - started) * 1000)
                raise
            LOG.info("Azione %s completata in %.0f ms", name, (time.monotonic() - started) * 1000)
            return result
        return wrapper
    return decorate


class RequestLogMiddleware:
    """Registra esito e durata HTTP senza salvare corpi, query o percorsi dei file."""

    def __init__(self, app, audio_dir: str | None = None):
        self.app = app
        self.audio_dir = Path(audio_dir).resolve() if audio_dir else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        audio_request = path.startswith("/rt-audio/")
        if path.startswith("/gradio_api/file="):
            path = "/gradio_api/file=<audio>"
        elif audio_request:
            path = "/rt-audio/<audio>"
        started = time.monotonic()
        status = 500
        response_range = ""

        async def send_logged(message):
            nonlocal status, response_range
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-range":
                        response_range = value.decode("ascii", errors="replace")
            await send(message)

        try:
            if audio_request:
                filename = scope.get("path", "").removeprefix("/rt-audio/")
                peaks_request = filename.endswith(".peaks")
                if peaks_request:
                    filename = filename.removesuffix(".peaks")
                if scope.get("method") not in {"GET", "HEAD"}:
                    response = PlainTextResponse("Method not allowed", status_code=405)
                elif self.audio_dir is None or not re.fullmatch(
                    r"[0-9a-f]{20}\.(?:m4a|mp3|wav|flac|aac|ogg)", filename
                ):
                    response = PlainTextResponse("Not found", status_code=404)
                else:
                    candidate = self.audio_dir / filename
                    if not candidate.is_file() or candidate.resolve().parent != self.audio_dir:
                        response = PlainTextResponse("Not found", status_code=404)
                    elif peaks_request:
                        from rt.web.data import waveform_result
                        peaks = waveform_result(str(candidate))
                        response = (JSONResponse({"peaks": peaks}, headers={"Cache-Control": "private, no-store"})
                                    if peaks is not None else JSONResponse({"pending": True}, status_code=202,
                                                                           headers={"Cache-Control": "no-store"}))
                    else:
                        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                        response = FileResponse(candidate, media_type=mime,
                                                content_disposition_type="inline",
                                                headers={"Cache-Control": "private, no-store"})
                await response(scope, receive, send_logged)
            else:
                await self.app(scope, receive, send_logged)
        except Exception:
            LOG.exception("HTTP %s %s: eccezione", scope.get("method"), path)
            raise
        finally:
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            if audio_request and scope.get("path", "").endswith(".peaks") and status == 202:
                level = logging.DEBUG
            request_range = next((value.decode("ascii", errors="replace") for name, value
                                  in scope.get("headers", []) if name.lower() == b"range"), "")
            range_info = f" range={request_range} served={response_range}" if audio_request else ""
            LOG.log(level, "HTTP %s %s → %d (%.0f ms)%s", scope.get("method"), path,
                    status, (time.monotonic() - started) * 1000, range_info)
