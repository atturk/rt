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
            f"telegram:\n  lessons_root: {str(root)!r}\n", encoding="utf-8")
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


def make_lesson(root: str, name: str = LESSON_NAME, index: bool = True) -> str:
    """Cartella già inizializzata con trascritto Markdown (come lo scenario golden).
    index=False per le copie usate dal CLI in sottoprocesso: non vanno nel DB dei test API."""
    lesson_dir = os.path.join(root, name)
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML)
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD)
    from rt.db.engine import get_database
    if index and get_database() is not None:
        from rt.services.lesson_service import ensure_indexed
        ensure_indexed([lesson_dir])
    return lesson_dir


def add_audio(lesson_dir: str, name: str = "lezione.m4a") -> str:
    target = os.path.join(lesson_dir, name)
    shutil.copy(AUDIO_FIXTURE, target)
    return target


def run_mock_pipeline(lesson_dir: str, with_review: bool = True, auto_accept: bool = True):
    """Pipeline in processo, in mock, come la eseguirebbe il worker."""
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    options = PipelineOptions(mock=True, with_review=with_review, auto_accept=auto_accept, rename=False)
    return run_pipeline([lesson_dir], options, RunContext())


# Bot API finta: la chat personale di chi ha scritto /start, dopo un messaggio in un gruppo
# (che il rilevamento della chat ignora).
PRIVATE_CHAT = {"id": 555123, "type": "private", "first_name": "Ada", "last_name": "Rossi"}
FAKE_TELEGRAM_UPDATES = [
    {"update_id": 1, "message": {"message_id": 10, "chat": {"id": -100999, "type": "supergroup"}, "text": "ciao"}},
    {"update_id": 2, "message": {"message_id": 11, "chat": PRIVATE_CHAT, "text": "/start"}},
]


def fake_telegram_server(updates=None):
    """Bot API finta su una porta libera di 127.0.0.1: getUpdates, getMe e sendMessage.
    Restituisce (server, base_url): basta RT_TELEGRAM_API_URL=base_url. Token 'rifiutato' ->
    401. server.calls registra tutte le chiamate [(metodo, corpo)], server.sent quelle accettate."""
    import itertools
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    payload = FAKE_TELEGRAM_UPDATES if updates is None else updates
    message_ids = itertools.count(100)

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            data = _json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = _json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            method = self.path.rsplit("/", 1)[-1]
            server.calls.append((method, body))
            if "rifiutato" in self.path:
                return self._reply(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
            server.sent.append((method, body))
            if method == "getUpdates":
                return self._reply(200, {"ok": True, "result": payload})
            if method == "getMe":
                return self._reply(200, {"ok": True, "result": {"id": 1, "is_bot": True, "username": "rt_test_bot"}})
            self._reply(200, {"ok": True, "result": {"message_id": next(message_ids), "text": body.get("text")}})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls, server.sent = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _serve(handler_cls):
    import threading
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def fake_searxng_server(results=3, json_enabled=True):
    """SearXNG finto su 127.0.0.1: /search?format=json con `results` immagini; con
    json_enabled=False risponde 403 come SearXNG quando il formato json non è abilitato."""
    import json as _json
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if not self.path.startswith("/search"):
                self.send_response(404)
                self.end_headers()
                return
            if not json_enabled:
                body, status, ctype = b"<h1>403 Forbidden</h1>", 403, "text/html"
            else:
                items = [{"title": f"Immagine {i}", "url": f"http://example.invalid/p{i}",
                          "img_src": f"http://example.invalid/{i}.png"} for i in range(results)]
                body, status, ctype = _json.dumps({"results": items}).encode(), 200, "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return _serve(Handler)


def fake_llm_server():
    """Provider OpenAI-compatible finto: POST /v1/chat/completions. Il modello 'inesistente'
    risponde 404 con un errore nel formato OpenAI; 'lento' non risponde per 5 secondi.
    Per la prova della visione: 'vede-rosso' risponde "Rossa.", 'pensa-troppo' esaurisce i token
    nel ragionamento (contenuto vuoto, finish_reason length), 'cieco' risponde "Non vedo immagini".
    Le richieste ricevute restano in server.requests (per controllare prompt e max_tokens)."""
    import json as _json
    import time as _time
    from http.server import BaseHTTPRequestHandler
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = _json.loads(self.rfile.read(length) or b"{}")
            received.append({"path": self.path, "auth": self.headers.get("Authorization"), "json": payload})
            model = payload.get("model")
            if model == "lento":
                _time.sleep(5)
            if model == "inesistente":
                status = 404
                body = {"error": {"message": "The model `inesistente` does not exist", "type": "invalid_request_error"}}
            else:
                status = 200
                content, finish = {"vede-rosso": ("Rossa.", "stop"), "pensa-troppo": ("", "length"),
                                   "cieco": ("Non vedo immagini", "stop")}.get(model, ("ok", "stop"))
                body = {"id": "x", "model": model, "choices": [{"index": 0, "finish_reason": finish,
                        "message": {"role": "assistant", "content": content}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}
            data = _json.dumps(body).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server, url = _serve(Handler)
    server.requests = received
    return server, url


def mock_image_description_for_unit(monkeypatch, lesson_dir):
    """Foto pertinente per i test d'integrazione: il mapping richiede candidate reali."""
    from rt.llm.client import LLMClient
    from rt.pipeline.outline import load_outline
    title = load_outline(lesson_dir).macro_sections[0].units[0].title
    original = LLMClient.call_structured

    def describe(self, *args, **kwargs):
        if kwargs.get('job_name') == 'image_description':
            assert self.force_mock  # nessuna chiamata reale, neppure se il worker perde --mock
            result = original(self, *args, **kwargs)
            return result.model_copy(update={'ocr_text': title})
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LLMClient, 'call_structured', describe)
