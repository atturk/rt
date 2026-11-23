"""
rt.llm.providers.base
Interfaccia base per i provider LLM e modelli di risposta normalizzati.
Disaccoppia la pipeline RT dalle specificità di DeepSeek direct, OpenRouter e altri provider.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field


class NormalizedResponse(BaseModel):
    """Risposta normalizzata indipendente dal provider."""
    content: str = Field(default="", description="Testo finale generato dal modello")
    reasoning: Optional[str] = Field(default=None, description="Chain of thought / reasoning interno se restituito")
    usage: Optional[Dict[str, Any]] = Field(default=None, description="Metadati sui token consumati")
    finish_reason: Optional[str] = Field(default=None, description="Motivo di fine generazione (stop, length, ecc.)")
    provider: str = Field(description="Nome normalizzato del provider")
    model: str = Field(description="ID o nome del modello")
    resolved_model: Optional[str] = Field(default=None, description="ID del modello realmente utilizzato dal provider (può differire dal modello richiesto, es. per router aggregatori come 'openrouter/free')")
    request_id: Optional[str] = Field(default=None, description="ID della richiesta fornito dal provider")


class BatchResultItem(BaseModel):
    """Singolo risultato di un lotto batch abbinato tramite custom_id."""
    custom_id: str
    response: Optional[NormalizedResponse] = None
    error: Optional[str] = None
    http_status: Optional[int] = None


class StreamChunk(BaseModel):
    """Singolo frammento restituito durante una sessione di streaming SSE."""
    content_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    request_id: Optional[str] = None
    resolved_model: Optional[str] = None


class BaseLLMProvider(ABC):
    """Classe base astratta per un provider LLM."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificativo del provider (es. 'deepseek', 'openrouter')."""
        pass

    @abstractmethod
    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        """Restituisce l'URL completo dell'endpoint chat/completions."""
        pass

    @abstractmethod
    def get_headers(self, api_key: str) -> Dict[str, str]:
        """Restituisce gli header HTTP per l'autenticazione verso il provider."""
        pass

    @abstractmethod
    def build_payload(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        thinking: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None,
        provider_routing: Optional[Dict[str, Any]] = None,
        response_json_schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Costruisce il payload JSON specifico per il provider."""
        pass

    @abstractmethod
    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        """Parsa una singola riga SSE (data: {...}) e restituisce uno StreamChunk se rilevante."""
        pass

    @abstractmethod
    def normalize_response(
        self,
        raw_json: Dict[str, Any],
        model_name: str,
        request_id: Optional[str] = None
    ) -> NormalizedResponse:
        """Normalizza la risposta JSON completa non in streaming nel formato standard."""
        pass

    @property
    def supports_batch(self) -> bool:
        """True se il provider supporta la modalità batch differita."""
        return False

    def batch_model(self, model: str) -> str:
        """Identificativo del modello usato in modalità batch (default: invariato)."""
        return (model or "").strip()

    def submit_batch(
        self,
        requests_list: List[Dict[str, Any]],
        *,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> str:
        """Invia un lotto di richieste ({custom_id, body}) e restituisce batch_id."""
        raise NotImplementedError(f"Il provider '{self.name}' non supporta la modalità batch.")

    def poll_batch(
        self,
        batch_id: str,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Tuple[str, Optional[Dict[str, BatchResultItem]]]:
        """Controlla lo stato di un lotto: (status, {custom_id: BatchResultItem} | None)."""
        raise NotImplementedError(f"Il provider '{self.name}' non supporta la modalità batch.")

    def cleanup_batch(
        self,
        batch_id: str,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        """Pulizia opzionale del lotto lato provider dopo il salvataggio dei risultati."""
        return None

    def cancel_batch(
        self,
        batch_id: str,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> bool:
        """Annulla un lotto lato provider se supportato. Restituisce True se annullato."""
        return False
