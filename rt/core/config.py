"""
rt.core.config
Gestione centralizzata della configurazione e credenziali sicure.
RISPETTO RIGOROSO DEI VINCOLI DI SICUREZZA:
- Nessun file arbitrario letto dal Desktop o da percorsi personali non standard.
- Credenziali caricate ESCLUSIVAMENTE da environment variables o file .env locale.
- Nessuna chiave API scritta nei log, manifest o file esportati.
"""

import os
from typing import Dict, Any, Optional, List
import yaml
from pydantic import BaseModel, Field, AliasChoices, model_validator

from rt.llm.pricing import ModelPricing


class LLMRetryConfig(BaseModel):
    max_timeout_retries: int = Field(default=1, description="Numero massimo di retry dopo timeout sullo stesso provider")
    timeout_backoff_seconds: float = Field(default=2.0, description="Secondi di attesa (backoff) tra un tentativo e il successivo")
    idle_read_timeout_seconds: float = Field(default=45.0, description="Timeout massimo (in secondi) di inattività sul socket durante lo streaming SSE: se nessun byte arriva entro questa soglia, la lettura fallisce con TimeoutFailure indipendentemente dal deadline wall-clock complessivo del job")



KNOWN_PROVIDER_DEFAULT_BASE_URLS: Dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}


class RouteConfig(BaseModel):
    """Configurazione atomica di una singola route di esecuzione (provider, model, credenziale)."""
    route_id: Optional[str] = Field(default=None, description="Identificativo univoco della route")
    provider: Optional[str] = Field(default=None, description="deepseek | openrouter | google | openai_compatible (None = route non ancora configurata)")
    model: Optional[str] = Field(default=None, description="Identificativo del modello per il provider (None = route non ancora configurata)")
    credential: Optional[str] = Field(default=None, description="Nome simbolico della credenziale (es. google_1, google_2)")
    base_url: Optional[str] = Field(default=None)
    thinking: Optional[bool] = Field(default=None, description="True = forza il reasoning acceso, False = tenta di disattivarlo (su OpenRouter, per sicurezza, produce comunque l'omissione del campo — vedi rt/llm/providers/openrouter.py), None = non specificato, il provider/modello decide da sé")
    reasoning_effort: Optional[str] = Field(default=None, description="low | high | max (None = non specificato/lascia decidere al provider)")
    max_thinking_tokens: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("max_thinking_tokens", "max_reasoning_tokens"),
        description="Massimo numero di token per il reasoning"
    )
    temperature: Optional[float] = Field(default=None)
    max_tokens: Optional[int] = Field(default=None)
    timeout_seconds: int = Field(default=180)
    pricing: Optional[ModelPricing] = Field(default=None, description="Prezzo specifico per questa route (priorità massima: sovrascrive sia il pricing custom globale sia DEFAULT_PRICING)")
    provider_routing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Oggetto 'provider' di OpenRouter (only/ignore/quantizations/sort/allow_fallbacks/...) "
                    "per questa specifica route, impostato insieme a provider/model perché la scelta dei "
                    "backend affidabili dipende dal modello richiesto, non è una preferenza globale. "
                    "Pass-through non validato: rispecchia esattamente lo schema documentato da OpenRouter "
                    "(https://openrouter.ai/docs/guides/routing/provider-selection). Ignorato per provider diversi da 'openrouter'."
    )

    @property
    def is_configured(self) -> bool:
        return self.provider is not None and self.model is not None

    def model_post_init(self, __context: Any) -> None:
        """Validazione config-time delle route. Una route con provider=None è uno slot
        intenzionalmente non configurato (placeholder in config.example/): non viene validata
        qui. Sta al chiamante (rt/cli.py, _job_has_configured_route) verificare che una route
        configurata esista prima di eseguire lavoro reale, con un messaggio chiaro."""
        if self.provider is None:
            return
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        clean_p = self.provider.lower().strip()
        allowed_providers = {"deepseek", "openrouter", "google", "openai_compatible"}
        if clean_p not in allowed_providers:
            raise ValueError(f"Provider LLM non supportato: '{self.provider}'. Provider ammessi: {sorted(allowed_providers)}")
        if not self.model or not str(self.model).strip():
            raise ValueError(f"Il modello per il provider '{self.provider}' non può essere vuoto.")
        if clean_p == "openai_compatible" and not self.base_url:
            raise ValueError(
                "Il provider 'openai_compatible' richiede 'base_url' esplicito nella route "
                "(non esiste un endpoint di default per questo tipo di provider)."
            )

        # Validazione difensiva anti-mismatch/copia-incolla per base_url
        if self.base_url:
            clean_url = str(self.base_url).strip().rstrip("/")
            for other_prov, default_url in KNOWN_PROVIDER_DEFAULT_BASE_URLS.items():
                if clean_url == default_url.rstrip("/"):
                    if other_prov != clean_p:
                        raise ValueError(
                            f"base_url '{self.base_url}' corrisponde all'endpoint di default del provider '{other_prov}', "
                            f"ma la route dichiara provider='{self.provider}'. Probabile errore di copia-incolla: "
                            f"rimuovi base_url per usare l'endpoint corretto di '{self.provider}', "
                            f"oppure impostane uno realmente specifico per questo provider."
                        )
                    break

        if self.credential:
            clean_c = self.credential.lower().strip()
            if not GLOBAL_CREDENTIALS.validate_credential(clean_p, clean_c):
                raise ValueError(
                    f"Credenziale '{self.credential}' non valida o incompatibile con il provider '{self.provider}'."
                )
        else:
            # Assegna automaticamente la credenziale di default per il provider se disponibile
            default_c = GLOBAL_CREDENTIALS.get_default_credential_for_provider(clean_p)
            if default_c:
                self.credential = default_c

        if not self.route_id:
            cred = self.credential or "default"
            self.route_id = f"{clean_p}|{self.model.strip()}|{cred.lower().strip()}"

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name == "provider" and isinstance(value, str):
            from rt.llm.credentials import GLOBAL_CREDENTIALS
            clean_p = value.lower().strip()
            # Se la credenziale corrente non è compatibile con il nuovo provider, aggiorna alla default
            if not self.credential or not GLOBAL_CREDENTIALS.validate_credential(clean_p, self.credential):
                default_c = GLOBAL_CREDENTIALS.get_default_credential_for_provider(clean_p)
                if default_c:
                    super().__setattr__("credential", default_c)



# LLMModelConfig preservato per piena compatibilità con tipi e import esistenti
class LLMModelConfig(RouteConfig):
    pass


class JobFallbackConfig(BaseModel):
    """Mappa di failover mirata per specifiche classi di errore."""
    timeout: Optional[RouteConfig] = None
    rate_limit: Optional[RouteConfig] = None
    safety: Optional[RouteConfig] = None
    auth: Optional[RouteConfig] = None
    generic: Optional[RouteConfig] = None


class JobRoutingConfig(BaseModel):
    """Configurazione completa del routing engine per un singolo job cognitivo."""
    primary: Optional[RouteConfig] = None
    secondary: Optional[RouteConfig] = None
    primary_routes: Optional[List[RouteConfig]] = None
    round_robin: bool = False
    fallback: JobFallbackConfig = Field(default_factory=JobFallbackConfig)
    max_attempts: int = Field(default=5, ge=1, le=10, description="Cap globale della catena di esecuzione dell'unità")
    max_output_chars: Optional[int] = Field(default=45000, description="Hard guard contro output runaway")

    def model_post_init(self, __context: Any) -> None:
        if self.primary_routes:
            if not self.primary and len(self.primary_routes) > 0:
                self.primary = self.primary_routes[0]
            if not self.secondary and len(self.primary_routes) > 1:
                self.secondary = self.primary_routes[1]

        if not self.primary:
            raise ValueError("JobRoutingConfig richiede la definizione di 'primary' o 'primary_routes'.")

        if self.round_robin and not self.secondary:
            raise ValueError("Configurazione non valida: round_robin è abilitato ma manca la route 'secondary'.")

    # Proxy trasparente degli attributi verso primary per retrocompatibilità totale con codice che accede a job_cfg.provider, etc.
    def __getattr__(self, name: str) -> Any:
        # Evita ricorsioni durante serializzazione o inizializzazione
        if name in ("primary", "secondary", "primary_routes", "round_robin", "fallback", "max_attempts", "max_output_chars", "__dict__"):
            return super().__getattribute__(name)
        primary_obj = self.__dict__.get("primary")
        if primary_obj and hasattr(primary_obj, name):
            return getattr(primary_obj, name)
        raise AttributeError(f"'{type(self).__name__}' non ha l'attributo '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("primary", "secondary", "primary_routes", "round_robin", "fallback", "max_attempts", "max_output_chars"):
            super().__setattr__(name, value)
        elif hasattr(self, "primary") and hasattr(self.primary, name):
            setattr(self.primary, name, value)
        else:
            super().__setattr__(name, value)


class ConfidenceThresholds(BaseModel):
    green: float = Field(default=0.95, description=">= green -> Auto-apply con tracciamento")
    yellow: float = Field(default=0.75, description=">= yellow e < green -> Coda di revisione")


def _build_default_jobs() -> Dict[str, "JobRoutingConfig"]:
    """Restituisce un dizionario di job con route primaria a guscio vuoto (provider/model a None,
    già il default di RouteConfig). Usato come default_factory per RTConfig.jobs: ogni installazione
    reale deve configurare esplicitamente provider e modello nel proprio config/ (o config.yaml).
    'thinking'/'max_tokens'/'timeout_seconds' restano invece opinionati per job: sono parametri di
    qualità/costo della route, non credenziali, e non fanno parte del concetto di 'guscio vuoto'."""
    empty_shell = lambda thinking=True, max_tokens=8192, timeout=180: JobRoutingConfig(
        primary=RouteConfig(
            provider=None,
            model=None,
            base_url=None,
            thinking=thinking,
            reasoning_effort="low",
            max_tokens=max_tokens,
            timeout_seconds=timeout,
        )
    )
    return {
        "outline": empty_shell(max_tokens=16384, timeout=240),
        "rewrite": empty_shell(max_tokens=8192, timeout=180),
        "review_asr": empty_shell(max_tokens=8192, timeout=120),
        "review_science": empty_shell(max_tokens=8192, timeout=180),
        "recall_quiz": empty_shell(max_tokens=8192, timeout=120),
        "recall_mirata": empty_shell(max_tokens=8192, timeout=120),
        "recall_vasta": empty_shell(max_tokens=8192, timeout=120),
        "recall_eval_mirata": empty_shell(max_tokens=4096, timeout=120),
        "recall_eval_vasta": empty_shell(max_tokens=4096, timeout=180),
    }



class TelegramRuntimeConfig(BaseModel):
    default_channel: str = Field(default="terminal", description="'terminal' | 'telegram', usato quando --channel non è passato a 'rt run'")
    wait_timeout_seconds: int = Field(default=0, description="0 = nessun timeout, attende indefinitamente (Ctrl+C per uscire)")
    state_dir: str = Field(default=".rt_telegram", description="Cartella di stato Telegram, relativa alla cwd da cui gira 'rt'")
    topics: Dict[str, int] = Field(
        default_factory=dict,
        description="Mappa materia (uppercase, es. 'BIOCHIMICA') -> message_thread_id del topic Telegram dedicato nel gruppo. \"Materie assenti dalla mappa vanno nel topic 'Generale' (nessun message_thread_id inviato).\""
    )
    # ------------------------------------------------------
    # Recall configuration
    # ------------------------------------------------------
    class RecallConfig(BaseModel):
        reserve_targets: Dict[str, int] = Field(default_factory=lambda: {"mirata": 4, "quiz": 6, "vasta": 2})
        refill_threshold: int = 3
        refill_batch_size: int = 4
        stt_engine: str = Field(default="macwhisper", description="'macwhisper' | 'api'")
    recall: "TelegramRuntimeConfig.RecallConfig" = Field(default_factory=RecallConfig)


class RTConfig(BaseModel):
    version: str = "2.0.0"
    retry: LLMRetryConfig = Field(default_factory=LLMRetryConfig, description="Configurazione retry per timeout LLM")
    jobs: Dict[str, JobRoutingConfig] = Field(default_factory=_build_default_jobs)
    thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    telegram: TelegramRuntimeConfig = Field(default_factory=TelegramRuntimeConfig)
    mock_llm: bool = Field(default=False, description="Usa mock deterministico per test e CI")
    streaming: bool = Field(default=True, description="Abilita streaming SSE se supportato dal provider")
    show_monitor: bool = Field(default=True, description="Mostra il live terminal monitor durante le chiamate")
    show_monitor_verbose: bool = Field(default=False, description="Se True, mostra il box dettagliato multi-riga invece della riga compatta di default")
    pricing: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, description="Pricing custom opzionale per provider e modello")

    @property
    def llm(self) -> Dict[str, JobRoutingConfig]:
        """Restituisce il dizionario unificato dei job (identità d'oggetto con jobs)."""
        return self.jobs

    @llm.setter
    def llm(self, val: Dict[str, JobRoutingConfig]) -> None:
        self.jobs = val

    @model_validator(mode="before")
    @classmethod
    def normalize_llm_and_jobs_config(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # 0. Registrazione delle credenziali custom dichiarate in YAML (es. per 'openai_compatible'),
        #    PRIMA che le RouteConfig vengano validate più sotto (altrimenti la validazione fallirebbe
        #    perché il nome della credenziale non sarebbe ancora noto al registry).
        raw_credentials = data.get("credentials")
        if isinstance(raw_credentials, list):
            from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
            for entry in raw_credentials:
                if isinstance(entry, dict):
                    cred_name = entry.get("name")
                    cred_provider = entry.get("provider")
                    cred_env_var = entry.get("env_var")
                    if cred_name and cred_provider and cred_env_var:
                        GLOBAL_CREDENTIALS.register(CredentialRef(name=cred_name, provider=cred_provider, env_var=cred_env_var))

        # 1. Estrazione retry da llm.retry se collocato lì in configurazioni legacy
        llm_section = data.get("llm")
        if isinstance(llm_section, dict) and "retry" in llm_section:
            retry_val = llm_section.pop("retry")
            if "retry" not in data:
                data["retry"] = retry_val

        # 2. Normalizzazione sezioni: supporta sia jobs: che llm:
        raw_source = data.get("jobs") or data.get("llm")
        if isinstance(raw_source, dict):
            normalized_jobs: Dict[str, Any] = {}
            for job_name, job_val in raw_source.items():
                if job_name in ("retry", "default"):
                    continue
                if isinstance(job_val, dict):
                    # Se ha già la chiave 'primary' o 'primary_routes', è già nel nuovo formato
                    if "primary" in job_val or "primary_routes" in job_val:
                        normalized_jobs[job_name] = job_val
                    else:
                        # Formato legacy: l'intero dizionario è la route primaria
                        normalized_jobs[job_name] = {
                            "primary": job_val,
                            "round_robin": False,
                            "max_attempts": 5
                        }
                elif isinstance(job_val, (RouteConfig, JobRoutingConfig)):
                    if isinstance(job_val, JobRoutingConfig):
                        normalized_jobs[job_name] = job_val
                    else:
                        normalized_jobs[job_name] = JobRoutingConfig(primary=job_val)
            if normalized_jobs:
                data["jobs"] = normalized_jobs
                if "llm" in data:
                    del data["llm"]

        return data




def _default_project_root() -> str:
    """Cartella reale del progetto, derivata dalla posizione del pacchetto 'rt'
    stesso (rt/__init__.py sta in <project_root>/rt/), indipendente dalla cwd
    della shell da cui è stato lanciato 'rt'."""
    import rt
    return os.path.dirname(os.path.dirname(os.path.abspath(rt.__file__)))


def _resolve_telegram_state_dir(cfg: RTConfig, anchor_dir: str) -> RTConfig:
    if not os.path.isabs(cfg.telegram.state_dir):
        cfg.telegram.state_dir = os.path.join(anchor_dir, cfg.telegram.state_dir)
    return cfg


def load_env_file(dotenv_path: Optional[str] = None, override: bool = False) -> None:
    """
    Carica variabili d'ambiente da un file .env locale (se presente).
    Cerca prima nella cwd corrente (comportamento invariato per chi lancia 'rt'
    da dentro la project root); se non lo trova lì, usa la project root reale
    (posizione del pacchetto 'rt'), per funzionare anche lanciando 'rt' da
    qualunque altra cartella. Non solleva errori se il file non esiste in nessuna
    delle due posizioni.
    """
    from dotenv import load_dotenv
    if dotenv_path is None:
        cwd_path = os.path.join(os.getcwd(), ".env")
        dotenv_path = cwd_path if os.path.isfile(cwd_path) else os.path.join(_default_project_root(), ".env")
    load_dotenv(dotenv_path=dotenv_path, override=override)


def get_api_key(provider_or_credential: str) -> Optional[str]:
    """
    Recupera l'API key per il provider o la credenziale specificata (es. 'google_1', 'google_2',
    'openrouter', 'deepseek') esclusivamente da variabili d'ambiente o file .env locale.
    Non effettua ricerche su file non standard o sul Desktop.
    """
    from rt.llm.credentials import GLOBAL_CREDENTIALS
    return GLOBAL_CREDENTIALS.get_api_key(provider_or_credential)




def _load_rtconfig_from_file(path: str) -> RTConfig:
    """Carica un singolo file YAML e lo valida come RTConfig. Comportamento invariato
    rispetto alla load_config() precedente per un path esplicito."""
    if not os.path.exists(path):
        return RTConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        data = yaml.safe_load(raw_text)
        if isinstance(data, dict):
            return RTConfig.model_validate(data)
    except Exception:
        pass
    return RTConfig()


_NON_JOB_YAML_FILENAMES = {"recall_lessons.yaml"}


def find_job_yaml_paths(config_dir: str) -> Dict[str, str]:
    """Cerca ricorsivamente in config_dir tutti i file <job>.yaml (nome file, senza
    estensione, = nome del job) tranne il 'general.yaml' della cartella radice e i
    file elencati in _NON_JOB_YAML_FILENAMES (config non di routing LLM, es.
    config/telegram/recall_lessons.yaml, letto a parte da rt.telegram.recall_lessons —
    non ha la forma di un JobRoutingConfig e romperebbe la validazione se trattato come job).
    Ritorna {job_name: path_assoluto}. La struttura di sottocartelle è libera
    (es. config/rt/outline.yaml, config/telegram/recall_quiz.yaml, o tutto piatto
    come prima): il codice non impone né assume alcuna organizzazione specifica."""
    result: Dict[str, str] = {}
    config_dir_abs = os.path.abspath(config_dir)
    for root, _dirs, files in os.walk(config_dir_abs):
        for fname in sorted(files):
            if not fname.endswith(".yaml"):
                continue
            if fname in _NON_JOB_YAML_FILENAMES:
                continue
            full_path = os.path.join(root, fname)
            if fname == "general.yaml" and os.path.dirname(full_path) == config_dir_abs:
                continue
            job_name = fname[:-len(".yaml")]
            result[job_name] = full_path
    return result


def _load_config_dir(config_dir: str) -> RTConfig:
    """Carica la configurazione divisa: config/general.yaml (impostazioni globali, solo
    nella cartella radice) + un file <job>.yaml per ciascun job, cercato ricorsivamente
    in tutta la cartella (nome del file, senza estensione = chiave in 'jobs') — la
    struttura di sottocartelle in cui vengono organizzati i job.yaml è a scelta libera."""
    merged_data: Dict[str, Any] = {}

    general_path = os.path.join(config_dir, "general.yaml")
    if os.path.isfile(general_path):
        with open(general_path, "r", encoding="utf-8") as f:
            general_data = yaml.safe_load(f.read())
        if isinstance(general_data, dict):
            merged_data.update(general_data)

    jobs_data: Dict[str, Any] = {}
    for job_name, job_path in sorted(find_job_yaml_paths(config_dir).items()):
        with open(job_path, "r", encoding="utf-8") as f:
            job_data = yaml.safe_load(f.read())
        if isinstance(job_data, dict):
            jobs_data[job_name] = job_data
    if jobs_data:
        merged_data["jobs"] = jobs_data

    return RTConfig.model_validate(merged_data)


def load_config(config_path: Optional[str] = None) -> RTConfig:
    """Carica la configurazione. Se config_path è esplicito, comportamento invariato.
    Altrimenti: usa 'config/' nella cwd se presente (comportamento invariato per chi
    lancia 'rt' da dentro la project root); se non c'è, prova 'config/' nella project
    root reale (posizione del pacchetto 'rt'), per funzionare anche lanciando 'rt' da
    qualunque altra cartella; se non trovata in nessuna delle due, restituisce i
    default (il chiamante a livello CLI verifica esplicitamente l'esistenza di una
    sorgente reale prima di eseguire lavoro — vedi rt/cli.py, _has_real_config_source)."""
    if config_path is not None:
        cfg = _load_rtconfig_from_file(config_path)
        return _resolve_telegram_state_dir(cfg, os.path.dirname(os.path.abspath(config_path)))

    cwd_config_dir = os.path.join(os.getcwd(), "config")
    if os.path.isdir(cwd_config_dir):
        return _resolve_telegram_state_dir(_load_config_dir(cwd_config_dir), os.getcwd())

    project_root = _default_project_root()
    root_config_dir = os.path.join(project_root, "config")
    if os.path.isdir(root_config_dir):
        return _resolve_telegram_state_dir(_load_config_dir(root_config_dir), project_root)

    return _resolve_telegram_state_dir(RTConfig(), project_root)



