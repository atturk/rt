"""Stato del servizio e sessione della SPA."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from rt.api import auth
from rt.api.deps import Actor
from rt.api.errors import ApiError, ErrorResponse

router = APIRouter(tags=["sistema"])


class Health(BaseModel):
    status: str = "ok"
    version: str
    database: bool


@router.get("/health", response_model=Health, summary="Stato del servizio (senza autenticazione)")
def health() -> Health:
    from rt.core.config import _default_project_root
    from rt.core.version import get_current_version
    from rt.db.engine import get_database
    return Health(version=get_current_version(_default_project_root()), database=get_database() is not None)


class SystemInfo(BaseModel):
    version: str = Field(description="Versione di RT installata (come 'rt -v')")
    prerelease: bool = Field(description="True per una beta o release candidate (es. 4.1.0b2)")
    update_channel: str = Field(description="Canale di aggiornamento: stable o beta ('rt -u --beta' / '--stable')")
    install_dir: str = Field(description="Cartella del codice di RT")
    data_dir: str = Field(description="Cartella dati (~/.rt o RT_DATA_DIR): canale, rt.db, media")
    config_dir: str = Field(description="Cartella config/ in uso")
    python_version: str
    platform: str


class CacheUsage(BaseModel):
    entries: int = Field(ge=0, description="Numero di file nella cache")
    bytes: int = Field(ge=0, description="Dimensione dei file in byte")


class CacheInfo(BaseModel):
    audio: CacheUsage
    waveform: CacheUsage
    total: CacheUsage


@router.get("/system/cache", response_model=CacheInfo, summary="Spazio occupato dalla cache audio e dalle forme d’onda")
def system_cache(_actor: Actor) -> CacheInfo:
    from rt.services.audio_service import cache_info
    return CacheInfo(**cache_info())


@router.delete("/system/cache", response_model=CacheInfo, summary="Svuota la cache e restituisce lo spazio liberato")
def clear_system_cache(_actor: Actor) -> CacheInfo:
    from rt.services.audio_service import clear_cache
    return CacheInfo(**clear_cache())


@router.get("/system/info", response_model=SystemInfo, summary="Versione, canale di aggiornamento e cartelle di RT")
def system_info(_actor: Actor) -> SystemInfo:
    import platform
    from rt.core import paths
    from rt.core.config import _default_project_root
    from rt.core.version import get_current_version, get_update_channel, is_prerelease
    root = _default_project_root()
    version = get_current_version(root)
    return SystemInfo(version=version, prerelease=is_prerelease(version), update_channel=get_update_channel(),
                      install_dir=str(root), data_dir=str(paths.data_dir()), config_dir=str(paths.config_dir(root)),
                      python_version=platform.python_version(),
                      platform=f"{platform.system()} {platform.release()} ({platform.machine()})")


class SessionRequest(BaseModel):
    token: str = Field(description="Token API mostrato da 'rt api'")


class SessionInfo(BaseModel):
    authenticated: bool = True
    csrf_token: str = Field(description="Da ripetere nell'header X-CSRF-Token per POST/PUT/DELETE")


@router.post("/auth/session", response_model=SessionInfo, summary="Apre una sessione con cookie (per la SPA)",
             responses={401: {"model": ErrorResponse}})
def create_session(body: SessionRequest, request: Request, response: Response) -> SessionInfo:
    if not request.app.state.auth_disabled and not auth.verify_token(body.token):
        raise ApiError(401, "unauthorized", "Token non valido.")
    return SessionInfo(csrf_token=open_browser_session(request, response))


def open_browser_session(request: Request, response: Response) -> str:
    """Crea la sessione e imposta i cookie di sessione e CSRF; restituisce il valore CSRF."""
    session_id = auth.create_session()
    csrf = auth.secrets.token_urlsafe(24)
    max_age = auth.SESSION_DAYS * 86400
    secure = request.url.scheme == "https"
    response.set_cookie(auth.SESSION_COOKIE, session_id, max_age=max_age, httponly=True,
                        samesite="strict", secure=secure, path="/")
    response.set_cookie(auth.CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
                        samesite="strict", secure=secure, path="/")
    return csrf


class LoginLink(BaseModel):
    url: str = Field(description="Link da aprire nel browser: apre la sessione una sola volta")
    expires_in: int = Field(description="Secondi di validità")


@router.post("/auth/login-link", response_model=LoginLink, summary="Crea un link di accesso monouso per il browser",
             responses={401: {"model": ErrorResponse}})
def create_login_link(request: Request, _actor: Actor) -> LoginLink:
    code = auth.create_login_code()
    return LoginLink(url=f"{str(request.base_url).rstrip('/')}/login?code={code}",
                     expires_in=auth.LOGIN_CODE_SECONDS)


@router.delete("/auth/session", status_code=204, summary="Chiude la sessione della SPA")
def delete_session(request: Request, _actor: Actor) -> Response:
    auth.drop_session(request.cookies.get(auth.SESSION_COOKIE, ""))
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(auth.CSRF_COOKIE, path="/")
    return response


class Me(BaseModel):
    actor: str


@router.get("/auth/me", response_model=Me, summary="Verifica le credenziali")
def me(actor: Actor) -> Me:
    return Me(actor=actor)
