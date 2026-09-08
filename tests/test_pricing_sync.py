"""
tests/test_pricing_sync.py
Test di unità e integrazione per il modulo rt.llm.pricing_sync:
- Cache locale e TTL di 24h
- Lookup live nel catalogo LiteLLM
- Raccolta e deduplicazione delle route configurate
- Confronto prezzi usati vs live con soglia staleness (15%)
- Comandi CLI prices-check e prices-lookup
- Avviso di staleness all'avvio di cmd_run (nessuna chiamata di rete)
TUTTE LE CHIAMATE A requests.get SONO MOCKATE.
"""

import os
import time
import json
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from rt.core.config import RTConfig, RouteConfig, JobRoutingConfig, JobFallbackConfig
from rt.llm.pricing import ModelPricing
from rt.llm.pricing_sync import (
    load_litellm_catalog,
    lookup_live_price,
    collect_configured_routes,
    check_configured_pricing,
    get_cache_age_days,
)
from rt.cli import cmd_prices_check, cmd_prices_lookup, cmd_run


FAKE_LITELLM_CATALOG = {
    "gemini/gemini-3.5-flash-lite": {
        "litellm_provider": "gemini",
        "input_cost_per_token": 0.00000030,  # $0.30 / M
        "output_cost_per_token": 0.00000250,  # $2.50 / M
    },
    "deepseek/deepseek-v4-flash": {
        "litellm_provider": "deepseek",
        "input_cost_per_token": 0.00000014,  # $0.14 / M
        "output_cost_per_token": 0.00000028,  # $0.28 / M
    },
    "openai/gpt-5.6-luna": {
        "litellm_provider": "openai",
        "input_cost_per_token": 0.00000200,  # $2.00 / M
        "output_cost_per_token": 0.00000800,  # $8.00 / M
    },
    "openrouter/tencent/hy3": {
        "litellm_provider": "openrouter",
        "input_cost_per_token": 0.00000050,  # $0.50 / M
        "output_cost_per_token": 0.00000100,  # $1.00 / M
    }
}


def test_load_litellm_catalog_downloads_and_caches(tmp_path, monkeypatch):
    """1. load_litellm_catalog scarica e salva in cache locale."""
    cache_file = str(tmp_path / "cache.json")
    monkeypatch.setattr("rt.llm.pricing_sync.CACHE_PATH", cache_file)

    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_LITELLM_CATALOG
    mock_resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = load_litellm_catalog()
        assert mock_get.call_count == 1
        assert "gemini/gemini-3.5-flash-lite" in data
        assert os.path.isfile(cache_file)

        # Verifica contenuto salvato
        with open(cache_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved == FAKE_LITELLM_CATALOG


def test_load_litellm_catalog_uses_cache_within_ttl(tmp_path, monkeypatch):
    """2. Seconda chiamata entro TTL usa la cache e non chiama requests.get."""
    cache_file = str(tmp_path / "cache.json")
    monkeypatch.setattr("rt.llm.pricing_sync.CACHE_PATH", cache_file)

    # Scrivi una cache recente
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(FAKE_LITELLM_CATALOG, f)

    with patch("requests.get") as mock_get:
        data = load_litellm_catalog()
        assert mock_get.call_count == 0
        assert "deepseek/deepseek-v4-flash" in data


def test_lookup_live_price_substring_and_provider_filter(tmp_path, monkeypatch):
    """3. lookup_live_price con catalogo mock: ricerca substring e filtro provider."""
    monkeypatch.setattr("rt.llm.pricing_sync.load_litellm_catalog", lambda force_refresh=False: FAKE_LITELLM_CATALOG)

    # Ricerca substring
    results = lookup_live_price("flash")
    keys = [r["key"] for r in results]
    assert "gemini/gemini-3.5-flash-lite" in keys
    assert "deepseek/deepseek-v4-flash" in keys
    assert len(results) == 2

    # Verifica conversione a costo per milione
    gemini_entry = next(r for r in results if r["key"] == "gemini/gemini-3.5-flash-lite")
    assert gemini_entry["input_per_million"] == 0.3
    assert gemini_entry["output_per_million"] == 2.5

    # Filtro provider
    filtered = lookup_live_price("flash", provider_hint="deepseek")
    assert len(filtered) == 1
    assert filtered[0]["key"] == "deepseek/deepseek-v4-flash"

    # Ricerca senza risultati
    none_res = lookup_live_price("nonexistent-model")
    assert none_res == []


def test_collect_configured_routes_deduplication():
    """4. collect_configured_routes enumera e deduplica tutte le route da primary/secondary/fallback."""
    cfg = RTConfig(
        jobs={
            "job1": JobRoutingConfig(
                primary=RouteConfig(provider="google", model="gemini-3.5-flash-lite"),
                secondary=RouteConfig(provider="google", model="gemini-3.5-flash-lite"),
                fallback=JobFallbackConfig(
                    timeout=RouteConfig(provider="openrouter", model="deepseek/deepseek-v4-flash"),
                    rate_limit=RouteConfig(provider="google", model="gemini-3.5-flash-lite"),
                )
            ),
            "job2": JobRoutingConfig(
                primary=RouteConfig(provider="deepseek", model="deepseek-v4-flash"),
            )
        }
    )
    routes = collect_configured_routes(cfg)
    assert len(routes) == 3
    keys = [(r["provider"], r["model"]) for r in routes]
    assert ("google", "gemini-3.5-flash-lite") in keys
    assert ("openrouter", "deepseek/deepseek-v4-flash") in keys
    assert ("deepseek", "deepseek-v4-flash") in keys


def test_collect_configured_routes_skips_unconfigured_routes():
    """Verifica che job con route non configurate (provider=None o model=None) vengano saltati senza eccezioni."""
    cfg = RTConfig(
        jobs={
            "job_empty": JobRoutingConfig(
                primary=RouteConfig(provider=None, model=None),
            ),
            "job_valid": JobRoutingConfig(
                primary=RouteConfig(provider="google", model="gemini-3.5-flash-lite"),
            ),
        }
    )
    routes = collect_configured_routes(cfg)
    assert len(routes) == 1
    assert routes[0]["provider"] == "google"
    assert routes[0]["model"] == "gemini-3.5-flash-lite"

    report = check_configured_pricing(cfg)
    assert len(report) == 1
    assert report[0]["job"] == "job_valid"


def test_check_configured_pricing_diff_and_stale(monkeypatch):
    """5. check_configured_pricing calcola input_diff_pct e flag stale (soglia 15%)."""
    monkeypatch.setattr("rt.llm.pricing_sync.load_litellm_catalog", lambda force_refresh=False: FAKE_LITELLM_CATALOG)

    # In DEFAULT_PRICING:
    # google/gemini-3.5-flash-lite è 0.075 / 0.30
    # Nel catalogo mock: 0.30 / 2.50 -> diff_pct = |0.30 - 0.075| / 0.075 * 100 = 300% (>15% -> stale)
    # deepseek/deepseek-v4-flash è 0.14 / 0.28
    # Nel catalogo mock: 0.14 / 0.28 -> diff_pct = 0% (non stale)
    cfg = RTConfig(
        jobs={
            "rewrite": JobRoutingConfig(
                primary=RouteConfig(provider="google", model="gemini-3.5-flash-lite")
            ),
            "outline": JobRoutingConfig(
                primary=RouteConfig(provider="deepseek", model="deepseek-v4-flash")
            )
        }
    )
    report = check_configured_pricing(cfg)
    assert len(report) == 2

    gemini_report = next(r for r in report if r["model"] == "gemini-3.5-flash-lite")
    assert gemini_report["used_input_per_million"] == 0.075
    assert gemini_report["live_match"]["input_per_million"] == 0.3
    assert gemini_report["input_diff_pct"] == 300.0
    assert gemini_report["stale"] is True

    deepseek_report = next(r for r in report if r["model"] == "deepseek-v4-flash")
    assert deepseek_report["used_input_per_million"] == 0.14
    assert deepseek_report["live_match"]["input_per_million"] == 0.14
    assert deepseek_report["input_diff_pct"] == 0.0
    assert deepseek_report.get("stale") is False or deepseek_report.get("stale") is None


def test_check_configured_pricing_uses_per_route_pricing_override(monkeypatch):
    """check_configured_pricing deve usare il pricing per-route (route.pricing), non solo il
    listino globale cfg.pricing o DEFAULT_PRICING: se l'utente ha impostato esplicitamente un
    prezzo custom sulla singola route (es. 0.0/0.0 per un modello che vuole tenere gratuito),
    'in uso oggi' deve riflettere quel valore, non quello hardcoded per lo stesso modello."""
    monkeypatch.setattr("rt.llm.pricing_sync.load_litellm_catalog", lambda force_refresh=False: FAKE_LITELLM_CATALOG)

    cfg = RTConfig(
        jobs={
            "rewrite": JobRoutingConfig(
                primary=RouteConfig(
                    provider="google",
                    model="gemini-3.5-flash-lite",
                    pricing=ModelPricing(input_per_million=0.0, output_per_million=0.0),
                )
            ),
        }
    )
    report = check_configured_pricing(cfg)
    assert len(report) == 1
    assert report[0]["used_input_per_million"] == 0.0
    assert report[0]["used_output_per_million"] == 0.0
    # Il live_match resta comunque disponibile per un'eventuale applicazione interattiva.
    assert report[0]["live_match"]["input_per_million"] == 0.3


def test_cmd_prices_lookup_and_check_output(capsys, monkeypatch):
    """6. Output testuale di cmd_prices_lookup e cmd_prices_check."""
    monkeypatch.setattr("rt.llm.pricing_sync.load_litellm_catalog", lambda force_refresh=False: FAKE_LITELLM_CATALOG)

    # Test lookup
    args_lookup = SimpleNamespace(query="gemini-3.5-flash-lite", provider=None)
    cmd_prices_lookup(args_lookup)
    out_lookup = capsys.readouterr().out
    assert "gemini/gemini-3.5-flash-lite" in out_lookup
    assert "in=$0.3/M" in out_lookup
    assert "out=$2.5/M" in out_lookup

    # Test lookup con query vuota/non trovata
    args_none = SimpleNamespace(query="non_existent", provider=None)
    cmd_prices_lookup(args_none)
    out_none = capsys.readouterr().out
    assert "Nessun modello trovato" in out_none

    # Test check
    fake_cfg = RTConfig(
        jobs={
            "rewrite": JobRoutingConfig(
                primary=RouteConfig(provider="google", model="gemini-3.5-flash-lite")
            )
        }
    )
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: fake_cfg)
    cmd_prices_check(SimpleNamespace())
    out_check = capsys.readouterr().out
    assert "VERIFICA PREZZI CONFIGURATI vs CATALOGO LIVE" in out_check
    assert "[rewrite] google/gemini-3.5-flash-lite" in out_check
    assert "⚠ DA VERIFICARE" in out_check
    assert "Differenza input: 300.0%" in out_check


def test_get_cache_age_days(tmp_path, monkeypatch):
    """8. get_cache_age_days restituisce None se il file non esiste, o i giorni se esiste."""
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("rt.llm.pricing_sync.CACHE_PATH", str(cache_file))

    # File inesistente
    assert get_cache_age_days() is None

    # File creato con mtime modificato di 2 giorni fa
    cache_file.write_text("{}", encoding="utf-8")
    two_days_ago = time.time() - (2 * 86400)
    os.utime(str(cache_file), (two_days_ago, two_days_ago))

    age = get_cache_age_days()
    assert age is not None
    assert 1.95 <= age <= 2.05


def test_cmd_run_staleness_warning(tmp_path, capsys, monkeypatch):
    """9. cmd_run stampa l'avviso di staleness se la cache è vecchia/assente, e non lo stampa se recente o disattivato."""
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("rt.llm.pricing_sync.CACHE_PATH", str(cache_file))

    # Mock delle fasi di run per fermare subito l'esecuzione
    monkeypatch.setattr("rt.pipeline.setup.is_audio_file", lambda x: False)
    monkeypatch.setattr("rt.cli.run_prepare", lambda *a, **kw: {"skipped": True, "segment_count": 0, "duration_seconds": 0})
    monkeypatch.setattr("rt.cli.run_outline", lambda *a, **kw: {"skipped": True, "validation_report": {"units_count": 0, "coverage_percentage": 100}})
    monkeypatch.setattr("rt.cli.confirm_or_revise_outline", lambda *a, **kw: None)
    monkeypatch.setattr("rt.cli.run_rewrite", lambda *a, **kw: {"skipped": True, "total_units": 0, "reused_units": 0, "regenerated_units": 0})
    monkeypatch.setattr("rt.cli.run_review_asr", lambda *a, **kw: {"skipped": True, "total_issues": 0})
    monkeypatch.setattr("rt.cli.run_review_science", lambda *a, **kw: {"skipped": True, "total_science_issues": 0})
    monkeypatch.setattr("rt.cli.run_build", lambda *a, **kw: {"skipped": True, "generated_files": []})
    monkeypatch.setattr("rt.cli.load_asr_issues", lambda *a, **kw: [])
    monkeypatch.setattr("rt.cli.load_science_issues", lambda *a, **kw: [])
    monkeypatch.setattr("rt.core.state.get_current_state", lambda *a, **kw: None)
    monkeypatch.setattr("rt.cli.load_ledger", lambda *a, **kw: SimpleNamespace(decisions=[]))

    args = SimpleNamespace(
        input=["tests/fixtures/demo_lecture"],
        force=False,
        mock=True,
        auto_accept=True,
        auto_accept_asr=None,
        auto_accept_science=None,
        rename=False
    )

    # Caso A: cache assente -> stampa avviso
    cfg_default = RTConfig(pricing_staleness_warning_days=7)
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: cfg_default)
    cmd_run(args)
    out_a = capsys.readouterr().out
    assert "I prezzi configurati non sono stati verificati con 'rt prices-check'" in out_a

    # Caso B: cache recente (creata ora) -> NON stampa avviso
    cache_file.write_text("{}", encoding="utf-8")
    cmd_run(args)
    out_b = capsys.readouterr().out
    assert "I prezzi configurati non sono stati verificati con 'rt prices-check'" not in out_b

    # Caso C: pricing_staleness_warning_days = 0 -> avviso disattivato
    cfg_disabled = RTConfig(pricing_staleness_warning_days=0)
    monkeypatch.setattr("rt.core.config.load_config", lambda *a, **kw: cfg_disabled)
    # Rendi la cache vecchia di 10 giorni
    old_time = time.time() - (10 * 86400)
    os.utime(str(cache_file), (old_time, old_time))
    cmd_run(args)
    out_c = capsys.readouterr().out
    assert "I prezzi configurati non sono stati verificati con 'rt prices-check'" not in out_c
