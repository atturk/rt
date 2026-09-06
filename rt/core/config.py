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
from pydantic import BaseModel, Field, AliasChoices, model_validator


class LLMRetryConfig(BaseModel):
    max_timeout_retries: int = Field(default=1, description="Numero massimo di retry dopo timeout sullo stesso provider")
    timeout_backoff_seconds: float = Field(default=2.0, description="Secondi di attesa (backoff) tra un tentativo e il successivo")


class RouteConfig(BaseModel):
    """Configurazione atomica di una singola route di esecuzione (provider, model, credenziale)."""
    route_id: Optional[str] = Field(default=None, description="Identificativo univoco della route")
    provider: str = Field(default="deepseek", description="deepseek | openrouter | google | mock")
    model: str = Field(default="deepseek-v4-flash", description="Identificativo del modello per il provider")
    credential: Optional[str] = Field(default=None, description="Nome simbolico della credenziale (es. google_1, google_2)")
    base_url: Optional[str] = Field(default=None)
    thinking: bool = Field(default=True, description="Abilita il thinking mode (DeepSeek reasoning o equivalenti)")
    reasoning_effort: str = Field(default="low", description="low | high | max (default: low)")
    max_thinking_tokens: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("max_thinking_tokens", "max_reasoning_tokens"),
        description="Massimo numero di token per il reasoning"
    )
    temperature: Optional[float] = Field(default=None)
    max_tokens: Optional[int] = Field(default=None)
    timeout_seconds: int = Field(default=180)

    def model_post_init(self, __context: Any) -> None:
        """Validazione config-time delle route."""
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        clean_p = self.provider.lower().strip()
        allowed_providers = {"deepseek", "openrouter", "google", "mock"}
        if clean_p not in allowed_providers:
            raise ValueError(f"Provider LLM non supportato: '{self.provider}'. Provider ammessi: {sorted(allowed_providers)}")
        if not self.model or not str(self.model).strip():
            raise ValueError(f"Il modello per il provider '{self.provider}' non può essere vuoto.")
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


def _build_default_jobs() -> Dict[str, JobRoutingConfig]:
    return {
        "outline": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=16384,
                timeout_seconds=240,
            )
        ),
        "rewrite": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=180,
            )
        ),
        "review_asr": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=120,
            )
        ),
        "review_science": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=180,
            )
        ),
    }


class RTConfig(BaseModel):
    version: str = "2.0.0"
    retry: LLMRetryConfig = Field(default_factory=LLMRetryConfig, description="Configurazione retry per timeout LLM")
    jobs: Dict[str, JobRoutingConfig] = Field(default_factory=_build_default_jobs)
    thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    mock_llm: bool = Field(default=False, description="Usa mock deterministico per test e CI")
    streaming: bool = Field(default=True, description="Abilita streaming SSE se supportato dal provider")
    show_monitor: bool = Field(default=True, description="Mostra il live terminal monitor durante le chiamate")
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
                    # Se ha già la chiave 'primary', è già nel nuovo formato
                    if "primary" in job_val:
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




def load_env_file(dotenv_path: Optional[str] = None, override: bool = False) -> None:
    """
    Carica variabili d'ambiente da un file .env locale (se presente).
    Non solleva errori se il file non esiste.
    """
    if dotenv_path is None:
        dotenv_path = os.path.join(os.getcwd(), ".env")
    
    if os.path.isfile(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if "=" in stripped:
                        k, v = stripped.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if override or k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass




def get_api_key(provider_or_credential: str) -> Optional[str]:
    """
    Recupera l'API key per il provider o la credenziale specificata (es. 'google_1', 'google_2',
    'openrouter', 'deepseek') esclusivamente da variabili d'ambiente o file .env locale.
    Non effettua ricerche su file non standard o sul Desktop.
    """
    from rt.llm.credentials import GLOBAL_CREDENTIALS
    return GLOBAL_CREDENTIALS.get_api_key(provider_or_credential)



def _parse_yaml_value(val_str: str) -> Any:
    val = val_str.strip()
    if not val:
        return None
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    lower = val.lower()
    if lower in ("true", "yes", "on"):
        return True
    if lower in ("false", "no", "off"):
        return False
    if lower in ("null", "none", "~"):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _simple_yaml_parse(text: str) -> Dict[str, Any]:
    """Parser deterministico per YAML strutturato a indentazione (senza dipendenze esterne)."""
    valid_lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        valid_lines.append((indent, stripped))

    root: Dict[str, Any] = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    
    for i, (indent, line) in enumerate(valid_lines):
        if ":" not in line:
            continue
            
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        
        # Rimuove commenti inline non protetti da virgolette
        if "#" in v and not ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
            v = v.split("#", 1)[0].strip()
            
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
            
        parent_dict = stack[-1][1]
        
        # Lookahead per verificare se la riga successiva è un sotto-blocco indentato
        has_children = (i + 1 < len(valid_lines) and valid_lines[i + 1][0] > indent)
        if not v:
            if has_children:
                new_dict: Dict[str, Any] = {}
                parent_dict[k] = new_dict
                stack.append((indent, new_dict))
            else:
                parent_dict[k] = None
        else:
            parent_dict[k] = _parse_yaml_value(v)
            
    return root


def load_config(config_path: Optional[str] = None) -> RTConfig:
    """Carica rt.config.yaml o restituisce la configurazione predefinita."""
    if config_path is None:
        config_path = os.path.join(os.getcwd(), "rt.config.yaml")
    
    if not os.path.exists(config_path):
        return RTConfig()
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        try:
            import yaml
            data = yaml.safe_load(raw_text)
        except ImportError:
            data = _simple_yaml_parse(raw_text)
            
        if isinstance(data, dict):
            return RTConfig.model_validate(data)
    except Exception:
        pass
    return RTConfig()

