"""
rt.llm.capabilities
Metadati e capacità formali dei provider supportati dal layer LLM di RT 2.0.
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    """Capacità formali supportate dall'adapter di un provider."""
    streaming: bool = Field(default=True, description="Supporto a streaming SSE")
    structured_output: bool = Field(default=True, description="Supporto a output JSON strutturato conforme a schema")
    reasoning: bool = Field(default=False, description="Supporto a modalità reasoning / thinking CoT")
    max_output_tokens: bool = Field(default=True, description="Supporto al parametro max_tokens/max_completion_tokens")
    supports_temperature: bool = Field(default=True, description="Supporto al controllo della temperatura")
    vision: bool = Field(default=True, description="Supporto a input di immagini")


_DEFAULT_CAPABILITIES: Dict[str, ProviderCapabilities] = {
    "deepseek": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=True,
        max_output_tokens=True,
        supports_temperature=True,  # In standard chat mode temperature is supported; disabled in thinking mode
        vision=False,
    ),
    "openrouter": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=True,
        max_output_tokens=True,
        supports_temperature=True,
        vision=True,
    ),
    "google": ProviderCapabilities(
        streaming=True,
        structured_output=True,
        reasoning=False,
        max_output_tokens=True,
        supports_temperature=True,
        vision=True,
    ),
}


def get_capabilities(provider_name: str, thinking_mode: bool = False) -> ProviderCapabilities:
    """
    Restituisce le capacità formali del provider, tenendo conto dell'eventuale modalità operativa.
    Per DeepSeek, supports_temperature è disabilitato in modalità reasoning (thinking_mode=True).
    """
    clean = provider_name.lower().strip()
    caps = _DEFAULT_CAPABILITIES.get(clean, ProviderCapabilities()).model_copy()
    if clean == "deepseek" and thinking_mode:
        caps.supports_temperature = False
    return caps


_NON_VISION_MODEL_PREFIXES = (
    "deepseek/",
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v",
    "deepseek-r",
    "qwen/qwen-2.5-",
    "qwen/qwen3-",
    "meta-llama/llama-3.1-",
    "meta-llama/llama-3.3-",
)


def supports_vision(provider_name: Optional[str], model_name: Optional[str] = None) -> bool:
    """Restituisce False se il provider o il modello noto non accetta immagini in ingresso."""
    clean_provider = (provider_name or "").lower().strip()
    if clean_provider and not get_capabilities(clean_provider).vision:
        return False
    clean_model = (model_name or "").lower().strip()
    if not clean_model:
        return True
    if "vision" in clean_model or "-vl" in clean_model:
        return True
    return not clean_model.startswith(_NON_VISION_MODEL_PREFIXES)
