"""Impostazioni della web app, segreti e notifiche Telegram.
Nessuna risposta contiene mai il valore di un segreto: solo "impostato sì/no"."""
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError, require_telegram
from rt.core.jev_decision import JevDecisionConfig

router = APIRouter(tags=["impostazioni"])

# Il router personale entra nello stesso punto di registrazione delle impostazioni.
from rt.api.routers.preferences import router as preferences_router
router.include_router(preferences_router)
from rt.api.routers.question_settings import router as questions_router
router.include_router(questions_router)


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
    recommended: str = Field(description="Motore consigliato su questo sistema")
    macparakeet_available: bool = Field(description="macparakeet può girare qui (solo macOS)")
    macparakeet_installed: bool
    parakeet_available: bool = Field(description="Parakeet ONNX installato (il modello si scarica al primo uso)")
    parakeet_model_ready: bool


class TelegramSettings(BaseModel):
    enabled: bool = Field(False, description="Notifiche Telegram attive nella chat personale (spente di predefinito)")
    bot_token_set: bool
    bot_token_preview: Optional[str] = Field(None, description="Primi e ultimi caratteri del token (es. 1234…wXyZ); "
                                                               "il valore completo solo con POST /settings/telegram/reveal")
    chat_id_set: bool = False
    chat_id_preview: Optional[str] = Field(None, description="Primi e ultimi caratteri del Chat ID")


class WorkerSettings(BaseModel):
    running: int = Field(0, description="Worker attivi ora (uno per job eseguibile insieme)")


class NoticeSettings(BaseModel):
    dismissed: List[str] = Field(description="Avvisi nascosti con 'Non mostrare più' (preview_edit_beta, preview_edit_issues, setup_wizard)")


class NoticeIn(BaseModel):
    notice: Literal["preview_edit_beta", "preview_edit_issues", "setup_wizard"]
    dismissed: bool = True


class WebSearchSettings(BaseModel):
    searxng_base_url: Optional[str] = Field(None, description="URL base di SearXNG per la ricerca immagini web")
    contextual_verification: bool = Field(default=False, description="Cerca sul web durante la verifica contestuale")


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
    engine: Literal["macparakeet", "parakeet", "custom"]
    base_url: str = ""
    model: str = ""
    api_key: Optional[str] = Field(None, description="Lascia vuoto per non cambiarla")


class TelegramIn(BaseModel):
    bot_token: Optional[str] = Field(None, description="Lascia vuoto per non cambiarlo")
    chat_id: Optional[str] = Field(None, description="ID della chat personale; lascia vuoto per non cambiarlo")


class TelegramChatIn(BaseModel):
    bot_token: Optional[str] = Field(None, description="Token nuovo da salvare insieme alla chat; vuoto = quello salvato")


class TelegramChatOut(BaseModel):
    found: bool
    name: Optional[str] = Field(None, description="Nome della chat trovata")
    message: str


class TelegramTestOut(BaseModel):
    ok: bool
    message: str


class RevealIn(BaseModel):
    field: Literal["bot_token", "chat_id"]


class RevealOut(BaseModel):
    field: str
    value: Optional[str] = Field(None, description="Valore completo, null se non impostato")


class Notification(BaseModel):
    sent_at: str
    kind: str = Field(description="lezione_pronta, decisione, errore o prova")
    text: str
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
    searxng_base_url: Optional[str] = Field(None, description="Vuoto per rimuoverlo; assente o null lo lascia invariato")
    contextual_verification: Optional[bool] = Field(None, description="Cerca sul web durante la verifica contestuale")


class WebSearchTestIn(BaseModel):
    searxng_base_url: str
    mock: bool = False


class WebSearchTestOut(BaseModel):
    ok: bool
    results: int = Field(description="Immagini restituite dalla ricerca di prova")
    latency_ms: Optional[int] = None
    message: str


# ---------------------------------------------------------------- lettura

@router.get("/settings", response_model=Settings, summary="Tutte le impostazioni (nessun valore segreto)")
def get_settings(_actor: Actor):
    from rt.services.settings_service import snapshot
    return snapshot(_project_root())


# ---------------------------------------------------------------- scrittura

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


@router.put("/settings/telegram/enabled", response_model=Settings, summary="Accende o spegne le notifiche Telegram")
def put_telegram_enabled(body: TelegramEnabledIn, _actor: Actor):
    from rt.services.settings_service import set_telegram_enabled, snapshot
    _call(set_telegram_enabled, _project_root(), body.enabled)
    return snapshot(_project_root())


@router.put("/settings/telegram", response_model=Settings, summary="Notifiche Telegram: token del bot e chat personale")
def put_telegram(body: TelegramIn, _actor: Actor):
    from rt.services.settings_service import save_telegram, snapshot
    _call(save_telegram, _project_root(), body.bot_token or "", body.chat_id or "")
    return snapshot(_project_root())


@router.post("/settings/telegram/chat", response_model=TelegramChatOut,
             summary="Trova la chat di chi ha scritto /start al bot e la salva per le notifiche")
def find_telegram_chat(body: TelegramChatIn, _actor: Actor):
    from rt.services.settings_service import save_telegram, telegram_value
    from rt.telegram.client import TelegramAPIError
    from rt.telegram.notify import detect_private_chat
    token = (body.bot_token or "").strip() or telegram_value("bot_token")
    if not token:
        raise ApiError(409, "telegram_not_configured", "Incolla prima il token del bot.")
    try:
        chat = detect_private_chat(token)
    except TelegramAPIError as exc:
        raise ApiError(502, "telegram_unreachable", str(exc).replace(token, "[token]"))
    if chat is None:
        return TelegramChatOut(found=False, message="Nessun messaggio ricevuto: scrivi /start al bot su Telegram e riprova.")
    _call(save_telegram, _project_root(), (body.bot_token or "").strip(), chat["chat_id"])
    return TelegramChatOut(found=True, name=chat["name"] or None,
                           message=f"Chat collegata{': ' + chat['name'] if chat['name'] else ''}.")


@router.post("/settings/telegram/reveal", response_model=RevealOut,
             summary="Valore completo del token del bot o del Chat ID, solo su richiesta esplicita")
def reveal_telegram(body: RevealIn, response: Response, _actor: Actor):
    from rt.services.settings_service import telegram_value
    response.headers["Cache-Control"] = "no-store"
    return RevealOut(field=body.field, value=telegram_value(body.field) or None)


@router.post("/settings/telegram/test", response_model=TelegramTestOut, summary="Manda un messaggio di prova nella chat")
def test_telegram(_actor: Actor):
    require_telegram()
    from rt.telegram.notify import send_test
    return send_test()


@router.get("/telegram/notifications", response_model=List[Notification],
            summary="Ultime notifiche inviate (lezione pronta, decisioni, errori, prove)")
def notifications(_actor: Actor, limit: int = Query(20, ge=1, le=50)):
    from rt.telegram.notify_log import recent_notifications
    return recent_notifications(limit)


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
    from rt.services.jev_playground import check_phase
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


@router.put("/settings/web-search", response_model=Settings, summary="Ricerca web: URL base di SearXNG e verifica contestuale")
def put_web_search(body: WebSearchIn, _actor: Actor):
    from rt.services.settings_service import save_web_search, snapshot
    _call(save_web_search, _project_root(), body.searxng_base_url, body.contextual_verification)
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


# ---------------------------------------------------------------- chiave sola lettura (AP1)

class ReadonlyKeyInfo(BaseModel):
    configured: bool
    created_at: Optional[str] = None
    key_preview: Optional[str] = None


class ReadonlyKeyCreated(BaseModel):
    key: str
    created_at: str
    key_preview: str


class ReadonlyKeyRevoked(BaseModel):
    ok: bool = True


@router.get("/settings/readonly-key", response_model=ReadonlyKeyInfo, summary="Informazioni sulla chiave di sola lettura (AP1)")
def get_readonly_key(_actor: Actor):
    from rt.api.readonly_auth import get_readonly_key_info
    return get_readonly_key_info()


@router.post("/settings/readonly-key", response_model=ReadonlyKeyCreated, summary="Crea o rigenera la chiave di sola lettura (AP1)")
def post_readonly_key(_actor: Actor):
    from rt.api.readonly_auth import create_readonly_key, get_readonly_key_info
    token = create_readonly_key()
    info = get_readonly_key_info()
    return ReadonlyKeyCreated(key=token, created_at=info["created_at"] or "", key_preview=info["key_preview"] or "")


@router.delete("/settings/readonly-key", response_model=ReadonlyKeyRevoked, summary="Revoca la chiave di sola lettura (AP1)")
def delete_readonly_key(_actor: Actor):
    from rt.api.readonly_auth import revoke_readonly_key
    revoke_readonly_key()
    return ReadonlyKeyRevoked(ok=True)
