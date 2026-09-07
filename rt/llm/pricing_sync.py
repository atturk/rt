"""
rt.llm.pricing_sync
Verifica diagnostica dei prezzi configurati/hardcoded contro il catalogo prezzi in tempo
reale di LiteLLM (github.com/BerriAI/litellm), community-mantenuto, copre le API dirette
di molti provider (non solo aggregatori). Usato SOLO su richiesta esplicita dell'utente via
CLI (`rt prices-check` / `rt prices-lookup`) — mai invocato automaticamente durante la
pipeline, che deve restare veloce e funzionare offline.
"""

import json
import os
import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import requests

if TYPE_CHECKING:
    from rt.core.config import RTConfig

LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
CACHE_PATH = os.path.join(os.path.expanduser("~"), ".cache", "rt", "litellm_pricing_cache.json")
CACHE_TTL_SECONDS = 24 * 3600


def get_cache_age_days() -> Optional[float]:
    """Restituisce l'età in giorni della cache locale, o None se non esiste ancora."""
    if not os.path.isfile(CACHE_PATH):
        return None
    age_seconds = time.time() - os.path.getmtime(CACHE_PATH)
    return age_seconds / 86400.0


def load_litellm_catalog(force_refresh: bool = False) -> Dict[str, Any]:
    """Scarica il catalogo prezzi di LiteLLM, con cache locale di 24h per non riscaricare
    ~2.3MB ad ogni invocazione. Solleva l'eccezione originale di 'requests' se la rete
    non è disponibile e non c'è cache valida (nessun fallback silenzioso)."""
    if not force_refresh and os.path.isfile(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_TTL_SECONDS:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    resp = requests.get(LITELLM_PRICING_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp_path = CACHE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, CACHE_PATH)
    return data


def lookup_live_price(model_query: str, provider_hint: Optional[str] = None) -> List[Dict[str, Any]]:
    """Cerca nel catalogo LiteLLM tutte le voci il cui nome contiene model_query (case-insensitive),
    opzionalmente filtrate per provider (campo 'litellm_provider' del catalogo, es. 'deepseek', 'gemini').
    Restituisce una lista di dict con chiave, provider, input_per_million, output_per_million
    (già convertiti da costo-per-token a costo-per-milione)."""
    catalog = load_litellm_catalog()
    query = model_query.lower()
    results = []
    for key, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        if query not in key.lower():
            continue
        if provider_hint:
            p_hint = provider_hint.lower()
            p_entry = entry.get("litellm_provider", "").lower()
            if p_hint == "google" and p_entry in ("gemini", "google", "vertex_ai"):
                pass
            elif p_hint == "gemini" and p_entry in ("gemini", "google", "vertex_ai"):
                pass
            elif p_entry != p_hint:
                continue
        in_cost = entry.get("input_cost_per_token")
        out_cost = entry.get("output_cost_per_token")
        if in_cost is None and out_cost is None:
            continue
        results.append({
            "key": key,
            "provider": entry.get("litellm_provider"),
            "input_per_million": round(in_cost * 1_000_000, 6) if in_cost is not None else None,
            "output_per_million": round(out_cost * 1_000_000, 6) if out_cost is not None else None,
        })
    return results


def collect_configured_routes(cfg: "RTConfig") -> List[Dict[str, Any]]:
    """Enumera tutte le route effettivamente configurate in tutti i job (primary, secondary,
    primary_routes, e ogni voce di fallback), deduplicate per (provider, model)."""
    seen = set()
    routes = []
    for job_name, job_cfg in cfg.jobs.items():
        candidates = []
        if job_cfg.primary:
            candidates.append((job_cfg.primary, ("primary",)))
        if job_cfg.secondary:
            candidates.append((job_cfg.secondary, ("secondary",)))
        if job_cfg.primary_routes:
            for i, r in enumerate(job_cfg.primary_routes):
                candidates.append((r, ("primary_routes", i)))
        for fb_field in ("timeout", "rate_limit", "safety", "auth", "generic"):
            fb_route = getattr(job_cfg.fallback, fb_field, None)
            if fb_route:
                candidates.append((fb_route, ("fallback", fb_field)))
        for route, path in candidates:
            key = (route.provider.lower().strip(), route.model.lower().strip().lstrip("~"))
            if key in seen:
                continue
            seen.add(key)
            routes.append({"job": job_name, "provider": key[0], "model": key[1], "path": path})
    return routes


def check_configured_pricing(cfg: "RTConfig") -> List[Dict[str, Any]]:
    """Per ogni route configurata, confronta il prezzo attualmente USATO dalla pipeline
    (rt.config.yaml 'pricing:' se presente, altrimenti DEFAULT_PRICING hardcoded) contro
    il prezzo live trovato nel catalogo LiteLLM per lo stesso provider/modello, quando
    trovabile con un match esatto o quasi-esatto. NON modifica nulla, solo report."""
    from rt.llm.pricing import calculate_cost

    report = []
    for route in collect_configured_routes(cfg):
        provider, model = route["provider"], route["model"]
        used_input = calculate_cost(provider, model, input_tokens=1_000_000, output_tokens=0, custom_pricing=cfg.pricing)
        used_output = calculate_cost(provider, model, input_tokens=0, output_tokens=1_000_000, custom_pricing=cfg.pricing)

        live_matches = lookup_live_price(model, provider_hint=provider if provider != "openrouter" else None)
        exact_match = next((m for m in live_matches if m["key"].lower().endswith(model.lower())), None)

        entry = {
            "job": route["job"],
            "provider": provider,
            "model": model,
            "path": route.get("path"),
            "used_input_per_million": used_input,
            "used_output_per_million": used_output,
            "live_match": exact_match,
            "other_matches": [m for m in live_matches if m is not exact_match][:5],
        }
        if exact_match and used_input is not None and exact_match.get("input_per_million") is not None:
            diff_pct = abs(exact_match["input_per_million"] - used_input) / max(used_input, 0.0001) * 100
            entry["input_diff_pct"] = round(diff_pct, 1)
            entry["stale"] = diff_pct > 15.0
        report.append(entry)
    return report
