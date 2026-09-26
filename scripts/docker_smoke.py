"""
Prova di accettazione di RT4-G1 per Docker: con 'docker compose up' API e worker partono e un
run mock completo funziona via API.

Uso (dalla radice del repository, immagine già costruita con 'docker compose build'):
    python scripts/docker_smoke.py [--keep]

Avvia lo stack con un nome di progetto proprio (volume nuovo), entra con il link monouso di
'rt web --no-browser' eseguito nel container e fa il run mock di scripts/api_smoke.py. Alla fine
ferma lo stack e cancella il volume (salvo --keep).
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_smoke  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = "rt-smoke"
PORT = os.environ.get("RT_PORT", "18765")


def compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "RT_PORT": PORT}
    return subprocess.run(["docker", "compose", "-p", PROJECT, *args], cwd=ROOT, env=env, check=check,
                          text=True, capture_output=capture)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="Lascia lo stack e il volume per ispezionarli")
    args = parser.parse_args()
    compose("up", "-d", "--no-build", "api", "worker")
    try:
        code = api_smoke.run(
            f"http://127.0.0.1:{PORT}",
            lambda: compose("exec", "-T", "api", "rt", "web", "--no-browser", capture=True).stdout,
            lessons_root="/data/lezioni",
            on_setup_lessons_root=lambda path: compose("exec", "-T", "api", "mkdir", "-p", path),
        )
        if code:
            compose("logs", "api", "worker", check=False)
        return code
    finally:
        if not args.keep:
            compose("down", "-v", check=False)


if __name__ == "__main__":
    sys.exit(main())
