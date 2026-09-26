"""
rt.api.launcher
'rt web --spa' (RT4-F1): un solo comando che avvia l'API (con la SPA su /) e un 'rt worker'
figlio, apre il browser già autenticato con un link monouso e ferma tutto con Ctrl+C.
Senza worker i job resterebbero in coda, quindi i due processi vivono e muoiono insieme.
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from typing import Callable, List, Optional

from rt.api.server import DEFAULT_HOST, DEFAULT_PORT, LOOPBACK

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def worker_command(extra: Optional[List[str]] = None) -> List[str]:
    return [sys.executable, os.path.join(_PROJECT_ROOT, "bin", "rt"), "worker"] + list(extra or [])


def _open_when_ready(base: str, url: str, say: Callable[[str], None], open_browser: bool) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/v1/health", timeout=2):
                break
        except Exception:
            time.sleep(0.3)
    say(f"🌐 Apri RT nel browser: {url}")
    say("   (link monouso, valido 5 minuti; poi usa il token nella pagina di accesso)")
    if open_browser:
        webbrowser.open(url)


def run_spa(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = True,
            worker: bool = True, worker_args: Optional[List[str]] = None,
            say: Callable[[str], None] = print) -> int:
    import uvicorn
    from rt.api import auth
    from rt.api.app import create_app
    from rt.api.server import prepare
    from rt.api.spa import find_spa_dir

    if host not in LOOPBACK:
        say(f"⚠️  RT sarà raggiungibile da altri dispositivi su {host}:{port}. Proteggi il token.")
    if not prepare(host=host, say=say):
        return 1
    spa_dir = find_spa_dir()
    if not spa_dir:
        say("⚠️  Interfaccia web non compilata: esegui 'npm install && npm run build' in frontend/ "
            "(o aggiorna RT con 'rt -u'). L'API funziona comunque.")
    shown = f"[{host}]" if ":" in host else host
    base = f"http://{shown}:{port}"
    login_url = f"{base}/login?code={auth.create_login_code()}"

    child = None
    if worker:
        child = subprocess.Popen(worker_command(worker_args))
        say(f"👷 Worker avviato (pid {child.pid}).")
    threading.Thread(target=_open_when_ready, args=(base, login_url, say, open_browser), daemon=True).start()
    say(f"🚀 RT su {base}  ·  API {base}/api/v1  ·  Ctrl+C per fermare API e worker")
    try:
        uvicorn.run(create_app(spa_dir=spa_dir), host=host, port=port, log_level="warning")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
        say("⏹ RT fermato.")
    return 0
