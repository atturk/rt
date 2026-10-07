"""Hotfix 4.2.3b1.1: il QR per l'iPhone usava l'IP 100.x, per cui il certificato di Tailscale non
vale. RT rileva il nome MagicDNS del Mac e la porta di Tailscale Serve, su qualunque Mac."""
from rt.core.tailscale import TailnetAddress, tailnet_address

HOST = "macbook-air-di-attilio.tail305dd8.ts.net"
STATUS = {"BackendState": "Running", "Self": {"DNSName": HOST + "."}}


def fake(status=STATUS, serve=None):
    def run_json(*args):
        return status if args == ("status",) else serve
    return run_json


def web(port, proxy="http://127.0.0.1:8765", path="/"):
    return {f"{HOST}:{port}": {"Handlers": {path: {"Proxy": proxy}}}}


def test_serve_on_443_gives_plain_hostname():
    assert tailnet_address(8765, fake(serve={"Web": web(443)})) == TailnetAddress(f"https://{HOST}", True, False)


def test_serve_on_other_port_and_funnel_are_reported():
    serve = {"Web": {**web(8443), **web(443, path="/mini-app.html")}, "AllowFunnel": {f"{HOST}:443": True}}
    assert tailnet_address(8765, fake(serve=serve)) == TailnetAddress(f"https://{HOST}:8443", True, False)
    funnel = {"Web": web(443, proxy="127.0.0.1:8765"), "AllowFunnel": {f"{HOST}:443": True}}
    assert tailnet_address(8765, fake(serve=funnel)).funnel is True


def test_without_serve_for_rt_the_hostname_is_still_proposed():
    # come sull'Air: il Funnel inoltrava solo i percorsi della Mini App
    serve = {"Web": web(443, path="/mini-app.html")}
    assert tailnet_address(8765, fake(serve=serve)) == TailnetAddress(f"https://{HOST}", False, False)
    assert tailnet_address(8765, fake(serve=None)).serve is False
    assert tailnet_address(9000, fake(serve={"Web": web(443)})).serve is False


def test_no_tailscale_or_logged_out():
    assert tailnet_address(8765, fake(status=None)) is None
    assert tailnet_address(8765, fake(status={"BackendState": "NeedsLogin", "Self": {"DNSName": ""}})) is None


def test_endpoint(api_client, monkeypatch):
    import rt.core.tailscale as ts
    monkeypatch.setattr(ts, "find_cli", lambda: None)
    assert api_client.get("/api/v1/system/tailnet").json() == {"origin": None, "serve": False, "funnel": False}
