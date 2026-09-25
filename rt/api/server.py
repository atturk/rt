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
        no_auth: bool = False, dev_cors: bool = False, say: Callable[[str], None] = print) -> int:
    import uvicorn
    from rt.api.app import create_app
    if host not in LOOPBACK:
        say(f"⚠️  L'API sarà raggiungibile da altri dispositivi su {host}:{port}. Proteggi il token.")
    if not prepare(reset_token=reset_token, no_auth=no_auth, host=host, say=say):
        return 1
    origins: Optional[List[str]] = DEV_SPA_ORIGINS if dev_cors else None
    app = create_app(auth_disabled=no_auth, cors_origins=origins)
    shown = f"[{host}]" if ":" in host else host
    say(f"🚀 API RT su http://{shown}:{port}/api/v1  ·  documentazione: http://{shown}:{port}/docs")
    if no_auth:
        say("⚠️  Autenticazione disattivata (--no-auth).")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0
