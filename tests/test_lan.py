"""Accesso dalla stessa rete locale (Wi-Fi di casa o hotspot): opzione, indirizzi, endpoint."""
from fastapi.testclient import TestClient


def _client(api_token, host="127.0.0.1"):
    from rt.api.app import create_app
    app = create_app()
    return app, TestClient(app, client=(host, 1234), headers={"Authorization": f"Bearer {api_token}"})


HOME = "192.168.1.0/24|192.168.1.1|aa:bb:cc:dd:ee:01"


def _lan(monkeypatch, tmp_path, network=HOME):
    from rt.core import lan
    monkeypatch.setattr(lan, "_flag_path", lambda: str(tmp_path / "lan-access"))
    current = {"id": network}
    monkeypatch.setattr(lan, "network_id", lambda: current["id"])
    return lan, current


def test_on_only_after_restart_on_same_network(tmp_path, monkeypatch):
    lan, current = _lan(monkeypatch, tmp_path)
    assert lan.bind_host() == "127.0.0.1"
    lan.set_lan_enabled(True)
    # il riavvio chiesto dalle Impostazioni la tiene accesa
    monkeypatch.setenv(lan.KEEP_ENV, "1")
    assert lan.bind_host() == "0.0.0.0"
    # un avvio da zero (Esci da RT, riavvio del computer) la spegne
    assert lan.bind_host() == "127.0.0.1" and not lan.lan_enabled()
    # come un riavvio su un'altra rete con lo stesso 192.168.1.x
    lan.set_lan_enabled(True)
    current["id"] = "192.168.1.0/24|192.168.1.1|aa:bb:cc:dd:ee:99"
    monkeypatch.setenv(lan.KEEP_ENV, "1")
    assert lan.bind_host() == "127.0.0.1" and not lan.lan_enabled()


def test_same_network():
    from rt.core.lan import same_network
    assert same_network(HOME, HOME)
    assert same_network("192.168.1.0/24|192.168.1.1|", HOME)  # arp senza MAC: basta il router
    assert not same_network("172.20.10.0/24|172.20.10.1|", HOME)
    assert not same_network(None, HOME) and not same_network(HOME, None)


def test_watch_turns_off_when_network_changes(tmp_path, monkeypatch):
    import threading
    lan, current = _lan(monkeypatch, tmp_path)
    lan.set_lan_enabled(True)
    changed = threading.Event()
    stop = threading.Event()
    lan.watch_network(changed.set, stop=stop, interval=0.01)
    assert not changed.wait(0.1)
    current["id"] = "10.0.0.0/24|10.0.0.1|"
    assert changed.wait(2) and not lan.lan_enabled()
    stop.set()


def test_lan_ip_filter():
    from rt.core.lan import _is_lan_ip
    assert _is_lan_ip("192.168.1.20") and _is_lan_ip("172.20.10.2") and _is_lan_ip("10.0.0.5")
    # loopback, link-local, Tailscale (100.64/10), pubblici e IPv6 no
    for ip in ("127.0.0.1", "169.254.3.4", "100.72.84.124", "8.8.8.8", "fe80::1", "nonsense"):
        assert not _is_lan_ip(ip)


def test_addresses_local_name_first(monkeypatch):
    from rt.core import lan
    monkeypatch.setattr(lan, "_ADDRESS_CACHE", {})
    monkeypatch.setattr(lan, "_local_hostname", lambda: "MacBook-Air-di-Attilio")
    monkeypatch.setattr(lan, "_lan_ips", lambda: ["192.168.1.20"])
    assert lan.lan_addresses(8765) == ["http://MacBook-Air-di-Attilio.local:8765", "http://192.168.1.20:8765"]


def test_endpoint_toggle_and_restart(api_token, tmp_path, monkeypatch):
    lan, current = _lan(monkeypatch, tmp_path, network=None)
    monkeypatch.setattr(lan, "lan_addresses", lambda port: [f"http://mac.local:{port}"])
    app, client = _client(api_token)
    info = client.get("/api/v1/system/lan").json()
    assert info["enabled"] is False and info["active"] is False and info["restarting"] is False

    class FakeServer:
        should_exit = False
    app.state.uvicorn_server = FakeServer()
    assert client.put("/api/v1/system/lan", json={"enabled": True}).status_code == 409  # niente rete
    current["id"] = HOME
    info = client.put("/api/v1/system/lan", json={"enabled": True}).json()
    assert info["enabled"] is True and info["restarting"] is True
    assert app.state.restart_requested and app.state.uvicorn_server.should_exit
    assert lan.lan_enabled()


def test_only_from_this_computer(api_token, tmp_path, monkeypatch):
    lan, _ = _lan(monkeypatch, tmp_path)
    _, phone = _client(api_token, host="192.168.1.30")
    assert phone.put("/api/v1/system/lan", json={"enabled": True}).status_code == 403
    _, local = _client(api_token)
    proxied = local.put("/api/v1/system/lan", json={"enabled": True}, headers={"X-Forwarded-For": "100.1.2.3"})
    assert proxied.status_code == 403
    assert not lan.lan_enabled()
