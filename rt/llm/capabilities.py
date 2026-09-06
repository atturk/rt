"""
rt.llm.capabilities
Metadati e capacità formali dei provider supportati dal layer LLM di RT 2.0.
"""

from typing import Dict
from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    """Capacità formali supportate dall'adapter di un provider."""
    streaming: bool = Field(default=True, description="Supporto a streaming SSE")
    structured_output: bool = Field(default=True, description="Supporto a output JSON strutturato conforme a schema")
    reasoning: bool = Field(default=False, description="Supporto a modalità reasoning / thinking CoT")
    max_output_tokens: bool = Field(default=True, description="Supporto al parametro max_tokens/max_completion_tokens")
    supports_temperature: bool = Field(default=True, description="Supporto al controllo della temperatura")


_DEFAULT_CAPABILITIES: Dict[str, ProviderCapabilities] = {
    "deepseek": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=True,
        max_output_tokens=True,
        supports_temperature=False  # DeepSeek official: in thinking mode temperature is ignored or prohibited
    ),
    "openrouter": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=True,
        max_output_tokens=True,
        supports_temperature=True
    ),
    "google": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=False,
        max_output_tokens=True,
        supports_temperature=True
    ),
    "mock": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=True,
        max_output_tokens=True,
        supports_temperature=True
    ),
}


def get_capabilities(provider_name: str) -> ProviderCapabilities:
    clean = provider_name.lower().strip()
    return _DEFAULT_CAPABILITIES.get(clean, ProviderCapabilities())
