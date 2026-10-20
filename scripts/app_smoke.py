#!/usr/bin/env python3
"""
scripts/app_smoke.py
Prova dell'app installata (CI): avvia 'rt desktop' come il doppio clic, senza browser e senza
servizi launchd, aspetta che API e web app rispondano con la versione giusta e la spegne.

    python scripts/app_smoke.py <python dell'app> <cartella del codice dell'app>
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

python, root = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
port = 8799
data = tempfile.mkdtemp(prefix="rt-app-smoke-")
env = {**os.environ, "RT_DATA_DIR": data, "RT_NO_SERVICES": "1", "RT_UPDATE_OFFLINE": "1", "RT_API_PORT": str(port),
       "PYTHONDONTWRITEBYTECODE": "1"}
log_path = os.path.join(data, "desktop-console.log")
with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
    version = f.read().strip()


def get(path: str) -> bytes:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return resp.read()


with open(log_path, "w", encoding="utf-8") as log:
    proc = subprocess.Popen([python, os.path.join(root, "bin", "rt"), "desktop", "--no-browser", "--port", str(port)],
                            env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=os.path.expanduser("~"))
    ok = False
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                health = json.loads(get("/api/v1/health"))
                ok = True
                break
            except OSError:
                time.sleep(1)
        if ok:
            assert health["version"] == version, health
            assert health["database"] is True, health
            page = get("/").decode("utf-8", "replace")
            assert 'id="root"' in page, page[:300]
            print(f"✅ RT {health['version']} risponde su http://127.0.0.1:{port} (dati in {data})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
print(open(log_path, encoding="utf-8", errors="replace").read())
for name in ("desktop.log", "worker.log", "api.log"):
    path = os.path.join(data, "logs", name)
    if os.path.isfile(path):
        print(f"--- {name}\n" + open(path, encoding="utf-8", errors="replace").read()[-4000:])
if not ok:
    sys.exit("❌ RT non ha risposto")
