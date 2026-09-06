"""
tests/test_pricing.py
Test di unità per rt.llm.pricing:
- Formalizzazione di openrouter/free come tier a costo 0.0
- Risoluzione non ambigua dei modelli senza collisioni per substring parziali
- Nessun match silenzioso per gemini-3.5-flash verso gemini-3.5-flash-lite
- Gestione deterministica e fallback pulito (None se modello sconosciuto)
"""

import pytest
from rt.llm.pricing import calculate_cost, DEFAULT_PRICING, ModelPricing


def test_openrouter_free_tier():
    """Verifica che openrouter/free sia formalizzato a costo zero esatto (0.0, non None)."""
    cost = calculate_cost("openrouter", "openrouter/free", input_tokens=1000, output_tokens=500)
    assert cost == 0.0
    assert cost is not None

    cost_with_reasoning = calculate_cost("openrouter", "openrouter/free", input_tokens=5000, output_tokens=2000, reasoning_tokens=1000)
    assert cost_with_reasoning == 0.0


def test_gemini_flash_does_not_silently_match_flash_lite():
    """
    Verifica che gemini-3.5-flash NON matchi silenziosamente gemini-3.5-flash-lite:
    restituisce None (costo sconosciuto non stimato) invece di un costo fittizio.
    """
    cost_lite = calculate_cost("google", "gemini-3.5-flash-lite", input_tokens=1000, output_tokens=500)
    assert cost_lite is not None
    assert cost_lite > 0.0

    cost_flash = calculate_cost("google", "gemini-3.5-flash", input_tokens=1000, output_tokens=500)
    assert cost_flash is None, f"gemini-3.5-flash deve restituire None, invece ha restituito {cost_flash}"
    assert cost_flash != cost_lite


def test_unambiguous_matching_llama():
    """Verifica che modelli non censiti come meta-llama/llama-3.3-70b-instruct non producano match ambigui."""
    cost = calculate_cost("openrouter", "meta-llama/llama-3.3-70b-instruct", input_tokens=1000, output_tokens=500)
    assert cost is None


def test_provider_prefix_normalization():
    """Verifica che la normalizzazione del prefisso provider funzioni correttamente."""
    cost_raw = calculate_cost("google", "gemini-2.0-flash", input_tokens=1000, output_tokens=500)
    cost_prefixed = calculate_cost("google", "google/gemini-2.0-flash", input_tokens=1000, output_tokens=500)
    assert cost_raw is not None
    assert cost_raw == cost_prefixed


def test_deterministic_pricing_values():
    """Verifica il calcolo corretto del costo per modelli noti."""
    # deepseek-chat: 0.14/M in, 0.28/M out -> 1M in + 1M out = 0.42
    cost = calculate_cost("deepseek", "deepseek-chat", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.42
