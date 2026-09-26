"""Impostazioni (come 'rt config' e la pagina Impostazioni), segreti e bot Telegram.
Nessuna risposta contiene mai il valore di un segreto: solo "impostato sì/no"."""
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError

router = APIRouter(tags=["impostazioni"])


def _project_root() -> Path:
    from rt.core.config import _default_project_root
    return Path(_default_project_root())


def _call(fn, *args, **kwargs):
    """Gli errori di validazione dei servizi diventano 422 con il loro messaggio."""
    from pydantic import ValidationError
    try:
        return fn(*args, **kwargs)
    except (ValueError, ValidationError) as exc:
        raise ApiError(422, "invalid_setting", str(exc).splitlines()[0] if str(exc) else "Valore non valido.")


# ---------------------------------------------------------------- schemi

class CredentialState(BaseModel):
    name: str
    provider: str = ""
    env_var: str = ""
    set: bool


class ConnectionCredential(BaseModel):
    name: str
    set: bool


class Connection(BaseModel):
    name: str
    provider: str
    base_url: str
    models: List[str]
    credentials: List[ConnectionCredential]


class PhaseAssignment(BaseModel):
    job: str
    label: str
    connection: Optional[str] = None
    model: Optional[str] = None


class Transcription(BaseModel):
    engine: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_set: bool


class TelegramSettings(BaseModel):
    bot_token_set: bool
    chat_id: Optional[str] = None
    topics: Dict[str, int]
    misc_topic_id: Optional[int] = None
    default_channel: str


class WorkerSettings(BaseModel):
    concurrency: int = Field(description="Job in parallelo del worker di 'rt web' (1-4, su lezioni diverse): "
                                         "vale dal prossimo avvio")
    running: int = Field(0, description="Worker attivi ora (uno per job eseguibile insieme)")


class WorkerIn(BaseModel):
    concurrency: int = Field(ge=1, le=4)


class Settings(BaseModel):
    lessons_root: Optional[str] = None
    worker: WorkerSettings
    transcription: Transcription
    telegram: TelegramSettings
    phases: List[PhaseAssignment] = Field(description="Modello assegnato a ciascuna delle sei fasi LLM")
    connections: List[Connection]
    credentials: List[CredentialState]
    pricing: Dict[str, Dict[str, Dict[str, Any]]]
    secrets_encrypted: bool = Field(description="True se i segreti sono nell'archivio cifrato (rt secrets init)")
    data_dir: Optional[str] = Field(None, description="Cartella dati in uso da questo processo: rt.db e media/")
    setup_required: bool = Field(False, description="True se la cartella delle lezioni non è impostata o non esiste: "
                                                    "la SPA apre la configurazione guidata")


class LessonsRootIn(BaseModel):
    path: str


class TranscriptionIn(BaseModel):
    engine: Literal["macparakeet", "custom"]
    base_url: str = ""
    model: str = ""
    api_key: Optional[str] = Field(None, description="Lascia vuoto per non cambiarla")


class TelegramIn(BaseModel):
    bot_token: Optional[str] = Field(None, description="Lascia vuoto per non cambiarlo")
    chat_id: Optional[str] = None
    topics: Dict[str, int] = Field(default_factory=dict, description="MATERIA -> id del topic")
    misc_topic_id: Optional[int] = None


class ConnectionIn(BaseModel):
    name: str
    provider: Literal["openrouter", "google", "deepseek", "openai_compatible"]
    base_url: str = ""
    api_keys: List[str] = Field(min_length=1)


class ModelIn(BaseModel):
    model: str


class PhaseIn(BaseModel):
    connection: str
    model: str


class RouteIn(BaseModel):
    provider: str
    credential: str = ""
    model: str
    base_url: str = ""
    round_robin: bool = False
    round_robin_credentials: Optional[List[str]] = None


class RouteOut(BaseModel):
    job: str
    role: str
    provider: str
    credential: str
    model: str
    base_url: str
    round_robin: bool


class SecretIn(BaseModel):
    value: str = Field(min_length=1)


class SecretSaved(BaseModel):
    name: str
    set: bool = True
    stored_in: Literal["store", "env"]


class DaemonStatus(BaseModel):
    running: bool
    pid: Optional[int] = None


# ---------------------------------------------------------------- lettura

@router.get("/settings", response_model=Settings, summary="Tutte le impostazioni (nessun valore segreto)")
def get_settings(_actor: Actor):
    from rt.services.settings_service import snapshot
    return snapshot(_project_root())


# ---------------------------------------------------------------- scrittura

@router.put("/settings/lessons-root", response_model=Settings, summary="Cartella delle lezioni")
def put_lessons_root(body: LessonsRootIn, _actor: Actor):
    from rt.services.settings_service import save_lessons_root, snapshot
    _call(save_lessons_root, body.path, _project_root())
    return snapshot(_project_root())


@router.put("/settings/worker", response_model=Settings,
            summary="Job in parallelo del worker avviato con la web (vale dal prossimo avvio)")
def put_worker(body: WorkerIn, _actor: Actor):
    from rt.services.settings_service import save_worker_concurrency, snapshot
    _call(save_worker_concurrency, _project_root(), body.concurrency)
    return snapshot(_project_root())


@router.put("/settings/transcription", response_model=Settings, summary="Motore di trascrizione")
def put_transcription(body: TranscriptionIn, _actor: Actor):
    from rt.services.settings_service import save_transcription, snapshot
    _call(save_transcription, _project_root(), body.engine, body.base_url, body.model, body.api_key or "")
    return snapshot(_project_root())


@router.put("/settings/telegram", response_model=Settings, summary="Bot Telegram: token, chat, topic")
def put_telegram(body: TelegramIn, _actor: Actor):
    from rt.services.settings_service import save_telegram, snapshot
    topics = [[k, v] for k, v in body.topics.items()]
    misc = "" if body.misc_topic_id is None else str(body.misc_topic_id)
    _call(save_telegram, _project_root(), body.bot_token or "", body.chat_id or "", topics, misc)
    return snapshot(_project_root())


@router.post("/settings/connections", response_model=Settings, status_code=201,
             summary="Nuova connessione LLM (provider, base URL, una o più chiavi)")
def post_connection(body: ConnectionIn, _actor: Actor):
    from rt.services.connections_service import save_connection
    from rt.services.settings_service import snapshot
    _call(save_connection, _project_root(), body.name, body.provider, body.base_url, body.api_keys)
    return snapshot(_project_root())


@router.post("/settings/connections/{name}/models", response_model=Settings, summary="Aggiunge un modello a una connessione")
def post_connection_model(name: str, body: ModelIn, _actor: Actor):
    from rt.services.connections_service import add_model
    from rt.services.settings_service import snapshot
    _call(add_model, _project_root(), name, body.model)
    return snapshot(_project_root())


@router.put("/settings/phases/{job}", response_model=Settings,
            summary="Assegna connessione e modello a una fase (outline, rewrite, review, recall, immagini)")
def put_phase(job: str, body: PhaseIn, _actor: Actor):
    from rt.services.connections_service import assign_phase
    from rt.services.settings_service import snapshot
    _call(assign_phase, _project_root(), job, body.connection, body.model)
    return snapshot(_project_root())


@router.get("/settings/routes/{job}/{role}", response_model=RouteOut, summary="Route di un job LLM (primaria, secondaria, fallback)")
def get_route(job: str, role: str, _actor: Actor):
    from rt.services.settings_service import ROUTE_ROLES, route_settings
    if role not in ROUTE_ROLES:
        raise ApiError(404, "route_not_found", "Ruolo non riconosciuto.")
    provider, credential, model, base_url, round_robin = route_settings(_project_root(), job, role)
    return RouteOut(job=job, role=role, provider=provider, credential=credential, model=model,
                    base_url=base_url, round_robin=round_robin)


@router.put("/settings/routes/{job}/{role}", response_model=RouteOut, summary="Salva la route di un job LLM")
def put_route(job: str, role: str, body: RouteIn, actor: Actor):
    from rt.services.settings_service import save_route
    _call(save_route, _project_root(), job, role, body.provider, body.credential, body.model,
          body.base_url, body.round_robin, body.round_robin_credentials)
    return get_route(job, role, actor)


@router.put("/settings/pricing", response_model=Settings, summary="Pricing custom per provider e modello (USD per 1M token)")
def put_pricing(body: Dict[str, Dict[str, Dict[str, Any]]], _actor: Actor):
    from rt.services.settings_service import save_pricing, snapshot
    _call(save_pricing, _project_root(), body)
    return snapshot(_project_root())


@router.put("/secrets/{name}", response_model=SecretSaved,
            summary="Salva un segreto dichiarato (archivio cifrato se inizializzato); il valore non viene mai restituito")
def put_secret(name: str, body: SecretIn, _actor: Actor):
    from rt.services.settings_service import save_secret_by_name
    try:
        where = _call(save_secret_by_name, _project_root(), name, body.value)
    except KeyError:
        raise ApiError(404, "secret_not_declared", "Segreto non dichiarato in configurazione.")
    return SecretSaved(name=name, stored_in=where)


# ---------------------------------------------------------------- bot Telegram

@router.get("/telegram/daemon", response_model=DaemonStatus, summary="Stato del bot Telegram")
def daemon_status(_actor: Actor):
    from rt.telegram.daemon_status import get_daemon_pid
    pid = get_daemon_pid()
    return DaemonStatus(running=pid is not None, pid=pid)


@router.post("/telegram/daemon/start", response_model=DaemonStatus,
             summary="Avvia il bot Telegram come processo indipendente dall'API")
def daemon_start(_actor: Actor):
    import os
    from rt.services.settings_service import general_config_path, secret_is_set
    from rt.telegram.daemon_status import get_default_pid_path, start_daemon_detached
    if not secret_is_set("RT_TELEGRAM_BOT_TOKEN") or not (os.environ.get("RT_TELEGRAM_CHAT_ID") or "").strip():
        raise ApiError(409, "telegram_not_configured", "Salva prima token e Chat ID del bot.")
    logfile = os.path.join(os.path.dirname(get_default_pid_path()), "telegram.log")
    try:
        pid = start_daemon_detached(str(general_config_path(_project_root()).parent.parent), logfile)
    except RuntimeError as exc:
        raise ApiError(409, "telegram_start_failed", str(exc))
    return DaemonStatus(running=True, pid=pid)


@router.post("/telegram/daemon/stop", response_model=DaemonStatus, summary="Ferma il bot Telegram")
def daemon_stop(_actor: Actor):
    from rt.telegram.daemon_status import stop_daemon
    stop_daemon()
    return daemon_status(_actor)
