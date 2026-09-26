"""
tests/api_support.py
Lezioni di prova per i test dell'API (fase E): una cartella lezione in una lessons_root
temporanea, con configurazione isolata nella cwd (come tests/golden_support.py).
"""
import os
import shutil

from tests.golden_support import AUDIO_FIXTURE, INFO_YAML, LESSON_NAME, TRANSCRIPT_MD


def isolated_workspace(tmp_path, monkeypatch, lessons_root=True):
    """cwd con config/ ed .env propri; lessons_root dentro tmp_path. Restituisce la root."""
    work = tmp_path / "work"
    (work / "config").mkdir(parents=True)
    (work / ".env").write_text("", encoding="utf-8")
    root = tmp_path / "lessons"
    root.mkdir()
    if lessons_root:
        (work / "config" / "general.yaml").write_text(
            f"telegram:\n  lessons_root: {str(root)!r}\n  default_channel: terminal\n", encoding="utf-8")
    monkeypatch.chdir(work)
    return str(root)


def workspace_with_example_config(tmp_path, monkeypatch):
    """Come isolated_workspace, ma con config/ copiata da config.example (i sei job LLM)."""
    root = isolated_workspace(tmp_path, monkeypatch, lessons_root=False)
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = os.path.join(os.getcwd(), "config")
    shutil.rmtree(config)
    shutil.copytree(os.path.join(project, "config.example"), config)
    import yaml
    general_path = os.path.join(config, "general.yaml")
    with open(general_path, encoding="utf-8") as f:
        general = yaml.safe_load(f) or {}
    general.setdefault("telegram", {})["lessons_root"] = root
    with open(general_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general, f, sort_keys=False, allow_unicode=True)
    return root


def make_lesson(root: str, name: str = LESSON_NAME) -> str:
    """Cartella già inizializzata con trascritto Markdown (come lo scenario golden)."""
    lesson_dir = os.path.join(root, name)
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML)
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD)
    return lesson_dir


def add_audio(lesson_dir: str, name: str = "lezione.m4a") -> str:
    target = os.path.join(lesson_dir, name)
    shutil.copy(AUDIO_FIXTURE, target)
    return target


def run_mock_pipeline(lesson_dir: str, with_review: bool = True, auto_accept: bool = True):
    """Pipeline in processo, in mock, senza DecisionProvider (come la eseguirebbe il worker)."""
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    options = PipelineOptions(mock=True, with_review=with_review, auto_accept=auto_accept,
                              rename=False, channel="terminal")
    return run_pipeline([lesson_dir], options, RunContext())


FAKE_TELEGRAM_UPDATES = [
    {"update_id": 1, "message": {"chat": {"id": -1001234567890}, "message_thread_id": 12, "text": "biochimica"}},
    {"update_id": 2, "message": {"chat": {"id": -1001234567890}, "message_thread_id": 27, "text": "fisiologia"}},
    {"update_id": 3, "message": {"chat": {"id": -1001234567890}, "text": "generale"}},
]


def fake_telegram_server(updates=None):
    """Bot API finta per getUpdates (rilevamento topic) su una porta libera di 127.0.0.1.
    Restituisce (server, base_url): basta RT_TELEGRAM_API_URL=base_url. Token 'rifiutato' -> 401."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    payload = FAKE_TELEGRAM_UPDATES if updates is None else updates

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            ok = "/getUpdates" in self.path and "rifiutato" not in self.path
            body = _json.dumps({"ok": True, "result": payload} if ok
                               else {"ok": False, "description": "Unauthorized"}).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
