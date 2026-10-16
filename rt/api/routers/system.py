"""Stato del servizio e sessione della SPA."""
from typing import Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from rt.api import auth, schemas
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


class CompactAudioPreview(BaseModel):
    file_convertibili: int
    bytes_convertibili: int
    file_orfani: int
    bytes_orfani: int
    spazio_stimato_liberato: int


@router.get("/system/compact-audio/preview", response_model=CompactAudioPreview,
            summary="Stima dello spazio liberato convertendo wav/flac e cancellando audio orfani")
def preview_compact_audio_endpoint(_actor: Actor) -> CompactAudioPreview:
    from rt.services.audio_compaction import preview_compact_audio
    return CompactAudioPreview(**preview_compact_audio())


@router.post("/system/compact-audio", response_model=schemas.JobAccepted, status_code=202,
             summary="Avvia il job per convertire in m4a i wav/flac e cancellare gli audio uniti orfani")
def start_compact_audio(actor: Actor):
    from rt.api.jobs import enqueue_job
    return enqueue_job("compact_audio", None, {}, actor)


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


class UpdateProgress(BaseModel):
    phase: str = Field(description="idle, downloading, installing o error")
    downloaded: int = Field(0, description="Byte già scaricati")
    total: Optional[int] = Field(None, description="Dimensione dell'installer in byte")
    error: Optional[str] = None
    target: Optional[str] = Field(None, description="Versione in installazione")


class AppUpdate(BaseModel):
    supported: bool = Field(description="True per l'app installata (RT.app, setup per Windows): si aggiorna da qui. "
                                        "False per install.sh, git o Docker: 'rt -u'")
    current: str
    latest: Optional[str] = Field(None, description="Ultima versione stabile pubblicata (le beta non contano)")
    available: bool = Field(description="C'è una versione stabile più recente con l'installer per questo sistema")
    asset_name: Optional[str] = None
    asset_size: Optional[int] = None
    notes_url: Optional[str] = None
    releases_url: str = Field(description="Pagina delle release: le beta si scaricano a mano da qui")
    error: Optional[str] = Field(None, description="Controllo non riuscito (rete, GitHub)")
    progress: UpdateProgress


def _app_update(refresh: bool) -> AppUpdate:
    from rt.core import app_update
    info = app_update.cached_check(refresh=refresh)
    data = app_update.as_dict(info)
    data.pop("checked_at", None)
    data.pop("asset_url", None)
    return AppUpdate(**data, releases_url=app_update.RELEASES_PAGE,
                     progress=UpdateProgress(**app_update.STATE.snapshot()))


@router.get("/system/update", response_model=AppUpdate,
            summary="Aggiornamento dell'app: ultima versione stabile e stato dell'installazione")
def system_update(_actor: Actor, refresh: bool = False) -> AppUpdate:
    return _app_update(refresh)


@router.post("/system/update", response_model=AppUpdate, status_code=202,
             summary="Scarica e installa l'ultima versione stabile (solo app installata)",
             responses={409: {"model": ErrorResponse}})
def start_system_update(_actor: Actor) -> AppUpdate:
    from rt.core import app_update
    info = app_update.cached_check(refresh=True)
    if not info.supported:
        raise ApiError(409, "update_unsupported", "Questa installazione si aggiorna da terminale con 'rt -u'.")
    if not info.available:
        raise ApiError(409, "no_update", info.error or "Nessuna versione stabile più recente da installare.")
    if not app_update.start(info):
        raise ApiError(409, "update_running", "Un aggiornamento è già in corso.")
    return _app_update(False)


class ChangelogGroup(BaseModel):
    title: str
    items: list[str]


class ChangelogSection(BaseModel):
    version: str
    date: str
    groups: list[ChangelogGroup]


@router.get("/system/changelog", response_model=list[ChangelogSection], summary="Novità delle versioni installate")
def system_changelog(_actor: Actor) -> list[ChangelogSection]:
    from rt.core.changelog import read_changelog
    from rt.core.config import _default_project_root
    return [ChangelogSection(**section) for section in read_changelog(_default_project_root())]


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


class TailnetInfo(BaseModel):
    origin: Optional[str] = Field(None, description="Indirizzo di RT nella tailnet (https://nome-mac.tailnet.ts.net), "
                                                    "None senza Tailscale")
    serve: bool = Field(False, description="Tailscale Serve inoltra già l'indirizzo a RT")
    funnel: bool = Field(False, description="L'indirizzo è pubblico su Internet (Tailscale Funnel)")


@router.get("/system/tailnet", response_model=TailnetInfo,
            summary="Indirizzo di RT per gli altri dispositivi della tailnet (es. iPhone)")
def system_tailnet(request: Request, _actor: Actor) -> TailnetInfo:
    from rt.core.tailscale import tailnet_address
    server = request.scope.get("server") or (None, None)
    port = server[1] or request.url.port or 8765
    found = tailnet_address(int(port))
    if found is None:
        return TailnetInfo()
    return TailnetInfo(origin=found.origin, serve=found.serve, funnel=found.funnel)


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
