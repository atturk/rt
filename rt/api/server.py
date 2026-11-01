"""
rt.api.server
Avvio dell'API con Uvicorn ('rt api'). Per default ascolta solo su 127.0.0.1: un host
diverso va chiesto in modo esplicito e produce un avviso, perché espone l'API alla rete.
"""
from typing import Callable, List, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEV_SPA_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def prepare(reset_token: bool = False, no_auth: bool = False, host: str = DEFAULT_HOST,
            say: Callable[[str], None] = print) -> bool:
    """Crea/aggiorna il DB e il token. False se l'avvio non è possibile."""
    from rt.api import auth
    from rt.db.engine import get_database
    db = get_database(create=True)
    if db is None:
        say("❌ Database non disponibile: l'API ne ha bisogno (controlla RT_DATABASE_URL o database_url).")
        return False
    if no_auth and host not in LOOPBACK:
        say("❌ --no-auth è permesso solo su 127.0.0.1.")
        return False
    token = auth.reset_token(db) if reset_token else auth.ensure_token(db)
    if token:
        say("🔑 Token API (mostrato una sola volta, conservalo):")
        say(f"   {token}")
        say("   Nella pagina /docs premi 'Authorize' e incollalo. Per generarne uno nuovo: rt api --reset-token")
    return True


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, reset_token: bool = False,
        no_auth: bool = False, dev_cors: bool = False, say: Callable[[str], None] = print,
        service: bool = False) -> int:
    import uvicorn
    from rt.api.app import create_app
    if host not in LOOPBACK:
        say(f"⚠️  L'API sarà raggiungibile da altri dispositivi su {host}:{port}. Proteggi il token.")
    # Come servizio (launchd, docker) il token non va nel log: si entra con il link monouso
    # di 'rt web' oppure si genera un token da mostrare con 'rt api --reset-token'.
    prepare_say = say if not service else _without_token(say)
    if not prepare(reset_token=reset_token, no_auth=no_auth, host=host, say=prepare_say):
        return 1
    origins: Optional[List[str]] = DEV_SPA_ORIGINS if dev_cors else None
    app = create_app(auth_disabled=no_auth, cors_origins=origins)
    shown = f"[{host}]" if ":" in host else host
    say(f"🚀 API RT su http://{shown}:{port}/api/v1  ·  documentazione: http://{shown}:{port}/docs")
    if no_auth:
        say("⚠️  Autenticazione disattivata (--no-auth).")
    # Gli stream SSE (canale live della web app) restano aperti: allo stop si chiudono dopo pochi secondi.
    uvicorn.run(app, host=host, port=port, log_level="info", timeout_graceful_shutdown=5,
                log_config=log_config())
    return 0


# Richieste che la web app ripete da sola ogni pochi secondi: riuscite non dicono nulla e
# riempivano api.log (il 70% delle righe). Errori e lentezze restano: cambiano lo status.
POLLING_PATHS = ("/api/v1/jobs", "/api/v1/workers", "/api/v1/system/update")
POLLING_SUFFIXES = ("/classifier",)


class PollingAccessFilter:
    """Toglie dall'access log di uvicorn i GET di polling andati a buon fine (200/304)."""

    def filter(self, record) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        _client, method, full_path, _version, status = args[:5]
        if method != "GET" or status not in (200, 304):
            return True
        path = str(full_path).split("?", 1)[0]
        return not (path in POLLING_PATHS or (path.startswith("/api/v1/lessons/") and path.endswith(POLLING_SUFFIXES)))


def log_config() -> dict:
    import copy
    from uvicorn.config import LOGGING_CONFIG
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["polling"] = {"()": "rt.api.server.PollingAccessFilter"}
    config["handlers"]["access"].setdefault("filters", []).append("polling")
    return config


def _without_token(say: Callable[[str], None]) -> Callable[[str], None]:
    """Filtra le righe di prepare() che mostrano il token (servizi: il log non è un segreto)."""
    hidden = {"shown": False}

    def _say(line: str) -> None:
        if line.startswith("🔑 Token API"):
            hidden["shown"] = True
            say("🔑 Token API creato (non mostrato nel log): entra con 'rt web', oppure 'rt api --reset-token' per vederne uno nuovo.")
            return
        if hidden["shown"] and (line.startswith("   ")):
            return
        say(line)
    return _say
