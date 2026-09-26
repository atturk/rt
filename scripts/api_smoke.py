"""
Run mock completo via API contro un RT già avviato (fase G): lo usano la prova di Docker
(scripts/docker_smoke.py) e il job CI dell'installer su macOS pulito.

    python scripts/api_smoke.py --base http://127.0.0.1:8765 --login-cmd "rt web --no-browser" \\
        --lessons-root ~/Lezioni [--expect-lessons 1]

Entra con il link monouso stampato da --login-cmd, imposta la cartella lezioni se serve,
aspetta un worker, carica l'audio di prova con run=true e mock=true e aspetta la fine del job.
--expect-lessons N controlla prima che l'API veda già almeno N lezioni (aggiornamento da 3.x).
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Callable, List, Optional

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, "tests", "fixtures", "demo_lecture.wav")


def login(base: str, login_output: str) -> requests.Session:
    match = re.search(r"/login\?code=([\w-]+)", login_output)
    if not match:
        raise SystemExit(f"❌ Nessun link di accesso nell'output:\n{login_output}")
    session = requests.Session()
    r = session.get(f"{base}/login?code={match.group(1)}", allow_redirects=False, timeout=10)
    if r.status_code != 303 or "rt_session" not in session.cookies:
        raise SystemExit(f"❌ Accesso non riuscito ({r.status_code}): {r.text[:300]}")
    session.headers["X-CSRF-Token"] = session.cookies["rt_csrf"]
    return session


def wait_health(base: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base}/api/v1/health", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise SystemExit(f"❌ L'API non risponde su {base}")


def _lessons(s: requests.Session, base: str) -> list:
    data = s.get(f"{base}/api/v1/lessons", timeout=30).json()
    return data.get("items", []) if isinstance(data, dict) else data


def run(base: str, login_output: Callable[[], str], lessons_root: Optional[str] = None,
        expect_lessons: int = 0, on_setup_lessons_root: Optional[Callable[[str], None]] = None) -> int:
    wait_health(base)
    s = login(base, login_output())
    if expect_lessons:
        found = _lessons(s, base)
        if len(found) < expect_lessons:
            print(f"❌ Lezioni viste dall'API: {len(found)}, attese almeno {expect_lessons}", file=sys.stderr)
            return 1
        print(f"✅ Lezioni già presenti viste dall'API: {len(found)}")
    if lessons_root:
        if on_setup_lessons_root:
            on_setup_lessons_root(lessons_root)
        r = s.put(f"{base}/api/v1/settings/lessons-root", json={"path": lessons_root}, timeout=30)
        if not r.ok:
            print(f"❌ Cartella lezioni non impostata: {r.status_code} {r.text[:300]}", file=sys.stderr)
            return 1
    deadline = time.monotonic() + 60
    while not s.get(f"{base}/api/v1/workers", timeout=10).json():
        if time.monotonic() > deadline:
            print("❌ Nessun worker attivo", file=sys.stderr)
            return 1
        time.sleep(1)
    before = len(_lessons(s, base))
    with open(AUDIO, "rb") as f:
        r = s.post(f"{base}/api/v1/lessons", timeout=60,
                   files={"audio": ("demo_lecture.wav", f, "audio/wav")},
                   data={"date": "2026-09-26", "materia": "Anatomia", "argomenti": "Prova installazione",
                         "run": "true", "mock": "true", "auto_accept": "true"})
    if not r.ok:
        print(f"❌ Importazione rifiutata: {r.status_code} {r.text[:300]}", file=sys.stderr)
        return 1
    job = r.json()
    print(f"📥 Job {job['job_id']} ({job['type']})")
    state = {}
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        state = s.get(f"{base}/api/v1/jobs/{job['job_id']}", timeout=10).json()
        if state["state"] in ("succeeded", "failed", "cancelled", "waiting_for_decision"):
            break
        time.sleep(2)
    print(f"   stato finale: {state.get('state')}")
    if state.get("state") != "succeeded":
        print(state.get("error"), file=sys.stderr)
        return 1
    after = len(_lessons(s, base))
    if after <= before:
        print(f"❌ La lezione nuova non compare ({before} → {after})", file=sys.stderr)
        return 1
    print(f"✅ Run mock completo via API: {after} lezioni")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8765")
    p.add_argument("--login-cmd", required=True, help="Comando che stampa il link monouso (rt web --no-browser)")
    p.add_argument("--lessons-root", default=None)
    p.add_argument("--expect-lessons", type=int, default=0)
    args = p.parse_args(argv)
    root = os.path.expanduser(args.lessons_root) if args.lessons_root else None

    def login_output() -> str:
        return subprocess.run(shlex.split(args.login_cmd), capture_output=True, text=True, check=True).stdout

    return run(args.base, login_output, root, args.expect_lessons,
               on_setup_lessons_root=lambda path: os.makedirs(path, exist_ok=True))


if __name__ == "__main__":
    sys.exit(main())
