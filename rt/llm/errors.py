"""
rt.llm.errors
Tassonomia centralizzata e normalizzazione formale di tutti i failure classes per RT 2.0.

Disaccoppia l'analisi del fallimento dal client HTTP e dal Routing Engine.
Tutti i messaggi sono sanitizzati per garantire l'assenza totale di secret leak.
"""

import re
from typing import Optional, Dict, Any
from rt.llm.credentials import GLOBAL_CREDENTIALS


class LLMFailure(Exception):
    """Classe base per ogni anomalia o fallimento durante una chiamata LLM."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        http_status: Optional[int] = None,
        raw_error: Optional[Any] = None
    ):
        sanitized = GLOBAL_CREDENTIALS.sanitize_secrets(str(message))
        super().__init__(sanitized)
        self.message = sanitized
        self.provider = provider
        self.model = model
        self.http_status = http_status
        self.raw_error = raw_error
        self.failure_class = "error"

    def __str__(self) -> str:
        return self.message


class TimeoutFailure(LLMFailure):
    """Sollevata quando la deadline wall-clock o socket dell'attempt viene superata."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "timeout"


class RateLimitFailure(LLMFailure):
    """Sollevata in presenza di HTTP 429, quota esaurita o limitazione di banda."""
    def __init__(self, message: str, retry_after: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.failure_class = "rate_limit"


class SafetyFailure(LLMFailure):
    """Sollevata in caso di blocco di contenuto, content filter o prompt feedback Gemini/OpenRouter."""
    def __init__(self, message: str, finish_reason: str = "content_filter", safety_details: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.finish_reason = finish_reason
        self.safety_details = safety_details
        self.failure_class = "safety"


class AuthenticationFailure(LLMFailure):
    """Sollevata in caso di credenziale assente, non valida, HTTP 401 o 403."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "auth_error"


class NetworkFailure(LLMFailure):
    """Sollevata in presenza di errori di trasporto, socket reset, broken pipe o DNS."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "network_error"


class ProviderServerFailure(LLMFailure):
    """Sollevata quando il server remoto risponde con HTTP 5xx."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "server_error"


class SchemaFailure(LLMFailure):
    """Sollevata quando l'output non rispetta lo schema JSON/Pydantic dopo l'esaurimento dei repair turns."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "schema_error"


class OutputLimitFailure(LLMFailure):
    """Sollevata quando l'Output Explosion Guard interrompe uno stream runaway."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "output_limit"


class ReasoningRequiredFailure(LLMFailure):
    """Sollevata quando il provider richiede reasoning obbligatorio non configurato
    (tipico di alcuni modelli specifici dietro router aggregatori come 'openrouter/free')."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "reasoning_required"


class SuspiciousFastResponseFailure(LLMFailure):
    """Sollevata quando un modello free-tier (tipicamente dietro 'openrouter/free') restituisce
    un risultato sintatticamente valido ma sospettosamente veloce, probabile segno di una
    risposta 'lazy' senza reasoning effettivo (rilevante per job di analisi come review_asr/review_science,
    dove un output minimale/vuoto è indistinguibile da un'analisi vera che non ha trovato nulla)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "suspicious_fast_response"


class UserAbortedFailure(LLMFailure):
    """Sollevata quando l'utente interrompe manualmente (Ctrl+C) un tentativo di streaming in corso."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "user_aborted"


class UnknownProviderFailure(LLMFailure):
    """Sollevata per errori imprevisti non mappabili in altre categorie."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "unknown_error"


# Alias retrocompatibili con il codice storico
LLMError = LLMFailure
LLMTimeoutError = TimeoutFailure


def parse_retry_after(headers: Optional[Dict[str, str]] = None, text: Optional[str] = None) -> Optional[float]:
    """Estrae i secondi da un header Retry-After o dal testo del messaggio."""
    if headers:
        for k, v in headers.items():
            if k.lower() == "retry-after":
                try:
                    return float(v)
                except ValueError:
                    pass
    if text:
        match = re.search(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def classify_failure(
    exception: Optional[Exception] = None,
    http_status: Optional[int] = None,
    finish_reason: Optional[str] = None,
    raw_response: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
) -> LLMFailure:
    """
    Classificatore centralizzato deterministico: traduce qualsiasi anomalia, codice HTTP,
    finish_reason o eccezione nella corrispondente istanza di LLMFailure.
    """
    if isinstance(exception, LLMFailure):
        return exception

    err_str = str(exception or raw_response or "").strip()
    clean_fr = str(finish_reason or "").lower().strip()

    # 1. Output explosion guard
    if isinstance(exception, OutputLimitFailure) or "output explosion" in err_str.lower():
        return OutputLimitFailure(err_str, provider=provider, model=model, http_status=http_status)

    # 2. Timeout (wall-clock o socket)
    if (
        isinstance(exception, (TimeoutError, TimeoutFailure)) or
        "timeout" in type(exception or object()).__name__.lower() or
        "deadline wall-clock" in err_str.lower() or
        "timed out" in err_str.lower()
    ):
        return TimeoutFailure(err_str or "Deadline superata", provider=provider, model=model, http_status=http_status)

    # 3. Safety / Content filter (Google Gemini block o OpenRouter content_filter)
    is_safety = (
        clean_fr in ("content_filter", "safety", "blocked") or
        "content_filter" in err_str.lower() or
        "promptfeedback" in err_str.lower() or
        "blockreason" in err_str.lower() or
        "safety" in err_str.lower() and ("policy" in err_str.lower() or "filter" in err_str.lower() or "violation" in err_str.lower())
    )
    if is_safety:
        return SafetyFailure(
            err_str or f"Blocco safety/content_filter rilevato (finish_reason='{finish_reason}')",
            provider=provider,
            model=model,
            http_status=http_status,
            finish_reason=clean_fr or "content_filter"
        )

    # 4. Rate limit (HTTP 429 o messaggio quota)
    if http_status == 429 or "rate limit" in err_str.lower() or "too many requests" in err_str.lower() or "quota" in err_str.lower():
        retry_sec = parse_retry_after(headers, err_str)
        return RateLimitFailure(
            err_str or "Rate limit superato (HTTP 429)",
            retry_after=retry_sec,
            provider=provider,
            model=model,
            http_status=http_status or 429
        )

    # 5. Autenticazione (HTTP 401, 403 o chiave mancante/invalida)
    if (
        http_status in (401, 403) or
        "unauthorized" in err_str.lower() or
        "api key mancante" in err_str.lower() or
        "invalid api key" in err_str.lower() or
        "authentication" in err_str.lower() or
        "permission_denied" in err_str.lower()
    ):
        return AuthenticationFailure(
            err_str or f"Errore autenticazione (HTTP {http_status})",
            provider=provider,
            model=model,
            http_status=http_status
        )

    # 6. Errori Server Provider (HTTP 5xx)
    if http_status and 500 <= http_status < 600:
        return ProviderServerFailure(
            err_str or f"Server error provider (HTTP {http_status})",
            provider=provider,
            model=model,
            http_status=http_status
        )

    # 7. Errori di Rete / Connessione
    if (
        "connection" in type(exception or object()).__name__.lower() or
        "connectionerror" in err_str.lower() or
        "broken pipe" in err_str.lower() or
        "connection reset" in err_str.lower() or
        "name resolution" in err_str.lower()
    ):
        return NetworkFailure(
            err_str or "Errore di connessione di rete",
            provider=provider,
            model=model,
            http_status=http_status
        )

    # 8. Errori di Schema / Validazione Pydantic
    if (
        "json non valido" in err_str.lower() or
        "jsondecodeerror" in err_str.lower() or
        "validazione schema pydantic" in err_str.lower() or
        "content vuoto" in err_str.lower()
    ):
        return SchemaFailure(
            err_str or "Errore conformità schema strutturato",
            provider=provider,
            model=model,
            http_status=http_status
        )

    # 8.5 Reasoning obbligatorio non configurato (tipico di alcuni modelli dietro router 'xxx/free')
    if (
        http_status == 400 and (
            "reasoning is mandatory" in err_str.lower() or
            "reasoning is required" in err_str.lower() or
            ("reasoning" in err_str.lower() and "cannot be disabled" in err_str.lower())
        )
    ):
        return ReasoningRequiredFailure(
            err_str or "Il modello selezionato richiede reasoning obbligatorio non configurato",
            provider=provider,
            model=model,
            http_status=http_status
        )

    # 9. Default sconosciuto
    return UnknownProviderFailure(
        err_str or "Errore provider non classificato",
        provider=provider,
        model=model,
        http_status=http_status
    )
