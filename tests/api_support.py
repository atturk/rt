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


CHAT = {"id": -1001234567890, "type": "supergroup", "is_forum": True}


def _topic_root(topic_id, name):
    """Messaggio di servizio che crea il topic (la radice: il suo id è quello del topic)."""
    return {"message_id": topic_id, "message_thread_id": topic_id, "is_topic_message": True, "chat": CHAT,
            "forum_topic_created": {"name": name, "icon_color": 7322096}}


# Bot API finta (RT4-F5, RT4-FA6). "_age": secondi fa, trasformati in "date" a ogni risposta.
# - topic 12 "Biochimica": messaggio di creazione e un messaggio nel topic (nome anche dal reply);
# - topic 27 "Anatomia umana": solo il reply_to_message (nome senza materia corrispondente) e un
#   messaggio di 3 giorni fa (oltre le 48 ore: Telegram non lo cancellerebbe);
# - topic 33: risposta a un altro messaggio, nome non recuperabile;
# - un messaggio nel topic Generale (senza message_thread_id).
FAKE_TELEGRAM_UPDATES = [
    {"update_id": 1, "message": {**_topic_root(12, "Biochimica"), "_age": 120}},
    {"update_id": 2, "message": {"message_id": 40, "message_thread_id": 12, "is_topic_message": True, "chat": CHAT,
                                 "text": "biochimica", "_age": 60, "reply_to_message": _topic_root(12, "Biochimica")}},
    {"update_id": 3, "message": {"message_id": 41, "message_thread_id": 27, "is_topic_message": True, "chat": CHAT,
                                 "text": "anatomia", "_age": 50, "reply_to_message": _topic_root(27, "Anatomia umana")}},
    {"update_id": 4, "message": {"message_id": 42, "message_thread_id": 27, "is_topic_message": True, "chat": CHAT,
                                 "text": "vecchio", "_age": 3 * 86400}},
    {"update_id": 5, "message": {"message_id": 43, "message_thread_id": 33, "is_topic_message": True, "chat": CHAT,
                                 "text": "risposta", "_age": 40,
                                 "reply_to_message": {"message_id": 35, "message_thread_id": 33, "chat": CHAT, "text": "x"}}},
    {"update_id": 6, "message": {"message_id": 44, "chat": CHAT, "text": "generale", "_age": 30}},
]


def fake_telegram_server(updates=None):
    """Bot API finta su una porta libera di 127.0.0.1: getUpdates (rilevamento topic),
    sendMessage e deleteMessage. Restituisce (server, base_url): basta
    RT_TELEGRAM_API_URL=base_url. Token 'rifiutato' -> 401. server.calls registra le chiamate
    [(metodo, corpo)], server.deleted gli id cancellati (un secondo deleteMessage -> 400)."""
    import copy
    import json as _json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    payload = FAKE_TELEGRAM_UPDATES if updates is None else updates

    def dated():
        now = int(time.time())
        out = copy.deepcopy(payload)
        for item in out:
            message = item.get("message") or {}
            if "_age" in message:
                message["date"] = now - message.pop("_age")
        return out

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            data = _json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            ok = "/getUpdates" in self.path and "rifiutato" not in self.path
            self._reply(200 if ok else 401, {"ok": True, "result": dated()} if ok
                        else {"ok": False, "error_code": 401, "description": "Unauthorized"})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = _json.loads(self.rfile.read(length) or b"{}")
            method = self.path.rsplit("/", 1)[-1]
            server.calls.append((method, body))
            if "rifiutato" in self.path:
                return self._reply(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
            if method == "sendMessage":
                server.sent += 1
                return self._reply(200, {"ok": True, "result": {"message_id": 1000 + server.sent, "chat": CHAT,
                                                                "text": body.get("text")}})
            if method == "deleteMessage":
                key = (str(body.get("chat_id")), int(body.get("message_id")))
                if key in server.deleted:
                    return self._reply(400, {"ok": False, "error_code": 400,
                                             "description": "Bad Request: message to delete not found"})
                server.deleted.add(key)
                return self._reply(200, {"ok": True, "result": True})
            self._reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls, server.deleted, server.sent = [], set(), 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
