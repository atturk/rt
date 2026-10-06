"""
rt.core.tailscale
Indirizzo con cui un altro dispositivo della tailnet (iPhone) raggiunge RT su questo Mac.
Con Tailscale Serve il certificato HTTPS vale solo per il nome MagicDNS del Mac
(nome-mac.tailnet.ts.net), mai per l'IP 100.x: il link di accesso deve usare quel nome.
Legge 'tailscale status --json' e 'tailscale serve status --json'; senza Tailscale non c'è
indirizzo e la pagina chiede di scriverlo a mano.
"""
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

# Il servizio launchd ha un PATH ridotto; l'app di Tailscale per macOS tiene la CLI nel bundle.
CANDIDATES = (
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
)


@dataclass
class TailnetAddress:
    origin: str  # https://nome-mac.tailnet.ts.net[:porta]
    serve: bool  # Tailscale Serve inoltra "/" a RT
    funnel: bool  # ...ed è pubblico su Internet (Funnel)


def find_cli() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    return next((path for path in CANDIDATES if os.access(path, os.X_OK)), None)


def _run_json(cli: str, *args: str) -> Optional[dict]:
    try:
        result = subprocess.run([cli, *args, "--json"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _proxies_to(target: str, port: int) -> bool:
    """'http://127.0.0.1:8765', '127.0.0.1:8765', 'localhost:8765' o '8765' → stessa porta di RT."""
    rest = target.split("://", 1)[-1].split("/", 1)[0]
    host, _, tail = rest.rpartition(":")
    return (tail or rest) == str(port) and host in ("", "127.0.0.1", "localhost", "[::1]")


def tailnet_address(port: int, run_json: Optional[Callable[..., Optional[dict]]] = None) -> Optional[TailnetAddress]:
    """Indirizzo tailnet di RT, o None se Tailscale non c'è o non è collegato."""
    if run_json is None:
        cli = find_cli()
        if cli is None:
            return None
        run_json = lambda *args: _run_json(cli, *args)  # noqa: E731
    status = run_json("status")
    if not status or status.get("BackendState") not in (None, "Running"):
        return None
    host = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not host:
        return None
    serve = run_json("serve", "status") or {}
    web = serve.get("Web") or {}
    funnel = serve.get("AllowFunnel") or {}
    # preferisce la porta 443 (indirizzo senza porta), poi le altre in ordine
    for key in sorted(web, key=lambda k: (k.rpartition(":")[2] != "443", k)):
        name, _, web_port = key.rpartition(":")
        handler = ((web.get(key) or {}).get("Handlers") or {}).get("/") or {}
        if name.rstrip(".") != host or not _proxies_to(str(handler.get("Proxy") or ""), port):
            continue
        origin = f"https://{host}" if web_port == "443" else f"https://{host}:{web_port}"
        return TailnetAddress(origin=origin, serve=True, funnel=bool(funnel.get(key)))
    return TailnetAddress(origin=f"https://{host}", serve=False, funnel=False)
