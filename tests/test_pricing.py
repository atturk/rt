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
    """Verifica che modelli non censiti come meta-llama/unknown-llama-model-xyz non producano match ambigui."""
    cost = calculate_cost("openrouter", "meta-llama/unknown-llama-model-xyz", input_tokens=1000, output_tokens=500)
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


# ======================================================================
# TASK 55: OPENROUTER DYNAMIC PRICING & CONFIG WIZARD PRICING DETECTION
# ======================================================================

def test_dynamic_openrouter_pricing_fetch_success():
    """Verifica che un modello OpenRouter non in DEFAULT_PRICING recuperi il prezzo via API."""
    import rt.llm.pricing as pr
    from unittest.mock import patch, MagicMock

    # Reset cache
    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "data": [
            {
                "id": "openai/gpt-5.6-luna",
                "pricing": {
                    "prompt": "0.0000015",      # $1.50 per 1M token
                    "completion": "0.0000060"    # $6.00 per 1M token
                }
            }
        ]
    }

    with patch("requests.get", return_value=fake_resp):
        cost = pr.calculate_cost("openrouter", "openai/gpt-5.6-luna", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost is not None
        # 1.50 + 6.00 = 7.50
        assert cost == 7.50


def test_dynamic_openrouter_pricing_fetch_failure_returns_none():
    """Verifica che se la richiesta dinamica a OpenRouter fallisce, ritorna None senza sollevare eccezioni."""
    import rt.llm.pricing as pr
    from unittest.mock import patch

    pr._OPENROUTER_DYNAMIC_CACHE.clear()
    pr._OPENROUTER_DYNAMIC_FETCHED = False

    with patch("requests.get", side_effect=Exception("Connection timeout")):
        cost = pr.calculate_cost("openrouter", "some-brand-new/unknown-model-xyz", input_tokens=1000, output_tokens=1000)
        assert cost is None


def test_configure_pricing_section_with_detected_pricing_auto_save(tmp_path):
    """
    Verifica che quando detected_pricing è fornito e l'utente risponde No alla domanda
    'Vuoi modificarlo?', il pricing venga salvato direttamente in general.yaml.
    """
    import yaml
    from unittest.mock import patch
    from rt.pipeline.configure import _configure_pricing_section

    config_dir = str(tmp_path)
    detected = {
        "input_per_million": 1.25,
        "output_per_million": 5.00
    }

    with patch("questionary.confirm") as mock_confirm:
        # L'utente risponde No a "Vuoi modificarlo?"
        mock_confirm.return_value.ask.return_value = False

        res = _configure_pricing_section(config_dir, "openrouter", "openai/gpt-4o", detected_pricing=detected)

    assert res is not None
    assert res["pricing"]["input_per_million"] == 1.25
    assert res["pricing"]["output_per_million"] == 5.00

    general_path = tmp_path / "general.yaml"
    assert general_path.exists()
    with open(general_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["pricing"]["openrouter"]["openai/gpt-4o"]["input_per_million"] == 1.25
    assert data["pricing"]["openrouter"]["openai/gpt-4o"]["output_per_million"] == 5.00


def test_configure_pricing_section_with_detected_pricing_modified(tmp_path):
    """
    Verifica che quando detected_pricing è fornito e l'utente risponde Sì a 'Vuoi modificarlo?',
    vengano chiesti i valori manuali pre-popolati coi valori rilevati.
    """
    import yaml
    from unittest.mock import patch
    from rt.pipeline.configure import _configure_pricing_section

    config_dir = str(tmp_path)
    detected = {
        "input_per_million": 1.25,
        "output_per_million": 5.00
    }

    with patch("questionary.confirm") as mock_confirm, patch("questionary.text") as mock_text:
        # 1. Vuoi modificarlo? -> True; 2. Costo reasoning separato? -> False
        mock_confirm.return_value.ask.side_effect = [True, False]
        # Inserimento manuale: modifica input a 2.0 e output a 6.0
        mock_text.return_value.ask.side_effect = ["2.0", "6.0"]

        res = _configure_pricing_section(config_dir, "openrouter", "openai/gpt-4o", detected_pricing=detected)

    assert res is not None
    assert res["pricing"]["input_per_million"] == 2.0
    assert res["pricing"]["output_per_million"] == 6.0
