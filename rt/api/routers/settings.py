"""Impostazioni (come 'rt config' e la pagina Impostazioni), segreti e bot Telegram.
Nessuna risposta contiene mai il valore di un segreto: solo "impostato sì/no"."""
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError, require_telegram
from rt.api.schemas import JobAccepted
from rt.core.jev_decision import JevDecisionConfig

router = APIRouter(tags=["impostazioni"])

# Il router personale entra nello stesso punto di registrazione delle impostazioni.
from rt.api.routers.preferences import router as preferences_router
router.include_router(preferences_router)


class PromptOverrideIn(BaseModel):
    instruction: str = Field(max_length=20000)


class PromptOverrideOut(BaseModel):
    default: str
    instruction: str


@router.get("/settings/prompts", response_model=Dict[str, PromptOverrideOut], summary="Istruzioni personalizzabili e predefinite per fase")
def list_prompt_overrides(actor: Actor):
    from rt.llm.prompts import (OUTLINE_SYSTEM_PROMPT, REWRITE_SYSTEM_PROMPT, SCIENCE_REVIEW_SYSTEM_PROMPT,
                                IMAGE_DESCRIPTION_SYSTEM_PROMPT, RECALL_QUIZ_SYSTEM_PROMPT)
    from rt.services.prompt_settings import global_instruction
    defaults = {"outline": OUTLINE_SYSTEM_PROMPT, "rewrite": REWRITE_SYSTEM_PROMPT,
                "review": SCIENCE_REVIEW_SYSTEM_PROMPT, "image_description": IMAGE_DESCRIPTION_SYSTEM_PROMPT,
                "recall": RECALL_QUIZ_SYSTEM_PROMPT}
    return {phase: {"default": default, "instruction": global_instruction(phase)}
            for phase, default in defaults.items()}


@router.put("/settings/prompts/{phase}", summary="Salva istruzioni per una fase; vuoto ripristina il default")
def save_prompt_override(phase: str, body: PromptOverrideIn, actor: Actor):
    from rt.services.prompt_settings import set_global_instruction
    _call(set_global_instruction, phase, body.instruction)
    return {"phase": phase, "instruction": body.instruction.strip()}


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
    enabled: bool = Field(False, description="Telegram attivo (spento di predefinito): bot, ripassi e decisioni su Telegram")
    bot_token_set: bool
    bot_token_preview: Optional[str] = Field(None, description="Primi e ultimi caratteri del token (es. 1234…wXyZ); "
                                                               "il valore completo solo con POST /settings/telegram/reveal")
    chat_id_set: bool = False
    chat_id_preview: Optional[str] = Field(None, description="Primi e ultimi caratteri del Chat ID")
    topics: Dict[str, int]
    topic_names: Dict[str, str] = Field(default_factory=dict, description="id del topic -> nome rilevato da Telegram")
    misc_topic_id: Optional[int] = None
    default_channel: str


class WorkerSettings(BaseModel):
    concurrency: int = Field(description="Job in parallelo del worker di 'rt web' (1-4, su lezioni diverse): "
                                         "vale dal prossimo avvio")
    running: int = Field(0, description="Worker attivi ora (uno per job eseguibile insieme)")


class WorkerIn(BaseModel):
    concurrency: int = Field(ge=1, le=4)


class NoticeSettings(BaseModel):
    dismissed: List[str] = Field(description="Avvisi nascosti con 'Non mostrare più' (preview_edit_beta, preview_edit_issues, setup_wizard)")


class NoticeIn(BaseModel):
    notice: Literal["preview_edit_beta", "preview_edit_issues", "setup_wizard"]
    dismissed: bool = True


class WebSearchSettings(BaseModel):
    searxng_base_url: Optional[str] = Field(None, description="URL base di SearXNG per la ricerca immagini web")


class PreferencesSettings(BaseModel):
    secondi_approvazione: int = Field(default=10, ge=0, le=3600, description="Secondi per l'approvazione automatica della scaletta (0 = disattivata)")
    sfondo_gruppi: Literal["colori", "grigi", "niente"] = Field(default="colori", description="Sfondo dei gruppi in Lezioni")
    modalita_arricchimento: Literal["manuale", "automatica", "disattivata"] = Field(default="manuale", description="Modalità dell'arricchimento")


class Settings(BaseModel):
    worker: WorkerSettings
    notices: NoticeSettings
    transcription: Transcription
    telegram: TelegramSettings
    phases: List[PhaseAssignment] = Field(description="Modello assegnato a ciascuna fase LLM")
    connections: List[Connection]
    credentials: List[CredentialState]
    pricing: Dict[str, Dict[str, Dict[str, Any]]]
    web_search: WebSearchSettings
    preferences: PreferencesSettings = Field(default_factory=PreferencesSettings, description="Preferenze generali")
    secrets_encrypted: bool = Field(description="True se i segreti sono nell'archivio cifrato (rt secrets init)")
    data_dir: Optional[str] = Field(None, description="Cartella dati in uso da questo processo: rt.db e media/")
    setup_required: bool = Field(False, description="True se manca un passo obbligatorio della configurazione e la SPA "
                                                    "apre la configurazione guidata (oggi nessuno: le lezioni stanno "
                                                    "nel database della cartella dati)")


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
    topic_names: Optional[Dict[str, str]] = Field(None, description="id del topic -> nome rilevato (facoltativo)")


class RevealIn(BaseModel):
    field: Literal["bot_token", "chat_id"]


class RevealOut(BaseModel):
    field: str
    value: Optional[str] = Field(None, description="Valore completo, null se non impostato")


class TopicTestIn(BaseModel):
    topic_id: int = Field(ge=1)
    materia: str = ""


class TopicTestOut(BaseModel):
    ok: bool
    message: str
    text: str = Field(description="Testo inviato nel topic")


class ListenMessages(BaseModel):
    job_id: Optional[str] = Field(None, description="Ultimo ascolto dei topic concluso")
    finished_at: Optional[str] = None
    count: int = Field(description="Messaggi ricevuti durante quell'ascolto (esclusi quelli di servizio)")
    cleaned: bool = Field(description="True se sono già stati cancellati")


class DeleteFailure(BaseModel):
    message_id: int
    reason: str


class ListenMessagesDeleted(BaseModel):
    job_id: str
    deleted: int
    failed: List[DeleteFailure]


class Notification(BaseModel):
    sent_at: str
    kind: str = Field(description="lezione_pronta, issue o prova")
    text: str
    topic_id: Optional[int] = None
    ok: bool = True


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


class SecretDeleted(BaseModel):
    name: str
    set: bool = False
    removed_from: List[Literal["store", "env"]] = Field(
        description="Dove era salvato; vuoto se non c'era (l'eliminazione è idempotente)")


class ModelTestIn(BaseModel):
    connection: str
    model: str
    mock: bool = False
    vision: bool = False


class ModelTestOut(BaseModel):
    ok: bool
    connection: str
    provider: str
    model: str
    latency_ms: Optional[int] = Field(None, description="Durata della chiamata in millisecondi")
    status_code: Optional[int] = Field(None, description="Stato HTTP della risposta del provider")
    reply: Optional[str] = Field(None, description="Inizio della risposta del modello")
    message: str = Field(description="Esito leggibile, anche l'errore del provider (sanificato)")
    vision_verified: bool = False


class WebSearchIn(BaseModel):
    searxng_base_url: str = Field("", description="Vuoto per rimuoverlo")


class WebSearchTestIn(BaseModel):
    searxng_base_url: str
    mock: bool = False


class WebSearchTestOut(BaseModel):
    ok: bool
    results: int = Field(description="Immagini restituite dalla ricerca di prova")
    latency_ms: Optional[int] = None
    message: str


class DaemonStatus(BaseModel):
    running: bool
    pid: Optional[int] = None


# ---------------------------------------------------------------- lettura

@router.get("/settings", response_model=Settings, summary="Tutte le impostazioni (nessun valore segreto)")
def get_settings(_actor: Actor):
    from rt.services.settings_service import snapshot
    return snapshot(_project_root())


# ---------------------------------------------------------------- scrittura

@router.put("/settings/worker", response_model=Settings,
            summary="Job in parallelo del worker avviato con la web (vale dal prossimo avvio)")
def put_worker(body: WorkerIn, _actor: Actor):
    from rt.services.settings_service import save_worker_concurrency, snapshot
    _call(save_worker_concurrency, _project_root(), body.concurrency)
    return snapshot(_project_root())


@router.put("/settings/notices", response_model=Settings,
            summary="Nasconde o rimostra un avviso della web ('Non mostrare più'), per tutti i browser")
def put_notice(body: NoticeIn, _actor: Actor):
    from rt.services.settings_service import save_notice, snapshot
    _call(save_notice, _project_root(), body.notice, body.dismissed)
    return snapshot(_project_root())


@router.put("/settings/preferences", response_model=Settings, summary="Salva le preferenze generali")
def put_preferences(body: PreferencesSettings, _actor: Actor):
    from rt.services.settings_service import save_preferences, snapshot
    _call(save_preferences, _project_root(), body.model_dump(exclude_unset=True))
    return snapshot(_project_root())


@router.put("/settings/transcription", response_model=Settings, summary="Motore di trascrizione")
def put_transcription(body: TranscriptionIn, _actor: Actor):
    from rt.services.settings_service import save_transcription, snapshot
    _call(save_transcription, _project_root(), body.engine, body.base_url, body.model, body.api_key or "")
    return snapshot(_project_root())


class TelegramEnabledIn(BaseModel):
    enabled: bool


@router.put("/settings/telegram/enabled", response_model=Settings, summary="Accende o spegne Telegram (spento: anche il bot si ferma)")
def put_telegram_enabled(body: TelegramEnabledIn, _actor: Actor):
    from rt.services.settings_service import set_telegram_enabled, snapshot
    _call(set_telegram_enabled, _project_root(), body.enabled)
    if not body.enabled:
        daemon_stop(_actor)
    return snapshot(_project_root())


@router.put("/settings/telegram", response_model=Settings, summary="Bot Telegram: token, chat, topic")
def put_telegram(body: TelegramIn, _actor: Actor):
    from rt.services.settings_service import save_telegram, snapshot
    topics = [[k, v] for k, v in body.topics.items()]
    misc = "" if body.misc_topic_id is None else str(body.misc_topic_id)
    names = None if body.topic_names is None else {int(k): v for k, v in body.topic_names.items() if str(k).isdigit()}
    _call(save_telegram, _project_root(), body.bot_token or "", body.chat_id or "", topics, misc, names)
    return snapshot(_project_root())


class TopicRecreateIn(BaseModel):
    topic_id: int
    name: str
    confirmation: str


class TelegramUserStartIn(BaseModel):
    api_id: int
    api_hash: str
    phone: str


class TelegramUserCompleteIn(BaseModel):
    code: str
    password: Optional[str] = None


class TelegramUserStatusOut(BaseModel):
    authorized: bool


class TelegramTopicOut(BaseModel):
    id: int
    name: str


class TelegramUserTopicsOut(BaseModel):
    topics: List[TelegramTopicOut]


@router.get("/settings/telegram/user/status", response_model=TelegramUserStatusOut, summary="Stato della sessione Telegram utente")
async def telegram_user_status(_actor: Actor):
    from rt.services.errors import ServiceError
    from rt.services.telegram_user_archive import _authorized_client
    try:
        client = await _authorized_client()
    except ServiceError:
        return {"authorized": False}
    await client.disconnect()
    return {"authorized": True}


@router.delete("/settings/telegram/user/session", summary="Revoca la sessione Telegram utente")
async def revoke_telegram_user(_actor: Actor):
    from rt.services.telegram_user_archive import revoke_session
    await revoke_session()
    return {"authorized": False}


@router.post("/settings/telegram/user/start", summary="Invia un codice Telegram all'account utente")
async def start_telegram_user(body: TelegramUserStartIn, _actor: Actor):
    require_telegram()
    from rt.services.telegram_user_archive import request_code
    await request_code(body.api_id, body.api_hash, body.phone)
    return {"sent": True}


@router.post("/settings/telegram/user/complete", summary="Completa l'accesso utente con codice e 2FA")
async def complete_telegram_user(body: TelegramUserCompleteIn, _actor: Actor):
    require_telegram()
    from rt.services.telegram_user_archive import complete_login
    await complete_login(body.code, body.password)
    return {"authorized": True}


@router.get("/settings/telegram/user/topics", response_model=TelegramUserTopicsOut, summary="Elenca i topic del gruppo con l'account utente")
async def get_telegram_user_topics(_actor: Actor):
    from rt.services.telegram_topics import _chat_id
    from rt.services.telegram_user_archive import list_topics
    return {"topics": await list_topics(int(_chat_id()))}


@router.post("/settings/telegram/user/topics/{topic_id}/archive", response_model=JobAccepted, status_code=202,
             summary="Esporta cronologia e media del topic (job telegram_topic_export; si scarica da /settings/telegram/user/archives/{job_id})")
def start_telegram_topic_archive(topic_id: int, actor: Actor):
    require_telegram()
    from rt.api.jobs import enqueue_job
    from rt.services.telegram_topics import TopicListenError, _chat_id
    from rt.services.telegram_user_archive import check_export_ready
    if topic_id < 1:
        raise ApiError(422, "invalid_topic", "Topic non valido.")
    try:
        chat_id = int(_chat_id())
    except (TopicListenError, ValueError) as exc:
        raise ApiError(409, "telegram_not_configured", str(exc) or "Chat ID del gruppo non valido.")
    check_export_ready()
    return enqueue_job("telegram_topic_export", None, {"chat_id": chat_id, "topic_id": topic_id}, actor)


@router.get("/settings/telegram/user/archives/{job_id}", summary="Scarica l'archivio prodotto da un job telegram_topic_export concluso",
            response_class=Response, responses={200: {"content": {"application/zip": {}}}})
def download_telegram_topic_archive(job_id: str, _actor: Actor):
    from fastapi.responses import FileResponse
    from rt.api.jobs import queue
    from rt.services.api_jobs import TELEGRAM_TOPIC_EXPORT, job_export_path
    info = queue().get(job_id)
    if info is None or info.type != TELEGRAM_TOPIC_EXPORT:
        raise ApiError(404, "job_not_found", "Esportazione inesistente.")
    if info.state != "succeeded":
        raise ApiError(409, "archive_not_ready", "L'esportazione non è ancora conclusa.")
    filename = str((info.result or {}).get("file") or "")
    path = job_export_path(info.id, filename) if filename else ""
    if not path or not os.path.isfile(path):
        raise ApiError(410, "archive_expired", "L'archivio non è più disponibile: esporta di nuovo il topic.")
    return FileResponse(path, media_type="application/zip", filename=os.path.basename(path))


@router.post("/settings/telegram/recreate-topic", summary="Elimina tutti i messaggi del topic e lo ricrea vuoto")
def recreate_telegram_topic(body: TopicRecreateIn, _actor: Actor):
    require_telegram()
    from rt.services.telegram_topics import TopicListenError, recreate_topic
    try:
        new_id = recreate_topic(body.topic_id, body.name, body.confirmation)
    except TopicListenError as exc:
        raise ApiError(409, "topic_recreation_failed", str(exc)) from exc
    return {"new_topic_id": new_id}


@router.post("/settings/telegram/reveal", response_model=RevealOut,
             summary="Valore completo del token del bot o del Chat ID, solo su richiesta esplicita")
def reveal_telegram(body: RevealIn, response: Response, _actor: Actor):
    from rt.services.settings_service import telegram_value
    response.headers["Cache-Control"] = "no-store"
    return RevealOut(field=body.field, value=telegram_value(body.field) or None)


@router.post("/settings/telegram/test-topic", response_model=TopicTestOut,
             summary="Invia nel topic il messaggio di prova 'Questo è il topic di <materia>'")
def test_topic(body: TopicTestIn, _actor: Actor):
    require_telegram()
    from rt.services.telegram_topics import TopicListenError, send_topic_test
    from rt.telegram.notify_log import record_notification
    try:
        result = send_topic_test(body.topic_id, body.materia)
    except TopicListenError as exc:
        raise ApiError(409, "telegram_not_configured", str(exc))
    record_notification("prova", result["text"], body.topic_id, ok=result["ok"])
    return result


LISTEN_CLEANED_KEY = "telegram.listen_cleaned"


def _last_listen():
    """Ultimo job 'Ascolta i topic' riuscito e i messaggi che ha ricevuto."""
    from rt.api.jobs import queue
    for info in queue().list(state="succeeded", job_type="telegram_listen_topics", limit=20):
        result = info.result or {}
        if result.get("ok"):
            return info, [m for m in result.get("messages") or [] if isinstance(m, dict)]
    return None, []


def _cleaned_job() -> Optional[str]:
    from rt.db.engine import get_database
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(get_database()) as s:
        return (SettingRepository(s).get(LISTEN_CLEANED_KEY) or {}).get("job_id")


@router.get("/settings/telegram/listen-messages", response_model=ListenMessages,
            summary="Messaggi ricevuti durante l'ultimo ascolto dei topic")
def listen_messages(_actor: Actor):
    info, messages = _last_listen()
    if info is None:
        return ListenMessages(count=0, cleaned=False)
    finished = info.finished_at.isoformat() if info.finished_at else None
    return ListenMessages(job_id=info.id, finished_at=finished, count=len(messages),
                          cleaned=_cleaned_job() == info.id)


@router.post("/settings/telegram/listen-messages/delete", response_model=ListenMessagesDeleted,
             summary="Cancella dal gruppo solo i messaggi ricevuti durante l'ultimo ascolto dei topic")
def delete_listen_messages(_actor: Actor):
    from rt.db.engine import get_database
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    from rt.services.telegram_topics import TopicListenError, delete_listen_messages as delete
    info, messages = _last_listen()
    if info is None or not messages:
        raise ApiError(404, "no_listen_messages", "Nessun messaggio di rilevamento da cancellare.")
    try:
        outcome = delete(messages)
    except TopicListenError as exc:
        raise ApiError(409, "telegram_not_configured", str(exc))
    with session_scope(get_database()) as s:
        SettingRepository(s).set(LISTEN_CLEANED_KEY, {"job_id": info.id, "deleted": outcome["deleted"]})
    return ListenMessagesDeleted(job_id=info.id, deleted=len(outcome["deleted"]), failed=outcome["failed"])


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


@router.delete("/settings/connections/{name}", response_model=Settings,
               summary="Elimina una connessione con i suoi modelli e le sue chiavi (409 se una route o il classificatore la usa)")
def delete_connection(name: str, _actor: Actor):
    from rt.security.secrets import SecretStoreError
    from rt.services.connections_service import ConnectionInUse, connection_names, delete_connection
    from rt.services.settings_service import snapshot
    if name not in connection_names(_project_root()):
        raise ApiError(404, "connection_not_found", "Connessione inesistente.")
    try:
        delete_connection(_project_root(), name)
    except ConnectionInUse as exc:
        raise ApiError(409, "connection_in_use", str(exc), details={"usages": exc.usages})
    except SecretStoreError as exc:
        raise ApiError(409, "secret_store_unavailable", str(exc))
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


@router.post("/settings/models/test", response_model=ModelTestOut,
             summary="Prova connessione e modello con una chiamata minima (anche prima di salvarli)")
def post_model_test(body: ModelTestIn, _actor: Actor):
    from rt.services.probes import probe_model
    return _call(probe_model, _project_root(), body.connection, body.model, body.mock, vision=body.vision)


class DecisionModelIn(BaseModel):
    enabled: bool = False
    shadow: bool = True
    model: str = ""
    relevance_model: str = ""
    credential: str = "openrouter"
    threshold: float = Field(0.85, ge=0, le=1)
    relevance_mode: Literal["disabled", "shadow", "active"] = "shadow"
    relevance_prompt: str = Field("", max_length=20000)
    relevance_threshold: float = Field(0.85, ge=0, le=1)
    prefilter_type: Literal["choice", "noul", "score"] = "choice"
    prefilter_prompt: str = Field("", max_length=20000)
    relevance_decision: Optional[JevDecisionConfig] = Field(
        None, description="Domanda e mappatura del gate di rilevanza (None = invariata/predefinita)")
    prefilter_decision: Optional[JevDecisionConfig] = Field(
        None, description="Domanda e mappatura del prefiltro errori (None = invariata/predefinita)")


class DecisionModelOut(DecisionModelIn):
    relevance_decision: JevDecisionConfig
    prefilter_decision: JevDecisionConfig
    relevance_customized: bool = Field(False, description="True se la rilevanza non usa la domanda predefinita")
    prefilter_customized: bool = Field(False, description="True se il prefiltro non usa la domanda predefinita")
    templates: Dict[Literal["relevance", "prefilter"], Dict[Literal["choice", "noul", "score"], JevDecisionConfig]] = Field(
        description="Domanda e mappatura predefinite per fase e tipo di richiesta")


class DecisionProbeOut(BaseModel):
    ok: bool
    choice: str
    confidence: float
    request_type: Literal["choice", "noul", "score"] = "choice"


class DecisionTestIn(BaseModel):
    phase: Literal["relevance", "prefilter"]
    decision: JevDecisionConfig
    model: str = Field("", max_length=200)
    credential: str = "openrouter"
    lesson_id: Optional[int] = Field(None, description="Lezione su cui provare (assente = unità di esempio)")
    unit_id: Optional[str] = Field(None, description="Unità della lezione (assente = la prima)")


class DecisionTestOut(BaseModel):
    phase: Literal["relevance", "prefilter"]
    unit_id: Optional[str] = None
    unit_title: str
    state: str = Field(description="Stato inviato al classificatore (l'unità di lezione)")
    request: Dict[str, Any] = Field(description="Richiesta inviata all'endpoint decisions")
    response: Dict[str, Any] = Field(description="Risposta JSON del classificatore")
    answer: Dict[str, Any] = Field(description="Risposta alla domanda, con tutte le probabilità")
    label: str = Field(description="Etichetta RT assegnata dalla mappatura")
    outcome: str = Field(description="Esito RT dell'etichetta")
    rule: Optional[int] = Field(None, description="Regola scattata (da 0); null = nessuna, esito fail-open")


def _decision_out(cfg) -> DecisionModelOut:
    from rt.services import jev_mapping
    from rt.services.jev_playground import templates
    return DecisionModelOut(enabled=cfg.enabled, shadow=cfg.shadow, model=cfg.model if cfg.enabled else "",
                            relevance_model=cfg.relevance_model,
                            credential=cfg.credential, threshold=cfg.task_a_skip_confidence_threshold,
                            relevance_mode=cfg.relevance_mode, relevance_prompt=cfg.relevance_prompt,
                            relevance_threshold=cfg.relevance_threshold, prefilter_type=cfg.prefilter_type,
                            prefilter_prompt=cfg.prefilter_prompt,
                            relevance_decision=jev_mapping.effective_decision("relevance", cfg),
                            prefilter_decision=jev_mapping.effective_decision("prefilter", cfg),
                            relevance_customized=cfg.relevance_decision is not None,
                            prefilter_customized=cfg.prefilter_decision is not None,
                            templates=templates(cfg))


def _playground_call(fn, *args, **kwargs):
    from rt.services.jev_playground import PlaygroundError
    try:
        return fn(*args, **kwargs)
    except PlaygroundError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc


@router.get("/settings/decision-model", response_model=DecisionModelOut)
def get_decision_model(_actor: Actor):
    from rt.core.config import load_config
    from rt.core.config import classifier_jev
    cfg = load_config()
    from rt.core.config import classifier_job
    result = _decision_out(classifier_jev(cfg, "relevance"))
    result.model = classifier_job(cfg, "prefilter").model
    result.enabled = classifier_job(cfg, "prefilter").mode in ("observe", "pipeline")
    result.shadow = classifier_job(cfg, "prefilter").mode == "observe"
    return result


@router.post("/settings/decision-model/test", response_model=DecisionTestOut,
             summary="Prova una configurazione del classificatore (anche non salvata) su un'unità di lezione")
def test_decision_model(body: DecisionTestIn, _actor: Actor):
    from rt.services.jev_playground import run_test
    return _playground_call(run_test, body.phase, body.decision, body.model, body.credential,
                            lesson_id=body.lesson_id, unit_id=body.unit_id)


@router.post("/settings/decision-model/probe", response_model=DecisionProbeOut)
def probe_decision_model(body: DecisionModelIn, _actor: Actor):
    from rt.llm.jev_client import JevChoiceQuestion, JevNoulQuestion, JevScoreQuestion, JevError, call_jev
    from rt.services.jev_playground import record_probe
    if not body.model.strip():
        raise ApiError(422, "decision_model_required", "Indica un modello decisionale.")
    try:
        if body.prefilter_type == "choice":
            question = JevChoiceQuestion(instructions="Classifica il frutto.", criteria={"banana": "È una banana", "altro": "È un altro frutto"})
        elif body.prefilter_type == "noul":
            question = JevNoulQuestion(instructions="È vero che la banana è un frutto? Rispondi con probabilità alta se l'affermazione è errata.")
        else:
            question = JevScoreQuestion(instructions="Valuta da 0 a 1 la probabilità che la banana sia un frutto.", criteria=["Probabilità che l'affermazione sia errata, da 0 a 1."])
        response = call_jev("Un oggetto è una banana gialla matura. La banana è un frutto.",
            {"categoria": question},
            job_name="decision_model_probe", model=body.model, credential=body.credential)
    except JevError as exc:
        raise ApiError(422, "decision_protocol_failed", str(exc)) from exc
    answer = response.answers["categoria"]
    if answer.type != body.prefilter_type:
        raise ApiError(422, "decision_protocol_failed", f"Il modello non ha restituito una risposta {body.prefilter_type} valida per il classificatore.")
    if answer.type == "choice":
        if answer.choice != "banana" or set(answer.probabilities) != {"banana", "altro"}:
            raise ApiError(422, "decision_protocol_failed", "Il modello non ha restituito opzioni e probabilità complete.")
        choice, confidence = answer.choice, answer.confidence
    elif answer.type == "noul":
        choice, confidence = "noul", answer.noul
    else:
        choice, confidence = "score", answer.confidence
    record_probe(body.credential, body.model, body.prefilter_type)
    return {"ok": True, "choice": choice, "confidence": confidence, "request_type": body.prefilter_type}


@router.put("/settings/decision-model", response_model=DecisionModelOut)
def put_decision_model(body: DecisionModelIn, _actor: Actor):
    from rt.core.config import JevConfig, load_config
    from rt.services import config_service, jev_mapping
    from rt.services.jev_playground import check_phase, probe_missing
    from rt.services.settings_service import general_config_path
    current = load_config().jev
    relevance = body.relevance_decision or current.relevance_decision
    prefilter = body.prefilter_decision or current.prefilter_decision
    relevance = _playground_call(check_phase, "relevance", relevance) if relevance else None
    prefilter = _playground_call(check_phase, "prefilter", prefilter) if prefilter else None
    # Il tipo storico segue la domanda del prefiltro: la predefinita di quel tipo resta "predefinita".
    prefilter_type = prefilter.type if prefilter else body.prefilter_type
    legacy = JevConfig(task_a_skip_confidence_threshold=body.threshold, relevance_prompt=body.relevance_prompt,
                       relevance_threshold=body.relevance_threshold, prefilter_type=prefilter_type,
                       prefilter_prompt=body.prefilter_prompt)
    # Una decisione identica alla predefinita non si salva: impronta e cache restano quelle di prima.
    if relevance and jev_mapping.is_default("relevance", relevance, legacy):
        relevance = None
    if prefilter and jev_mapping.is_default("prefilter", prefilter, legacy):
        prefilter = None
    path = general_config_path(_project_root())
    data = config_service.read_yaml(path)
    from rt.services.classifier_settings import write_classifier
    write_classifier(data, load_config().classifier)
    jev = {**data.get("jev", {}), "task_a_skip_confidence_threshold": body.threshold,
           "relevance_prompt": body.relevance_prompt, "relevance_threshold": body.relevance_threshold,
           "prefilter_type": prefilter_type, "prefilter_prompt": body.prefilter_prompt}
    for key, decision in (("relevance_decision", relevance), ("prefilter_decision", prefilter)):
        if decision is None:
            jev.pop(key, None)
        else:
            jev[key] = decision.model_dump()
    data["jev"] = jev
    config_service.write_yaml_atomic(path, data)
    return get_decision_model(_actor)


@router.put("/settings/web-search", response_model=Settings, summary="Ricerca web: URL base di SearXNG")
def put_web_search(body: WebSearchIn, _actor: Actor):
    from rt.services.settings_service import save_web_search, snapshot
    _call(save_web_search, _project_root(), body.searxng_base_url)
    return snapshot(_project_root())


@router.post("/settings/web-search/test", response_model=WebSearchTestOut,
             summary="Ricerca immagini di prova su SearXNG: quanti risultati tornano")
def post_web_search_test(body: WebSearchTestIn, _actor: Actor):
    from rt.services.probes import probe_searxng
    return _call(probe_searxng, body.searxng_base_url, body.mock)


@router.put("/secrets/{name}", response_model=SecretSaved,
            summary="Salva un segreto dichiarato (archivio cifrato se inizializzato); il valore non viene mai restituito")
def put_secret(name: str, body: SecretIn, _actor: Actor):
    from rt.services.settings_service import save_secret_by_name
    try:
        where = _call(save_secret_by_name, _project_root(), name, body.value)
    except KeyError:
        raise ApiError(404, "secret_not_declared", "Segreto non dichiarato in configurazione.")
    return SecretSaved(name=name, stored_in=where)


@router.delete("/secrets/{name}", response_model=SecretDeleted,
               summary="Elimina un segreto dichiarato dall'archivio cifrato, da .env e dall'ambiente (come 'rt secrets unset')")
def delete_secret(name: str, _actor: Actor):
    from rt.security.secrets import SecretStoreError
    from rt.services.settings_service import delete_secret_by_name
    try:
        removed = delete_secret_by_name(_project_root(), name)
    except KeyError:
        raise ApiError(404, "secret_not_declared", "Segreto non dichiarato in configurazione.")
    except SecretStoreError as exc:
        raise ApiError(409, "secret_store_unavailable", str(exc))
    return SecretDeleted(name=name, removed_from=removed)


# ---------------------------------------------------------------- bot Telegram

@router.get("/telegram/daemon", response_model=DaemonStatus, summary="Stato del bot Telegram")
def daemon_status(_actor: Actor):
    from rt.telegram.daemon_status import get_daemon_pid
    pid = get_daemon_pid()
    return DaemonStatus(running=pid is not None, pid=pid)


@router.post("/telegram/daemon/start", response_model=DaemonStatus,
             summary="Avvia il bot Telegram come processo indipendente dall'API")
def daemon_start(_actor: Actor):
    require_telegram()
    import os
    from rt.services.settings_service import general_config_path, secret_is_set
    from rt.telegram.daemon_status import get_default_pid_path, start_daemon_detached
    if not secret_is_set("RT_TELEGRAM_BOT_TOKEN") or not (os.environ.get("RT_TELEGRAM_CHAT_ID") or "").strip():
        raise ApiError(409, "telegram_not_configured", "Salva prima token e Chat ID del bot.")
    from rt.services import service_manager as sm
    if sm.supported() and sm.installed(["bot"]):
        # fase G: il bot è un servizio launchd, lo avvia launchd (niente processo figlio dell'API)
        try:
            sm.start(["bot"])
        except sm.ServiceError as exc:
            raise ApiError(409, "telegram_start_failed", str(exc))
        pid = _wait_daemon_pid()
        if pid is None:
            raise ApiError(409, "telegram_start_failed", "Il bot non si è avviato: controlla il log del servizio bot.")
        return DaemonStatus(running=True, pid=pid)
    logfile = os.path.join(os.path.dirname(get_default_pid_path()), "telegram.log")
    try:
        pid = start_daemon_detached(str(general_config_path(_project_root()).parent.parent), logfile)
    except RuntimeError as exc:
        raise ApiError(409, "telegram_start_failed", str(exc))
    return DaemonStatus(running=True, pid=pid)


def _wait_daemon_pid(seconds: float = 8.0):
    import time
    from rt.telegram.daemon_status import get_daemon_pid
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pid = get_daemon_pid()
        if pid is not None:
            return pid
        time.sleep(0.2)
    return None


@router.get("/telegram/notifications", response_model=List[Notification],
            summary="Ultime notifiche inviate dal bot (lezione pronta, issue, prove dei topic)")
def notifications(_actor: Actor, limit: int = Query(20, ge=1, le=50)):
    from rt.telegram.notify_log import recent_notifications
    return recent_notifications(limit)


@router.post("/telegram/daemon/stop", response_model=DaemonStatus, summary="Ferma il bot Telegram")
def daemon_stop(_actor: Actor):
    from rt.services import service_manager as sm
    from rt.telegram.daemon_status import stop_daemon
    if sm.supported() and sm.installed(["bot"]):
        try:
            sm.stop(["bot"])  # scarica il servizio: launchd non lo rilancia
        except sm.ServiceError:
            pass
    stop_daemon()
    return daemon_status(_actor)


from rt.core.config import ClassifierConfig, ClassifierJob


class ClassifierProbeIn(ClassifierJob):
    mode: Literal["off", "manual", "observe", "pipeline"] = "manual"
    request_type: Literal["choice", "noul", "score"] = "choice"


@router.get("/settings/classifier", response_model=ClassifierConfig)
def get_classifier_settings(actor: Actor):
    from rt.core.config import load_config
    return load_config().classifier


@router.post("/settings/classifier/probe", response_model=DecisionProbeOut)
def probe_classifier_settings(body: ClassifierProbeIn, actor: Actor):
    from rt.llm.jev_client import call_jev, JevChoiceQuestion, JevNoulQuestion, JevScoreQuestion, JevError
    from rt.services.jev_playground import record_probe
    questions = {
        "choice": JevChoiceQuestion(instructions="Classifica il frutto", criteria={"banana": "Banana", "altro": "Altro"}),
        "noul": JevNoulQuestion(instructions="La banana è un frutto"),
        "score": JevScoreQuestion(instructions="Valuta la banana", criteria=["È un frutto"]),
    }
    try:
        answer = call_jev("Una banana", {"categoria": questions[body.request_type]},
            model=body.model, credential=body.credential, base_url=body.base_url,
            timeout_seconds=body.timeout_seconds, job_name="classifier_probe").answers.get("categoria")
        if answer is None or answer.type != body.request_type:
            raise ValueError("Risposta del classificatore non valida")
    except (JevError, ValueError) as exc:
        raise ApiError(422, "decision_protocol_failed", str(exc)) from exc
    record_probe(body.credential, body.model, body.request_type)
    return {"ok": True, "choice": getattr(answer, "choice", body.request_type),
            "confidence": getattr(answer, "confidence", getattr(answer, "noul", 0)), "request_type": body.request_type}


@router.put("/settings/classifier", response_model=ClassifierConfig)
def put_classifier_settings(body: ClassifierConfig, actor: Actor):
    from rt.core.config import load_config, classifier_job
    from rt.services import config_service
    from rt.services.jev_playground import probe_missing
    from rt.services.classifier_settings import write_classifier
    cfg = load_config()
    incoming = cfg.model_copy(update={"classifier": body})
    checks = []
    for name in body.jobs:
        job, old = classifier_job(incoming, name), classifier_job(cfg, name)
        if job.mode != "off" and (job.model, job.credential, job.base_url) != (old.model, old.credential, old.base_url):
            from rt.services.jev_mapping import effective_decision
            request_type = effective_decision(name, cfg.jev).type if name in ("relevance", "prefilter") else "noul" if name in ("drift", "enrichment") else "choice"
            checks.append((job.credential, job.model, request_type))
    missing = probe_missing(checks) if checks else None
    if missing:
        raise ApiError(422, "decision_probe_required", missing)
    path = config_service.general_config_path(_project_root())
    data = config_service.read_yaml(path)
    write_classifier(data, body)
    config_service.write_yaml_atomic(path, data)
    return body
