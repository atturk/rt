"""
Server per i test end-to-end della SPA (Playwright, fase F): API vera + worker + build della
SPA su una cartella lezioni di prova, isolata in una directory temporanea.

Uso (lo lancia frontend/playwright.config.ts):
    python scripts/e2e_server.py --port 8766 [--dir /tmp/rt-e2e]

Scrive frontend/e2e/.state/server.json con base_url e token API, che i test usano per
chiedere un link di accesso monouso (POST /api/v1/auth/login-link) e per rileggere dall'API.
Ogni avvio riparte da zero: lezioni, DB e configurazione vengono ricreati. Il worker gira con
--mock (LLM e risposte vocali finti), il bot Telegram è finto (RT_TELEGRAM_FAKE=1) e il Bot API
anche (tests/api_support.fake_telegram_server); niente finestra di Finder per la scelta cartella.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "frontend", "e2e", ".state", "server.json")


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
    # Cartelle per il navigatore della scelta cartella (RT4-FA6): la finestra di Finder è
    # disattivata, come su Linux, così anche su macOS i test usano il ripiego della SPA.
    for folder in ("Documenti/RT Lezioni e2e", "Documenti/Università", "Scrivania"):
        os.makedirs(os.path.join(home, folder))
    os.environ["HOME"] = home
    os.environ["RT_NATIVE_FOLDER_PICKER"] = "0"
    os.environ["RT_TELEGRAM_FAKE"] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [ROOT, os.environ.get("PYTHONPATH")]))
    os.environ.pop("RT_DATABASE_URL", None)
    os.environ["RT_SECRETS_FILE"] = os.path.join(work, "config", "secrets.enc")
    os.chdir(work)
    return lessons


def _plain_lesson(root: str, date: str, materia: str, argomenti: str) -> str:
    """Cartella con info.yaml e trascritto, come dopo 'rt setup'."""
    from tests.golden_support import INFO_YAML, TRANSCRIPT_MD
    folder = os.path.join(root, f"[{date}] {materia} - {argomenti}")
    os.makedirs(folder)
    with open(os.path.join(folder, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML.replace("2026-09-05", date).replace("BIOCHIMICA", materia).replace("Lipidi", argomenti))
    with open(os.path.join(folder, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD.replace("2026-09-05", date).replace("BIOCHIMICA", materia))
    return folder


def _lessons(root: str) -> None:
    """BIOCHIMICA completa con audio; FISIOLOGIA solo setup; FARMACOLOGIA e PATOLOGIA con
    l'outline approvata e 10 issue della review da decidere (per la review contestuale)."""
    from rt.services.outline_service import approve_outline
    from tests.api_support import add_audio, make_lesson, run_mock_pipeline
    done = make_lesson(root)
    add_audio(done)
    run_mock_pipeline(done, with_review=True, auto_accept=True)
    _plain_lesson(root, "2026-09-12", "FISIOLOGIA", "Il rene")
    for date, materia, argomenti in (("2026-09-19", "FARMACOLOGIA", "Recettori"),
                                     ("2026-09-20", "PATOLOGIA", "Infiammazione")):
        lesson = _plain_lesson(root, date, materia, argomenti)
        add_audio(lesson)
        run_mock_pipeline(lesson, with_review=True, auto_accept=False)  # si ferma sull'outline
        approve_outline(lesson, channel="api")
        run_mock_pipeline(lesson, with_review=True, auto_accept=False)  # si ferma sulle issue
    # Come le lezioni reali da RT 4.0: testi nel DB, media in media/ (le cartelle vanno nel backup).
    from rt.storage.migrate import migrate_storage
    report = migrate_storage(root)
    if report.errors:
        raise RuntimeError("; ".join(report.errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--dir", default=os.path.join(tempfile.gettempdir(), "rt-e2e"))
    args = parser.parse_args()
    sys.path.insert(0, ROOT)

    # realpath: su macOS la cartella temporanea è un link (/var -> /private/var) e l'API salva
    # la cartella delle lezioni risolta; i test la confrontano con quella di server.json.
    root = _workspace(os.path.realpath(args.dir))
    from rt.api import auth
    from rt.api.launcher import run_spa
    from rt.db.bootstrap import ensure_database
    from rt.db.engine import get_database

    ensure_database()
    _lessons(root)
    # Bot API finta per "Ascolta i topic" (RT4-F5): API e worker la ereditano dall'ambiente.
    from tests.api_support import fake_telegram_server
    _telegram, os.environ["RT_TELEGRAM_API_URL"] = fake_telegram_server()
    token = auth.reset_token(get_database())
    base_url = f"http://127.0.0.1:{args.port}"
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"base_url": base_url, "token": token, "lessons_root": root}, f)
    print(f"Server e2e su {base_url} (lezioni in {root})", flush=True)
    return run_spa(port=args.port, open_browser=False, worker_args=["--mock"])


if __name__ == "__main__":
    sys.exit(main())
