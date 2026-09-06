"""
rt.llm.providers
Registry per i provider LLM supportati.
"""

from typing import Dict, Type
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk
from rt.llm.providers.deepseek import DeepSeekProvider
from rt.llm.providers.openrouter import OpenRouterProvider
from rt.llm.providers.google import GoogleProvider
from rt.llm.providers.mock import MockProvider

_PROVIDERS: Dict[str, Type[BaseLLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "google": GoogleProvider,
    "mock": MockProvider,
}


def get_provider(name: str) -> BaseLLMProvider:
    """Restituisce l'istanza del provider richiesto o solleva ValueError se non supportato."""
    clean_name = name.lower().strip()
    provider_cls = _PROVIDERS.get(clean_name)
    if not provider_cls:
        available = ", ".join(sorted(_PROVIDERS.keys()))
        raise ValueError(
            f"Provider LLM non riconosciuto: '{name}'. Provider disponibili: {available}"
        )
    return provider_cls()

