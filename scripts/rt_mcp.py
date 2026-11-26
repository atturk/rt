#!/usr/bin/env python3
"""
scripts/rt_mcp.py
Server MCP (stdio) che permette a Claude Code di usare un'installazione di RT già avviata:
API, job, import, log ed export. L'interfaccia e la console del browser si provano con il
server MCP di Playwright, aperto con il link monouso di rt_browser_login (vedi .mcp.json e
docs/mcp.md).

Solo libreria standard: gira con qualsiasi python3, senza toccare l'ambiente dell'app.

Accesso all'API, nell'ordine:
1. RT_API_TOKEN, oppure il file indicato da RT_API_TOKEN_FILE (predefinito ~/.rt/config/mcp-token);
2. altrimenti, sul Mac, un link monouso chiesto all'app installata ('rt web --no-browser', il
   comando dei servizi launchd): apre una sessione con cookie e CSRF come la web app. Così non
   serve copiare il token e quello dell'utente non cambia.

Variabili:
- RT_MCP_BASE_URL   indirizzo dell'API (predefinito http://127.0.0.1:<porta dell'app>)
- RT_MCP_MODE       "full" (predefinito) o "readonly" (solo GET)
- RT_DATA_DIR       cartella dati (predefinito ~/.rt): log, porta, export
- RT_MCP_RT_COMMAND comando per 'rt' se non è quello dei servizi launchd (es. "python3 /x/bin/rt")

Protezioni: alcune operazioni sono sempre bloccate (uscita dall'app, aggiornamenti, rivelare
segreti, finestra del Finder); quelle che cancellano o sovrascrivono chiedono confirm=true.
Prima di eliminare una lezione ne salva sempre lo ZIP completo in <dati>/mcp/exports.
"""
import http.cookiejar
import json
import mimetypes
import os
import plistlib
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

SERVER_NAME = "rt"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_PORT = 8765
MAX_TEXT = 60_000
LOG_FILES = ("api", "worker", "desktop", "browser-install")
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}

# Mai dal server MCP: chiudono o aggiornano l'app, mostrano segreti, aprono finestre sul Mac.
BLOCKED: List[Tuple[str, str]] = [
    ("POST", r"/system/quit"),
    ("POST", r"/system/update(/install)?"),
    ("PUT", r"/system/update/channel"),
    ("POST", r"/system/choose-folder"),
    ("POST", r"/settings/telegram/reveal"),
    ("POST", r"/auth/login-link"),
    ("DELETE", r"/auth/session"),
]

# Cancellano o sovrascrivono dati: servono confirm=true.
CONFIRM: List[Tuple[str, str]] = [
    ("DELETE", r".*"),
    ("POST", r".*/delete"),
    ("POST", r"/system/compact-audio"),
    ("POST", r"/lessons/[^/]+/update"),
    ("POST", r"/lessons/[^/]+/document/restore-pipeline"),
    ("POST", r"/lessons/[^/]+/versions/[^/]+/restore"),
    ("POST", r"/lessons/[^/]+/recall/questions/restore"),
    ("PATCH", r"/lessons/[^/]+/metadata"),
    ("PUT", r"/secrets/.*"),
    ("POST", r"/settings/connections.*"),
    ("POST", r"/settings/readonly-key"),
    ("PUT", r"/settings/telegram"),
    ("POST", r"/calendar/import"),
    ("POST", r"/settings/questions/import"),
]

LESSON_DELETE = re.compile(r"^/lessons/(\d+)$")


def _data_dir() -> str:
    return os.path.abspath(os.path.expanduser(os.environ.get("RT_DATA_DIR") or "~/.rt"))


def _app_port() -> int:
    for value in (os.environ.get("RT_API_PORT"), _read(os.path.join(_data_dir(), "api-port"))):
        try:
            port = int((value or "").strip())
            if 0 < port < 65536:
                return port
        except ValueError:
            pass
    return DEFAULT_PORT


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _api_path(path: str) -> str:
    """Accetta '/lessons', 'lessons' o '/api/v1/lessons' e restituisce il percorso sotto /api/v1."""
    path = "/" + path.strip().lstrip("/")
    return path[len("/api/v1"):] or "/" if path.startswith("/api/v1/") or path == "/api/v1" else path


def check_policy(method: str, path: str, confirm: bool, mode: str) -> Optional[str]:
    """None se la richiesta si può fare, altrimenti il motivo del rifiuto."""
    method = method.upper()
    sub = _api_path(path).split("?", 1)[0]
    for m, pattern in BLOCKED:
        if method == m and re.fullmatch(pattern, sub):
            return f"{method} {sub} è bloccato dal server MCP (operazione riservata all'utente)."
    if mode == "readonly" and method not in ("GET", "HEAD"):
        return f"Modalità sola lettura (RT_MCP_MODE=readonly): {method} {sub} non è permesso."
    if not confirm:
        for m, pattern in CONFIRM:
            if method == m and re.fullmatch(pattern, sub):
                return (f"{method} {sub} cancella o sovrascrive dati: ripeti con confirm=true "
                        "solo se è proprio quello che vuoi provare.")
    return None


class RTClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base = (base_url or os.environ.get("RT_MCP_BASE_URL") or f"http://127.0.0.1:{_app_port()}").rstrip("/")
        self.token = token if token is not None else self._token_from_env()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.session_ready = False

    @staticmethod
    def _token_from_env() -> Optional[str]:
        token = os.environ.get("RT_API_TOKEN", "").strip()
        if token:
            return token
        path = os.path.expanduser(os.environ.get("RT_API_TOKEN_FILE") or os.path.join(_data_dir(), "config", "mcp-token"))
        return (_read(path) or "").strip() or None

    # --- accesso -------------------------------------------------------------------------
    def auth_mode(self) -> str:
        if self.token:
            return "token"
        return "sessione (link monouso dell'app)" if self.session_ready else "nessuno ancora"

    def _ensure_auth(self) -> None:
        if self.token or self.session_ready:
            return
        url = self.login_url()
        parsed = urllib.parse.urlparse(url)
        # stesso host dell'API anche se il link usa un nome diverso (localhost/127.0.0.1)
        login = f"{self.base}/login?{parsed.query}"
        try:
            with self.opener.open(urllib.request.Request(login), timeout=30) as resp:
                resp.read()
        except urllib.error.HTTPError:
            pass  # conta solo il cookie della sessione (la pagina dopo il redirect può mancare)
        if not self._csrf():
            raise RuntimeError("Sessione non aperta: il link monouso non è stato accettato.")
        self.session_ready = True

    def _csrf(self) -> str:
        for cookie in self.jar:
            if cookie.name == "rt_csrf":
                return cookie.value
        return ""

    def login_url(self) -> str:
        """Link monouso (5 minuti) per aprire la web app già autenticata."""
        if self.token:
            data = self._raw("POST", "/auth/login-link", body=b"{}", content_type="application/json")
            payload = json.loads(data[2] or b"{}")
            url = payload.get("url") or ""
            if url:
                return url
            raise RuntimeError(f"Risposta inattesa da /auth/login-link: {payload}")
        return self._login_url_from_app()

    def _login_url_from_app(self) -> str:
        # con l'API spenta 'rt web' avvierebbe un server nuovo invece di dare il link
        if not self._reachable():
            raise RuntimeError(f"RT non risponde su {self.base}: aprilo (o avvia i servizi) e riprova.")
        command = _rt_command()
        if not command:
            raise RuntimeError(
                "Nessun accesso all'API: imposta RT_API_TOKEN (o il file ~/.rt/config/mcp-token) "
                "oppure RT_MCP_RT_COMMAND con il comando 'rt' dell'app.")
        env = dict(os.environ, RT_DATA_DIR=_data_dir(), PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run(command + ["web", "--no-browser", "--port", str(urllib.parse.urlparse(self.base).port or DEFAULT_PORT)],
                             capture_output=True, text=True, timeout=120, env=env, cwd=_data_dir())
        match = re.search(r"https?://\S+/login\?code=[\w\-]+", out.stdout + out.stderr)
        if not match:
            tail = (out.stdout + out.stderr).strip()[-800:]
            raise RuntimeError(f"Il comando dell'app non ha dato un link di accesso (RT è avviato?). Uscita: {tail}")
        return match.group(0)

    # --- richieste -----------------------------------------------------------------------
    def _reachable(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/api/v1/health", timeout=5):
                return True
        except Exception:  # noqa: BLE001
            return False

    def _raw(self, method: str, path: str, query: Optional[Dict[str, Any]] = None, body: Optional[bytes] = None,
             content_type: Optional[str] = None, timeout: float = 120,
             root: bool = False) -> Tuple[int, Dict[str, str], bytes]:
        # "/openapi.json" e gli altri percorsi fuori da /api/v1 si chiedono con root=True
        sub = path if root else _api_path(path)
        url = f"{self.base}{sub}" if root else f"{self.base}/api/v1{sub}"
        if query:
            pairs = [(k, ("true" if item else "false") if isinstance(item, bool) else str(item))
                     for k, v in query.items() for item in (v if isinstance(v, list) else [v])]
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(pairs)
        if sub != "/health" and not sub.startswith("/auth/login-link"):
            self._ensure_auth()
        headers = {"Accept": "application/json, */*"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif method.upper() not in ("GET", "HEAD"):
            headers["X-CSRF-Token"] = self._csrf()
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and not self.token and self.session_ready:
                self.session_ready = False  # sessione scaduta: una nuova al prossimo giro
            return exc.code, dict(exc.headers.items()), exc.read()

    def request(self, method: str, path: str, query: Optional[Dict[str, Any]] = None, body: Any = None,
                timeout: float = 120) -> Tuple[int, Dict[str, str], bytes]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        return self._raw(method, path, query, data, "application/json" if data is not None else None, timeout)

    def upload(self, path: str, fields: Dict[str, Any], files: Dict[str, List[str]],
               timeout: float = 600) -> Tuple[int, Dict[str, str], bytes]:
        boundary = uuid.uuid4().hex
        parts: List[bytes] = []
        for name, value in (fields or {}).items():
            for item in (value if isinstance(value, list) else [value]):
                text = json.dumps(item) if isinstance(item, (bool, dict)) else str(item)
                if isinstance(item, bool):
                    text = "true" if item else "false"
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{text}\r\n'.encode())
        for name, paths in (files or {}).items():
            for p in (paths if isinstance(paths, list) else [paths]):
                p = os.path.expanduser(p)
                with open(p, "rb") as f:
                    content = f.read()
                ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
                filename = os.path.basename(p).replace('"', "")
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                             f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self._raw("POST", path, None, b"".join(parts), f"multipart/form-data; boundary={boundary}", timeout)


def _rt_command() -> Optional[List[str]]:
    explicit = os.environ.get("RT_MCP_RT_COMMAND", "").strip()
    if explicit:
        return shlex.split(explicit)
    plist = os.path.expanduser("~/Library/LaunchAgents/com.atturk.rt.api.plist")
    try:
        with open(plist, "rb") as f:
            args = plistlib.load(f).get("ProgramArguments") or []
    except (OSError, plistlib.InvalidFileException):
        return None
    # [python, .../bin/rt, "api", "--service", ...]: servono i primi due
    return list(args[:2]) if len(args) >= 2 else None


# --- formattazione delle risposte ----------------------------------------------------------
def _filename(headers: Dict[str, str], fallback: str) -> str:
    disposition = next((v for k, v in headers.items() if k.lower() == "content-disposition"), "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition) or re.search(r'filename="?([^";]+)', disposition)
    name = urllib.parse.unquote(m.group(1)) if m else fallback
    return re.sub(r"[\\/:]", "_", name)


def _save_binary(headers: Dict[str, str], data: bytes, fallback: str, sub: str = "downloads") -> str:
    folder = os.path.join(_data_dir(), "mcp", sub)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{time.strftime('%Y%m%d-%H%M%S')} {_filename(headers, fallback)}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def describe(status: int, headers: Dict[str, str], data: bytes, elapsed: float, fallback: str = "file") -> str:
    ctype = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    head = f"HTTP {status} in {elapsed:.2f} s"
    if not data:
        text = ""
    elif "json" in ctype or (data[:1] in (b"{", b"[") and "text/html" not in ctype):
        try:
            text = json.dumps(json.loads(data), ensure_ascii=False, indent=1)
        except ValueError:
            text = data.decode("utf-8", "replace")
    elif ctype.startswith("text/") and "html" not in ctype:
        text = data.decode("utf-8", "replace")
    else:
        path = _save_binary(headers, data, fallback)
        return f"{head}\n{ctype or 'binario'}, {len(data)} byte, salvato in: {path}"
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"\n… (troncato: {len(text)} caratteri in tutto; usa filtri o paginazione)"
    return f"{head}\n{text}"


def _tail(path: str, lines: int) -> List[str]:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block, data = 64 * 1024, b""
        while size > 0 and data.count(b"\n") <= lines:
            step = min(block, size)
            size -= step
            f.seek(size)
            data = f.read(step) + data
    return data.decode("utf-8", "replace").splitlines()[-lines:]


def read_logs(service: str = "all", lines: int = 100, contains: str = "", since: str = "") -> str:
    names = LOG_FILES if service == "all" else (service,)
    if any(n not in LOG_FILES for n in names):
        return f"Servizio sconosciuto: {service} (disponibili: all, {', '.join(LOG_FILES)})"
    lines = max(1, min(int(lines or 100), 2000))
    out = []
    for name in names:
        path = os.path.join(_data_dir(), "logs", f"{name}.log")
        if not os.path.isfile(path):
            out.append(f"== {name}.log: assente")
            continue
        rows = _tail(path, lines * 20 if (contains or since) else lines)
        if since:
            # le righe con data e ora (AAAA-MM-GG HH:MM:SS) si confrontano come testo
            rows = [r for r in rows if not re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", r) or r[:len(since)] >= since]
        if contains:
            rows = [r for r in rows if contains.lower() in r.lower()]
        rows = rows[-lines:]
        out.append(f"== {name}.log ({len(rows)} righe)\n" + "\n".join(rows))
    text = "\n\n".join(out)
    return text if len(text) <= MAX_TEXT else "…\n" + text[-MAX_TEXT:]


# --- strumenti -------------------------------------------------------------------------------
class Tools:
    def __init__(self, client: Optional[RTClient] = None, mode: Optional[str] = None):
        self.client = client or RTClient()
        self.mode = (mode or os.environ.get("RT_MCP_MODE") or "full").strip().lower()
        self._openapi: Optional[Dict[str, Any]] = None

    def definitions(self) -> List[Dict[str, Any]]:
        obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}  # noqa: E731
        confirm = {"type": "boolean", "description": "true per operazioni che cancellano o sovrascrivono dati"}
        return [
            {"name": "rt_status", "description": "Stato di RT: salute dell'API, versione, cartelle, worker, job attivi e costi LLM totali.",
             "inputSchema": obj({})},
            {"name": "rt_endpoints", "description": "Cerca fra gli endpoint dell'API (dallo schema OpenAPI dell'app avviata). "
             "Con 'detail' mostra parametri e corpo di un endpoint preciso (es. 'POST /lessons').",
             "inputSchema": obj({"search": {"type": "string", "description": "parole nel percorso o nella descrizione"},
                                 "detail": {"type": "string", "description": "METODO /percorso di cui mostrare lo schema"}})},
            {"name": "rt_request", "description": "Chiama l'API di RT (percorsi sotto /api/v1, es. '/lessons'). Risposte JSON come testo; "
             "file binari salvati in ~/.rt/mcp/downloads. Le operazioni distruttive richiedono confirm=true; eliminare una "
             "lezione ne salva prima lo ZIP completo.",
             "inputSchema": obj({"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                                 "path": {"type": "string"},
                                 "query": {"type": "object", "description": "parametri della query string"},
                                 "body": {"description": "corpo JSON"},
                                 "confirm": confirm,
                                 "timeout_s": {"type": "number"}}, ("method", "path"))},
            {"name": "rt_upload", "description": "POST multipart con file locali (import di audio con POST /lessons, ZIP con "
             "/lessons/import-zip, fonti con /lessons/{id}/sources, immagini...). Per una lezione di prova senza costi usa "
             "fields.mock=true.",
             "inputSchema": obj({"path": {"type": "string"},
                                 "fields": {"type": "object", "description": "campi del form (liste per i campi ripetuti)"},
                                 "files": {"type": "object", "description": "campo -> percorso o lista di percorsi locali"},
                                 "confirm": confirm}, ("path",))},
            {"name": "rt_wait_job", "description": "Aspetta che un job finisca (o si fermi su una decisione) e ne riporta stato, "
             "durata, errore ed eventi recenti.",
             "inputSchema": obj({"job_id": {"type": "string"},
                                 "timeout_s": {"type": "number", "description": "predefinito 600, massimo 3600"}}, ("job_id",))},
            {"name": "rt_logs", "description": "Ultime righe dei log di RT (api, worker, desktop, browser-install o all), "
             "filtrabili per testo e per data e ora ('since': 'AAAA-MM-GG HH:MM:SS', anche parziale).",
             "inputSchema": obj({"service": {"type": "string", "enum": ["all", *LOG_FILES]},
                                 "lines": {"type": "integer"}, "contains": {"type": "string"}, "since": {"type": "string"}})},
            {"name": "rt_export_lesson", "description": "Salva lo ZIP di una lezione in ~/.rt/mcp/exports (scope all: tutto, audio compreso).",
             "inputSchema": obj({"lesson_id": {"type": "integer"},
                                 "scope": {"type": "string", "enum": ["all", "final", "sources"]}}, ("lesson_id",))},
            {"name": "rt_browser_login", "description": "Link monouso (5 minuti) per aprire la web app già autenticata: "
             "passalo a browser_navigate del server MCP di Playwright per provare l'interfaccia e leggere la console.",
             "inputSchema": obj({})},
        ]

    def call(self, name: str, args: Dict[str, Any]) -> str:
        handler = getattr(self, "t_" + name.removeprefix("rt_"), None) if name.startswith("rt_") else None
        if handler is None:
            raise ValueError(f"Strumento sconosciuto: {name}")
        return handler(**(args or {}))

    # ---
    def _json(self, method: str, path: str, **kw: Any) -> Any:
        status, _h, data = self.client.request(method, path, **kw)
        if status >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {status} {data[:300].decode('utf-8', 'replace')}")
        return json.loads(data or b"null")

    def t_status(self) -> str:
        out: Dict[str, Any] = {"base_url": self.client.base, "mode": self.mode, "data_dir": _data_dir()}
        try:
            out["health"] = self._json("GET", "/health")
        except Exception as exc:  # noqa: BLE001
            out["health"] = f"API non raggiungibile: {exc}"
            return json.dumps(out, ensure_ascii=False, indent=1)
        for key, path, q in (("system", "/system/info", None), ("workers", "/workers", None),
                             ("active_jobs", "/jobs", {"limit": 20}), ("costs", "/costs", None)):
            try:
                value = self._json("GET", path, query=q)
                if key == "active_jobs":
                    items = value.get("items", value) if isinstance(value, dict) else value
                    value = [{k: j.get(k) for k in ("id", "type", "state", "lesson_id", "created_at")}
                             for j in items if isinstance(j, dict) and j.get("state") not in TERMINAL_STATES]
                if key == "costs" and isinstance(value, dict):
                    value = {k: v for k, v in value.items() if not isinstance(v, list)}
                out[key] = value
            except Exception as exc:  # noqa: BLE001
                out[key] = f"errore: {exc}"
        out["auth"] = self.client.auth_mode()
        return json.dumps(out, ensure_ascii=False, indent=1)[:MAX_TEXT]

    def _schema(self) -> Dict[str, Any]:
        if self._openapi is None:
            status, _h, data = self.client._raw("GET", "/openapi.json", root=True)
            self._openapi = json.loads(data) if status == 200 else {}
            if not self._openapi:
                local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "openapi.json")
                self._openapi = json.loads(_read(local) or "{}")
        return self._openapi

    def t_endpoints(self, search: str = "", detail: str = "") -> str:
        schema = self._schema()
        paths = schema.get("paths", {})
        if detail:
            method, _, path = detail.strip().partition(" ")
            full = "/api/v1" + _api_path(path)
            op = paths.get(full, {}).get(method.lower())
            if not op:
                return f"Endpoint non trovato: {method.upper()} {full}"
            info = {k: op.get(k) for k in ("summary", "description", "parameters", "requestBody") if op.get(k)}
            refs = set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(info)))
            comps = schema.get("components", {}).get("schemas", {})
            info["schemas"] = {r: comps.get(r) for r in sorted(refs)}
            text = json.dumps(info, ensure_ascii=False, indent=1)
            return text[:MAX_TEXT]
        words = [w.lower() for w in search.split()]
        rows = []
        for path, ops in paths.items():
            for method, op in ops.items():
                line = f"{method.upper():6} {path.removeprefix('/api/v1')}  {op.get('summary', '')}"
                if all(w in line.lower() for w in words):
                    blocked = check_policy(method, path, False, self.mode)
                    rows.append(line + ("  [richiede confirm]" if blocked and "confirm" in blocked else
                                        "  [bloccato]" if blocked else ""))
        return f"{len(rows)} endpoint\n" + "\n".join(rows)

    def t_request(self, method: str, path: str, query: Optional[Dict[str, Any]] = None, body: Any = None,
                  confirm: bool = False, timeout_s: float = 120) -> str:
        refused = check_policy(method, path, confirm, self.mode)
        if refused:
            return "RIFIUTATO: " + refused
        notes = ""
        sub = _api_path(path).split("?", 1)[0]
        lesson = LESSON_DELETE.match(sub)
        if method.upper() == "DELETE" and lesson:
            saved = self.t_export_lesson(int(lesson.group(1)), "all")
            if not saved.startswith("Esportata"):
                return f"RIFIUTATO: export prima dell'eliminazione non riuscito, lezione non eliminata.\n{saved}"
            notes = saved + "\n"
        start = time.monotonic()
        status, headers, data = self.client.request(method, path, query, body, timeout=float(timeout_s))
        return notes + describe(status, headers, data, time.monotonic() - start, os.path.basename(sub) or "file")

    def t_upload(self, path: str, fields: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None,
                 confirm: bool = False) -> str:
        refused = check_policy("POST", path, confirm, self.mode)
        if refused:
            return "RIFIUTATO: " + refused
        missing = [p for v in (files or {}).values() for p in (v if isinstance(v, list) else [v])
                   if not os.path.isfile(os.path.expanduser(p))]
        if missing:
            return "File non trovati: " + ", ".join(missing)
        start = time.monotonic()
        status, headers, data = self.client.upload(path, fields or {}, files or {})
        return describe(status, headers, data, time.monotonic() - start)

    def t_wait_job(self, job_id: str, timeout_s: float = 600) -> str:
        deadline = time.monotonic() + max(1.0, min(float(timeout_s), 3600.0))
        start, job = time.monotonic(), {}
        while True:
            job = self._json("GET", f"/jobs/{job_id}")
            if job.get("state") in TERMINAL_STATES or job.get("state") == "waiting_for_decision":
                break
            if time.monotonic() > deadline:
                break
            time.sleep(2)
        try:
            events = self._json("GET", f"/jobs/{job_id}/events/list")
            items = events.get("items", events) if isinstance(events, dict) else events
            events = items[-15:] if isinstance(items, list) else items
        except Exception as exc:  # noqa: BLE001
            events = f"eventi non disponibili: {exc}"
        summary = {k: job.get(k) for k in ("id", "type", "state", "lesson_id", "progress", "error", "decision",
                                           "created_at", "started_at", "finished_at", "result")}
        summary["waited_s"] = round(time.monotonic() - start, 1)
        summary["timed_out"] = job.get("state") not in TERMINAL_STATES | {"waiting_for_decision"}
        summary["recent_events"] = events
        return json.dumps(summary, ensure_ascii=False, indent=1)[:MAX_TEXT]

    def t_logs(self, service: str = "all", lines: int = 100, contains: str = "", since: str = "") -> str:
        return read_logs(service, lines, contains, since)

    def t_export_lesson(self, lesson_id: int, scope: str = "all") -> str:
        start = time.monotonic()
        status, headers, data = self.client.request("GET", f"/lessons/{int(lesson_id)}/export",
                                                    {"format": "zip", "scope": scope}, timeout=900)
        if status != 200 or not data:
            return f"Export non riuscito: HTTP {status} {data[:300].decode('utf-8', 'replace')}"
        path = _save_binary(headers, data, f"lezione-{lesson_id}.zip", "exports")
        return f"Esportata la lezione {lesson_id} ({len(data)} byte, {time.monotonic() - start:.1f} s): {path}"

    def t_browser_login(self) -> str:
        return self.client.login_url()


# --- protocollo MCP (JSON-RPC 2.0, un messaggio per riga su stdin/stdout) ------------------
def handle(tools: Tools, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None  # notifiche (es. notifications/initialized)
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        result: Any = {"protocolVersion": requested, "capabilities": {"tools": {}},
                       "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                       "instructions": "Strumenti per usare un'installazione di RT avviata. Parti da rt_status e "
                                       "rt_endpoints; per l'interfaccia usa rt_browser_login con Playwright."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools.definitions()}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            text, error = tools.call(params.get("name", ""), params.get("arguments") or {}), False
        except Exception as exc:  # noqa: BLE001
            text, error = f"{type(exc).__name__}: {exc}", True
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Metodo non supportato: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> int:
    tools = Tools()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: Optional[Dict[str, Any]] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON non valido"}}
        else:
            reply = handle(tools, message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
