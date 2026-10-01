"""Plugin pytest opt-in: i test RT possono usare soltanto server locali."""
from urllib.parse import urlparse

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    import requests
    import httpx

    def check(url):
        if urlparse(str(url)).hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            raise RuntimeError("Rete esterna disabilitata nei test offline")

    old_send = requests.Session.send
    def send(self, request, **kwargs):
        check(request.url)
        return old_send(self, request, **kwargs)
    monkeypatch.setattr(requests.Session, "send", send)
    old_handle = httpx.HTTPTransport.handle_request
    def handle(self, request):
        check(request.url)
        return old_handle(self, request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    old_async = httpx.AsyncHTTPTransport.handle_async_request
    async def handle_async(self, request):
        check(request.url)
        return await old_async(self, request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async)
