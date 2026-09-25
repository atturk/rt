"""
rt.api.auth
Autenticazione a utente singolo (RT4-E1).

- Un token API generato al primo avvio di 'rt api' e mostrato una sola volta; nel DB resta
  solo l'hash (sha256 con salt, tabella settings, chiave "api.auth").
- Client (script, Swagger UI): header Authorization: Bearer <token>.
- SPA: POST /api/v1/auth/session con il token imposta un cookie di sessione HttpOnly,
  SameSite=Strict, e un cookie CSRF leggibile; le richieste che modificano dati con il
  cookie devono ripetere il valore CSRF nell'header X-CSRF-Token (double submit).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rt.api.errors import ApiError

AUTH_KEY = "api.auth"
SESSIONS_KEY = "api.sessions"
SESSION_COOKIE = "rt_session"
CSRF_COOKIE = "rt_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_DAYS = 30
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

bearer_scheme = HTTPBearer(auto_error=False, description="Token mostrato da 'rt api' al primo avvio")


def _db():
    from rt.db.engine import get_database
    db = get_database()
    if db is None:
        raise ApiError(503, "database_unavailable", "Database non disponibile.")
    return db


def _hash(value: str, salt: str) -> str:
    return hashlib.sha256((salt + value).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def has_token(db=None) -> bool:
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(db or _db()) as session:
        return bool(SettingRepository(session).get(AUTH_KEY))


def reset_token(db=None) -> str:
    """Genera un token nuovo (invalida il precedente e le sessioni) e lo restituisce."""
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    token = secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    with session_scope(db or _db()) as session:
        repo = SettingRepository(session)
        repo.set(AUTH_KEY, {"salt": salt, "token_hash": _hash(token, salt), "created_at": _now().isoformat()})
        repo.delete(SESSIONS_KEY)
    return token


def ensure_token(db=None) -> Optional[str]:
    """Al primo avvio crea il token e lo restituisce; poi None (esiste già)."""
    return None if has_token(db) else reset_token(db)


def verify_token(token: str) -> bool:
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    if not token:
        return False
    with session_scope(_db()) as session:
        record = SettingRepository(session).get(AUTH_KEY) or {}
    if not record.get("token_hash"):
        return False
    return hmac.compare_digest(_hash(token, record.get("salt", "")), record["token_hash"])


def create_session() -> str:
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    session_id = secrets.token_urlsafe(32)
    now = _now()
    with session_scope(_db()) as session:
        repo = SettingRepository(session)
        sessions = {k: v for k, v in (repo.get(SESSIONS_KEY) or {}).items()
                    if datetime.fromisoformat(v) > now}
        sessions[_hash(session_id, "")] = (now + timedelta(days=SESSION_DAYS)).isoformat()
        repo.set(SESSIONS_KEY, sessions)
    return session_id


def verify_session(session_id: str) -> bool:
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    if not session_id:
        return False
    with session_scope(_db()) as session:
        expires = (SettingRepository(session).get(SESSIONS_KEY) or {}).get(_hash(session_id, ""))
    return bool(expires) and datetime.fromisoformat(expires) > _now()


def drop_session(session_id: str) -> None:
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(_db()) as session:
        repo = SettingRepository(session)
        sessions = dict(repo.get(SESSIONS_KEY) or {})
        if sessions.pop(_hash(session_id or "", ""), None) is not None:
            repo.set(SESSIONS_KEY, sessions)


def require_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    """Restituisce l'attore ("api") o solleva 401/403."""
    if request.app.state.auth_disabled:
        return "api"
    if credentials is not None:
        if credentials.scheme.lower() == "bearer" and verify_token(credentials.credentials):
            return "api"
        raise ApiError(401, "unauthorized", "Token non valido.")
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id and verify_session(session_id):
        if request.method not in SAFE_METHODS:
            header = request.headers.get(CSRF_HEADER, "")
            cookie = request.cookies.get(CSRF_COOKIE, "")
            if not header or not cookie or not hmac.compare_digest(header, cookie):
                raise ApiError(403, "csrf_failed", "Token CSRF mancante o non valido.")
        return "api"
    raise ApiError(401, "unauthorized", "Autenticazione richiesta.")
