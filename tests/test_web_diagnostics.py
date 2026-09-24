"""Il log web deve rendere visibili i guasti senza divulgare percorsi audio."""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from rt.web.diagnostics import RequestLogMiddleware, log_action
from rt.web.app import _client_log


def test_request_log_hides_audio_path(caplog):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 206, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = RequestLogMiddleware(app)
    scope = {"type": "http", "method": "GET", "path": "/gradio_api/file=/private/lesson/audio.m4a"}
    with caplog.at_level(logging.INFO, logger="rt.web"):
        asyncio.run(middleware(scope, lambda: None, lambda message: asyncio.sleep(0)))

    assert "HTTP GET /gradio_api/file=<audio> → 206" in caplog.text
    assert "/private/lesson" not in caplog.text


def test_backend_action_logs_exception(caplog):
    @log_action("prova")
    def fail():
        raise ValueError("guasto di prova")

    with caplog.at_level(logging.INFO, logger="rt.web"), pytest.raises(ValueError):
        fail()
    assert "Azione prova avviata" in caplog.text
    assert "Azione prova fallita" in caplog.text


def test_browser_error_reaches_server_log(caplog):
    with caplog.at_level(logging.WARNING, logger="rt.web"):
        _client_log(SimpleNamespace(kind="audio.error", message="Formato non supportato"))
    assert "Browser audio.error: Formato non supportato" in caplog.text
