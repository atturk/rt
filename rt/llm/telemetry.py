"""
rt.llm.telemetry
Modello e gestione normalizzata della telemetria delle chiamate LLM.
Ogni richiesta produce un record strutturato con latenza, token, costo stimato e stato.
"""

import time
import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class LLMTelemetryRecord(BaseModel):
    request_id: str = Field(description="Identificativo univoco della richiesta")
    execution_id: Optional[str] = Field(default=None, description="Identificativo univoco dell'intera catena di esecuzione dell'unità")
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat(), description="Timestamp ISO 8601")
    job: str = Field(description="Nome del job cognitivo (outline, rewrite, review_asr, review_science, general)")
    unit_id: Optional[str] = Field(default=None, description="Identificativo dell'unità didattica (se applicabile)")
    provider: str = Field(description="Nome del provider (deepseek, openrouter, google, mock)")
    model: str = Field(description="Nome o ID del modello utilizzato")

    # Routing e Credenziali
    route_id: Optional[str] = Field(default=None, description="Identificatore deterministico provider|model|credential")
    route_role: Optional[str] = Field(default=None, description="primary | secondary | fallback_timeout | fallback_rate_limit | fallback_safety | fallback_auth | fallback_generic")
    credential_ref: Optional[str] = Field(default=None, description="Nome simbolico della credenziale usata (es. google_1, google_2, openrouter, deepseek)")

    # Gestione tentativi e ciclo di vita attempt
    attempt: int = Field(default=1, description="Numero progressivo del tentativo (1-indexed)")
    parent_attempt: Optional[int] = Field(default=None, description="Indice dell'attempt che ha originato il failover")
    started_at: Optional[str] = Field(default=None, description="Timestamp ISO di inizio tentativo")
    ended_at: Optional[str] = Field(default=None, description="Timestamp ISO di fine tentativo")
    elapsed_seconds: float = Field(default=0.0, description="Durata wall-clock effettiva dell'attempt in secondi")
    timeout_seconds_configured: Optional[int] = Field(default=None, description="Timeout wall-clock configurato per questa attempt")
    retry_count: int = Field(default=0, description="Numero di retry già effettuati prima di questa attempt")

    # Failover metadata
    failure_class: Optional[str] = Field(default=None, description="Classe normalizzata del fallimento (timeout, rate_limit, safety, auth_error, network_error, server_error, schema_error, output_limit, success)")
    fallback_reason: Optional[str] = Field(default=None, description="Causa scatenante il fallback verso questa route")
    fallback_to_provider: Optional[str] = Field(default=None, description="Provider verso cui si effettua il fallback")
    fallback_to_model: Optional[str] = Field(default=None, description="Modello verso cui si effettua il fallback")
    fallback_to_credential: Optional[str] = Field(default=None, description="Credenziale verso cui si effettua il fallback")

    # Conteggi token e caratteri
    input_tokens: Optional[int] = Field(default=None, description="Token di input/prompt")
    reasoning_tokens: Optional[int] = Field(default=None, description="Token generati durante il reasoning")
    output_tokens: Optional[int] = Field(default=None, description="Token di output/completion")
    total_tokens: Optional[int] = Field(default=None, description="Token complessivi consumati")
    output_chars: int = Field(default=0, description="Caratteri di completamento ricevuti")

    # Metriche streaming
    time_to_first_token: Optional[float] = Field(default=None, description="Latenza in secondi all'arrivo del primo chunk/token")
    stream_duration: Optional[float] = Field(default=None, description="Durata in secondi della fase di streaming")
    last_chunk_at: Optional[str] = Field(default=None, description="Timestamp ISO dell'ultimo chunk ricevuto")

    # Stato, errori ed esito HTTP
    latency_ms: float = Field(default=0.0, description="Latenza totale della chiamata in millisecondi")
    finish_reason: Optional[str] = Field(default=None, description="Causa di terminazione della generazione (stop, length, content_filter, ecc.)")
    status: str = Field(default="success", description="Stato dell'attempt (success, timeout, error, ecc.)")
    error_class: Optional[str] = Field(default=None, description="Classe normalizzata dell'errore (retrocompatibilità)")
    http_status: Optional[int] = Field(default=None, description="Codice HTTP restituito (se disponibile)")
    error_message: Optional[str] = Field(default=None, description="Messaggio di errore sanitizzato in caso di fallimento")

    # Costo e modalità
    estimated_cost: Optional[float] = Field(default=None, description="Costo stimato in USD della richiesta")
    streaming: bool = Field(default=True, description="Indica se la chiamata è stata eseguita in streaming")

    def sanitize_secrets(self) -> None:
        """Garantisce che nessun secret/chiave API compaia nel record."""
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        if self.error_message:
            self.error_message = GLOBAL_CREDENTIALS.sanitize_secrets(self.error_message)




class TelemetryStore:
    """Archivio centralizzato in-memory per i record di telemetria della sessione."""

    def __init__(self):
        self._records: List[LLMTelemetryRecord] = []

    def add(self, record: LLMTelemetryRecord) -> None:
        record.sanitize_secrets()
        self._records.append(record)

    def get_last(self) -> Optional[LLMTelemetryRecord]:
        return self._records[-1] if self._records else None

    def get_all(self, job: Optional[str] = None) -> List[LLMTelemetryRecord]:
        if job:
            return [r for r in self._records if r.job == job]
        return list(self._records)

    def get_records(self, job: Optional[str] = None) -> List[LLMTelemetryRecord]:
        """Alias per get_all."""
        return self.get_all(job=job)

    def clear(self) -> None:
        self._records.clear()

    def get_summary(self) -> Dict[str, Any]:
        total_in = sum(r.input_tokens or 0 for r in self._records)
        total_out = sum(r.output_tokens or 0 for r in self._records)
        total_reas = sum(r.reasoning_tokens or 0 for r in self._records)
        total_tok = sum(r.total_tokens or 0 for r in self._records)
        total_cost = sum(r.estimated_cost or 0.0 for r in self._records)

        return {
            "total_requests": len(self._records),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_reasoning_tokens": total_reas,
            "total_tokens": total_tok,
            "total_estimated_cost_usd": round(total_cost, 6),
        }


# Istanza singleton di telemetria globale per la sessione
GLOBAL_TELEMETRY = TelemetryStore()
