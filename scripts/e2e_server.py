"""
Server per i test end-to-end della SPA (Playwright, fase F): API vera + worker + build della
SPA su una cartella lezioni di prova, isolata in una directory temporanea.

Uso (lo lancia frontend/playwright.config.ts):
    python scripts/e2e_server.py --port 8766 [--dir /tmp/rt-e2e]

Scrive frontend/e2e/.state/server.json con base_url e token API, che i test usano per
chiedere un link di accesso monouso (POST /api/v1/auth/login-link) e per rileggere dall'API.
Ogni avvio riparte da zero: lezioni, DB e configurazione vengono ricreati.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "frontend", "e2e", ".state", "server.json")
SECOND_LESSON = "[2026-09-12] FISIOLOGIA - Il rene"


def _workspace(base: str) -> str:
    """cwd con config/ (da config.example) e lessons_root dentro base; HOME isolata."""
    import yaml
    if os.path.isdir(base):
        shutil.rmtree(base)
    work, lessons, home = (os.path.join(base, d) for d in ("work", "lessons", "home"))
    os.makedirs(lessons)
    os.makedirs(home)
    shutil.copytree(os.path.join(ROOT, "config.example"), os.path.join(work, "config"))
    with open(os.path.join(work, ".env"), "w", encoding="utf-8"):
        pass
    general_path = os.path.join(work, "config", "general.yaml")
    with open(general_path, encoding="utf-8") as f:
        general = yaml.safe_load(f) or {}
    general.setdefault("telegram", {})["lessons_root"] = lessons
    with open(general_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general, f, sort_keys=False, allow_unicode=True)
    os.environ["HOME"] = home
    os.environ.pop("RT_DATABASE_URL", None)
    os.environ["RT_SECRETS_FILE"] = os.path.join(work, "config", "secrets.enc")
    os.chdir(work)
    return lessons


def _lessons(root: str) -> None:
    from tests.api_support import add_audio, make_lesson, run_mock_pipeline
    from tests.golden_support import INFO_YAML, TRANSCRIPT_MD
    done = make_lesson(root)
    add_audio(done)
    run_mock_pipeline(done, with_review=True, auto_accept=True)
    second = os.path.join(root, SECOND_LESSON)
    os.makedirs(second)
    with open(os.path.join(second, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML.replace("2026-09-05", "2026-09-12").replace("BIOCHIMICA", "FISIOLOGIA")
                .replace("Lipidi", "Il rene"))
    with open(os.path.join(second, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD.replace("BIOCHIMICA", "FISIOLOGIA"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--dir", default=os.path.join(tempfile.gettempdir(), "rt-e2e"))
    args = parser.parse_args()
    sys.path.insert(0, ROOT)

    root = _workspace(os.path.abspath(args.dir))
    from rt.api import auth
    from rt.api.launcher import run_spa
    from rt.db.bootstrap import ensure_database
    from rt.db.engine import get_database

    ensure_database()
    _lessons(root)
    token = auth.reset_token(get_database())
    base_url = f"http://127.0.0.1:{args.port}"
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"base_url": base_url, "token": token, "lessons_root": root}, f)
    print(f"Server e2e su {base_url} (lezioni in {root})", flush=True)
    return run_spa(port=args.port, open_browser=False)


if __name__ == "__main__":
    sys.exit(main())
