"""
rt.llm.pricing
Configurazione e calcolo stime di costo per le chiamate LLM.
Disaccoppiato dalla logica di business e configurabile per provider e modello.

I valori sottostanti sono stime di riferimento e possono invecchiare. Usa 'rt prices-check' per confrontarli con il catalogo live.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    input_per_million: float = Field(description="Costo in USD per 1M token di input")
    output_per_million: float = Field(description="Costo in USD per 1M token di output")
    reasoning_per_million: Optional[float] = Field(
        default=None,
        description="Costo in USD per 1M token di reasoning (se diverso da output standard)"
    )


# Pricing di riferimento (stime basate sui listini ufficiali pubblici)
DEFAULT_PRICING: Dict[str, Dict[str, ModelPricing]] = {
    "deepseek": {
        "deepseek-v4-flash": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek-v4-flash-latest": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek-chat": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek-reasoner": ModelPricing(input_per_million=0.55, output_per_million=2.19),
        "deepseek-v4-pro": ModelPricing(input_per_million=0.55, output_per_million=2.19),
    },
    "openrouter": {
        "openrouter/free": ModelPricing(input_per_million=0.0, output_per_million=0.0),
        "~deepseek/deepseek-v4-flash-latest": ModelPricing(input_per_million=0.05, output_per_million=0.10),
        "deepseek/deepseek-v4-flash-latest": ModelPricing(input_per_million=0.05, output_per_million=0.10),
        "deepseek/deepseek-v4-flash-0731": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek/deepseek-v4-flash": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek/deepseek-chat": ModelPricing(input_per_million=0.14, output_per_million=0.28),
        "deepseek/deepseek-r1": ModelPricing(input_per_million=0.55, output_per_million=2.19),
        "deepseek/deepseek-v4-pro": ModelPricing(input_per_million=0.55, output_per_million=2.19),
        "anthropic/claude-3.5-sonnet": ModelPricing(input_per_million=3.00, output_per_million=15.00),
        "openai/gpt-4o-mini": ModelPricing(input_per_million=0.15, output_per_million=0.60),
    },
    "google": {
        "gemini-flash-latest": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-flash-lite-latest": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-pro-latest": ModelPricing(input_per_million=1.25, output_per_million=5.00),
        "gemini-3.6-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-3.5-flash-lite": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-2.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-2.0-flash": ModelPricing(input_per_million=0.10, output_per_million=0.40),
        "gemini-2.0-flash-lite": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-2.5-pro": ModelPricing(input_per_million=1.25, output_per_million=5.00),
        "gemini-1.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
        "gemini-1.5-pro": ModelPricing(input_per_million=1.25, output_per_million=5.00),
    }
}


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    reasoning_tokens: Optional[int] = 0,
    custom_pricing: Optional[Dict[str, Any]] = None
) -> Optional[float]:
    """
    Calcola la stima di costo per una singola richiesta LLM.
    Restituisce None se i token non sono disponibili o se il modello non ha pricing noto.
    """
    if input_tokens is None and output_tokens is None:
        return None

    in_tok = input_tokens or 0
    out_tok = output_tokens or 0
    reas_tok = reasoning_tokens or 0

    prov_clean = provider.lower().strip()
    mod_clean = model.lower().strip().lstrip("~")

    pricing: Optional[ModelPricing] = None

    # 1. Verifica in custom_pricing (se fornito da rt.config.yaml)
    if custom_pricing and prov_clean in custom_pricing:
        p_dict = custom_pricing[prov_clean]
        if mod_clean in p_dict:
            pricing = ModelPricing.model_validate(p_dict[mod_clean])

    # 2. Verifica in DEFAULT_PRICING
    if pricing is None and prov_clean in DEFAULT_PRICING:
        prov_models = DEFAULT_PRICING[prov_clean]
        # (a) Match esatto sulla chiave
        if mod_clean in prov_models:
            pricing = prov_models[mod_clean]
        else:
            # (b) Match esatto dopo normalizzazione prefisso provider (es. "google/gemini-2.0-flash")
            prefix = f"{prov_clean}/"
            norm_mod = mod_clean[len(prefix):] if mod_clean.startswith(prefix) else mod_clean
            if norm_mod in prov_models:
                pricing = prov_models[norm_mod]
            else:
                # (c) Match deterministico per segmenti interi separati da '-' o '/'
                query_tokens = [s for s in mod_clean.replace("/", "-").split("-") if s]
                for k, v in sorted(prov_models.items(), key=lambda item: len(item[0]), reverse=True):
                    k_tokens = [s for s in k.replace("/", "-").split("-") if s]
                    if k_tokens == query_tokens:
                        pricing = v
                        break

    # Se non trovato ma il provider è deepseek/openrouter con modello deepseek generico, usa fallback conservativo
    if pricing is None:
        if "deepseek" in mod_clean:
            pricing = ModelPricing(input_per_million=0.14, output_per_million=0.28)
        else:
            return None

    cost_in = (in_tok / 1_000_000.0) * pricing.input_per_million
    cost_out = (out_tok / 1_000_000.0) * pricing.output_per_million

    # Se c'è un pricing specifico per reasoning_tokens, usalo
    reason_rate = pricing.reasoning_per_million if pricing.reasoning_per_million is not None else pricing.output_per_million
    cost_reason = (reas_tok / 1_000_000.0) * reason_rate

    total_cost = cost_in + cost_out + cost_reason
    return round(total_cost, 6)
