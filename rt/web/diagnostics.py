"""Diagnostica locale della web app: console, file a rotazione e richieste HTTP."""
from __future__ import annotations

from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time
from typing import Callable


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

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith("/gradio_api/file="):
            path = "/gradio_api/file=<audio>"
        started = time.monotonic()
        status = 500

        async def send_logged(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_logged)
        except Exception:
            LOG.exception("HTTP %s %s: eccezione", scope.get("method"), path)
            raise
        finally:
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            LOG.log(level, "HTTP %s %s → %d (%.0f ms)", scope.get("method"), path,
                    status, (time.monotonic() - started) * 1000)
