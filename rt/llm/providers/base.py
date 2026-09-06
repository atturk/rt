"""
rt.llm.providers.base
Interfaccia base per i provider LLM e modelli di risposta normalizzati.
Disaccoppia la pipeline RT dalle specificità di DeepSeek direct, OpenRouter e altri provider.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class NormalizedResponse(BaseModel):
    """Risposta normalizzata indipendente dal provider."""
    content: str = Field(default="", description="Testo finale generato dal modello")
    reasoning: Optional[str] = Field(default=None, description="Chain of thought / reasoning interno se restituito")
    usage: Optional[Dict[str, Any]] = Field(default=None, description="Metadati sui token consumati")
    finish_reason: Optional[str] = Field(default=None, description="Motivo di fine generazione (stop, length, ecc.)")
    provider: str = Field(description="Nome normalizzato del provider")
    model: str = Field(description="ID o nome del modello")
    request_id: Optional[str] = Field(default=None, description="ID della richiesta fornito dal provider")


class StreamChunk(BaseModel):
    """Singolo frammento restituito durante una sessione di streaming SSE."""
    content_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    request_id: Optional[str] = None


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
        thinking: bool = True,
        reasoning_effort: str = "low",
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None
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
