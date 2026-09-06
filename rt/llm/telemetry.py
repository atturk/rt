"""
rt.llm.telemetry
Modello e gestione normalizzata della telemetria delle chiamate LLM.
Ogni richiesta produce un record strutturato con latenza, token, costo stimato e stato.
"""

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
    resolved_model: Optional[str] = Field(default=None, description="ID del modello realmente utilizzato dal provider (può differire dal modello richiesto, es. per router aggregatori come 'openrouter/free')")

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

    def clear(self) -> None:
        self._records.clear()

    def get_summary(self) -> Dict[str, Any]:
        total_in = sum(r.input_tokens or 0 for r in self._records)
        total_out = sum(r.output_tokens or 0 for r in self._records)
        total_reas = sum(r.reasoning_tokens or 0 for r in self._records)
        total_tok = sum(r.total_tokens or 0 for r in self._records)
        total_cost = sum(r.estimated_cost or 0.0 for r in self._records)

        by_job: Dict[str, Dict[str, Any]] = {}
        by_provider: Dict[str, Dict[str, Any]] = {}

        for r in self._records:
            # Raggruppamento per job
            j = r.job
            if j not in by_job:
                by_job[j] = {
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                }
            by_job[j]["requests"] += 1
            by_job[j]["input_tokens"] += r.input_tokens or 0
            by_job[j]["output_tokens"] += r.output_tokens or 0
            by_job[j]["reasoning_tokens"] += r.reasoning_tokens or 0
            by_job[j]["total_tokens"] += r.total_tokens or 0
            by_job[j]["estimated_cost_usd"] = round(by_job[j]["estimated_cost_usd"] + (r.estimated_cost or 0.0), 6)

            # Raggruppamento per provider
            p = r.provider
            if p not in by_provider:
                by_provider[p] = {
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                }
            by_provider[p]["requests"] += 1
            by_provider[p]["input_tokens"] += r.input_tokens or 0
            by_provider[p]["output_tokens"] += r.output_tokens or 0
            by_provider[p]["reasoning_tokens"] += r.reasoning_tokens or 0
            by_provider[p]["total_tokens"] += r.total_tokens or 0
            by_provider[p]["estimated_cost_usd"] = round(by_provider[p]["estimated_cost_usd"] + (r.estimated_cost or 0.0), 6)

        return {
            "total_requests": len(self._records),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_reasoning_tokens": total_reas,
            "total_tokens": total_tok,
            "total_estimated_cost_usd": round(total_cost, 6),
            "by_job": by_job,
            "by_provider": by_provider,
        }

    def export_to_file(self, target_path: str) -> None:
        """Salva il riepilogo della telemetria su disco in modo atomico (file temporaneo + os.replace)."""
        import json
        import os
        summary_data = self.get_summary()
        target_dir = os.path.dirname(os.path.abspath(target_path))
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        tmp_path = target_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, target_path)


# Istanza singleton di telemetria globale per la sessione
GLOBAL_TELEMETRY = TelemetryStore()
