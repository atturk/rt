"""
rt.api.readonly_auth
Autenticazione per l'API di sola lettura (AP1):
- Chiave separata di sola lettura salvata nei repository di configurazione
- Servita esclusivamente su 127.0.0.1 (loopback)
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rt.api.auth import _db, _hash, _now, verify_token
from rt.api.errors import ApiError

READONLY_AUTH_KEY = "api.readonly_auth"

readonly_bearer_scheme = HTTPBearer(auto_error=False, description="Chiave di sola lettura per Open WebUI")


# Tailscale Serve e i proxy inoltrano da 127.0.0.1: questi header svelano un client remoto.
FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
                      "x-real-ip", "tailscale-user-login", "tailscale-user-name",
                      "tailscale-user-profile-pic", "tailscale-headers-info")


def _is_loopback(host: str) -> bool:
    """Niente eccezioni per "testclient": i test usano TestClient(client=("127.0.0.1", ...))."""
    if not host:
        return False
    h = host.strip().lower()
    return h in ("127.0.0.1", "localhost", "::1") or h.startswith("127.")


def is_local_request(request: Request) -> bool:
    if not request.client:
        return False
    if any(name in request.headers for name in FORWARDING_HEADERS):
        return False
    return _is_loopback(request.client.host)


def get_readonly_key() -> Optional[str]:
    """Restituisce il token in chiaro se presente nei segreti di RT."""
    import os
    from rt.core.config import load_env_file
    load_env_file()
    val = os.environ.get("RT_READONLY_KEY")
    if val:
        return val.strip() or None
    from rt.security.secrets import default_store_path, is_initialized
    from rt.services import secrets_service
    try:
        if is_initialized():
            store = secrets_service.store(default_store_path())
            s = store.get("RT_READONLY_KEY")
            if s:
                return s.strip() or None
    except Exception:
        pass
    return None


def get_readonly_key_info(db=None) -> Dict[str, Any]:
    """Restituisce le informazioni sulla chiave (con il token in chiaro se presente nei segreti)."""
    from rt.db.repositories import SettingRepository
    from rt.db.session import read_scope

    database = db or _db()
    with read_scope(database) as session:
        record = SettingRepository(session).get(READONLY_AUTH_KEY)

    if not isinstance(record, dict) or not record.get("token_hash"):
        return {"configured": False, "created_at": None, "key_preview": None, "key": None}

    return {
        "configured": True,
        "created_at": record.get("created_at"),
        "key_preview": record.get("key_preview"),
        "key": get_readonly_key(),
    }


def create_readonly_key(db=None) -> str:
    """Genera una nuova chiave di sola lettura, la salva e la conserva anche tra i segreti."""
    import os
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    from rt.services import config_service

    token = "rt_ro_" + secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    preview = f"{token[:8]}…{token[-4:]}"

    database = db or _db()
    with session_scope(database) as session:
        SettingRepository(session).set(
            READONLY_AUTH_KEY,
            {
                "salt": salt,
                "token_hash": _hash(token, salt),
                "created_at": _now().isoformat(),
                "key_preview": preview,
            },
        )
    try:
        config_service.set_secret("RT_READONLY_KEY", token)
    except Exception:
        pass
    os.environ["RT_READONLY_KEY"] = token
    return token


def revoke_readonly_key(db=None) -> bool:
    """Revoca la chiave di sola lettura e cancella il segreto."""
    import os
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    from rt.services import config_service

    database = db or _db()
    with session_scope(database) as session:
        SettingRepository(session).set(READONLY_AUTH_KEY, None)
    try:
        config_service.unset_secret("RT_READONLY_KEY")
    except Exception:
        pass
    os.environ.pop("RT_READONLY_KEY", None)
    return True


def verify_readonly_token(token: str, db=None) -> bool:
    """Verifica se il token corrisponde alla chiave di sola lettura (o al token principale di RT)."""
    if not token:
        return False
    # Il token principale di RT è sempre valido come fallback
    if verify_token(token):
        return True

    from rt.db.repositories import SettingRepository
    from rt.db.session import read_scope

    database = db or _db()
    with read_scope(database) as session:
        record = SettingRepository(session).get(READONLY_AUTH_KEY)

    if not isinstance(record, dict) or not record.get("token_hash"):
        return False

    salt = record.get("salt", "")
    return hmac.compare_digest(_hash(token, salt), record["token_hash"])


def require_readonly_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(readonly_bearer_scheme),
) -> str:
    """Verifica che la richiesta provenga da loopback (127.0.0.1), senza header di inoltro
    (Tailscale Serve, proxy), e abbia una chiave valida. Con l'autenticazione disattivata
    (rt web --no-auth, solo sviluppo) vale come per l'API principale: nessuna chiave."""
    if not is_local_request(request):
        raise ApiError(403, "forbidden_ip", "L'API di sola lettura è accessibile solo da 127.0.0.1, senza proxy.")

    if getattr(request.app.state, "auth_disabled", False):
        return "readonly"

    if credentials is not None and credentials.scheme.lower() == "bearer":
        if verify_readonly_token(credentials.credentials):
            return "readonly"
        raise ApiError(401, "unauthorized", "Chiave di sola lettura non valida.")

    raise ApiError(401, "unauthorized", "Chiave di sola lettura richiesta (header Authorization: Bearer <chiave>).")
