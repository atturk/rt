"""
rt.services.connections_service
Connessioni LLM e assegnazioni delle sei fasi, condivise da web e API. Spostato
dalla vecchia web Gradio (RT4-E4).
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths
from rt.services.settings_service import (_atomic_yaml, _read_yaml, credential_names,
                             general_config_path, route_settings, save_credential,
                             save_route)


PHASES = (
    ("outline", "Outline"),
    ("rewrite", "Rewrite"),
    ("review", "Review"),
    ("recall", "Recall"),
    ("image_description", "Descrizione immagine"),
    ("enrichment_writer", "Arricchitore"),
    ("enrichment_visualizer", "Visualizzazioni HTML"),
    ("enrichment_image", "Generazione immagini IA"),
    ("study_chat", "Chat dello Studio"),
)
PROVIDERS = (
    ("OpenRouter", "openrouter"),
    ("Google AI Studio", "google"),
    ("DeepSeek", "deepseek"),
    ("OpenAI-compatible", "openai_compatible"),
)


def list_connections(project_root: Path) -> list[dict]:
    """Include le credenziali legacy come connessioni a una chiave, senza migrarle su disco."""
    config_dir = general_config_path(project_root).parent
    general = _read_yaml(config_dir / "general.yaml")
    connections = [dict(item) for item in general.get("connections", [])
                   if isinstance(item, dict) and item.get("name")]
    claimed = {key for item in connections for key in item.get("credentials", [])}
    for credential in general.get("credentials", []):
        if not isinstance(credential, dict) or credential.get("name") in claimed:
            continue
        name = credential.get("name")
        provider = credential.get("provider")
        if not name or not provider:
            continue
        connections.append({"name": name, "provider": provider,
                            "base_url": KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, ""),
                            "credentials": [name], "models": [], "_legacy": True})

    # I modelli già assegnati nei vecchi file YAML devono essere selezionabili.
    for path in find_job_yaml_paths(str(config_dir)).values():
        job = _read_yaml(Path(path))
        routes = [job.get("primary"), job.get("secondary"), *(job.get("primary_routes") or [])]
        for route in routes:
            if not isinstance(route, dict) or not route.get("model"):
                continue
            for connection in connections:
                if route.get("credential") in connection.get("credentials", []):
                    if connection.get("_legacy") and route.get("base_url"):
                        connection["base_url"] = route["base_url"]
                    models = connection.setdefault("models", [])
                    if route["model"] not in models:
                        models.append(route["model"])
    return connections


def connection_names(project_root: Path) -> list[str]:
    return [item["name"] for item in list_connections(project_root)]


def find_connection(project_root: Path, name: str) -> dict:
    connection = next((item for item in list_connections(project_root) if item["name"] == name), None)
    if connection is None:
        raise ValueError("Seleziona una connessione esistente.")
    return connection


def model_names(project_root: Path, name: str) -> list[str]:
    return sorted(set(find_connection(project_root, name).get("models", [])), key=str.casefold)


def phase_selection(project_root: Path, job: str,
                    connections: list[dict] | None = None) -> tuple[str | None, str | None]:
    _, credential, model, _, _ = route_settings(project_root, job, "primary")
    if connections is None:
        connections = list_connections(project_root)
    connection = next((item for item in connections
                       if credential in item.get("credentials", [])), None)
    return (connection["name"] if connection else None, model or None)


def save_connection(project_root: Path, name: str, provider: str,
                    base_url: str, keys: list[str]) -> str:
    name = name.strip()
    if not name or len(name) > 60 or not re.fullmatch(r"[\w .-]+", name, re.UNICODE):
        raise ValueError("Il nome della connessione deve avere al massimo 60 caratteri.")
    if name.casefold() in {item.casefold() for item in connection_names(project_root)}:
        raise ValueError("Esiste già una connessione con questo nome.")
    if provider not in dict(PROVIDERS).values():
        raise ValueError("Provider non supportato.")
    base_url = (base_url or KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, "")).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Inserisci un Base URL HTTP valido.")
    keys = [item.strip() for item in keys if item and item.strip()]
    if not keys:
        raise ValueError("Aggiungi almeno una chiave API.")
    slug = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")[:35]
    if not slug or not slug[0].isalpha():
        slug = f"conn_{slug}"
    credential_ids = [f"web_{slug}_{index}" for index in range(1, len(keys) + 1)]
    if any(identifier in credential_names(project_root) for identifier in credential_ids):
        raise ValueError("Il nome genera una credenziale già esistente. Scegli un altro nome.")
    for identifier, key in zip(credential_ids, keys):
        save_credential(project_root, provider, identifier, key)
    path = general_config_path(project_root)
    data = _read_yaml(path)
    data.setdefault("connections", []).append({"name": name, "provider": provider,
                                                "base_url": base_url,
                                                "credentials": credential_ids,
                                                "models": []})
    _atomic_yaml(path, data)
    clear_catalog_cache(name)
    return name


def add_model(project_root: Path, connection_name: str, model: str) -> str:
    model = model.strip()
    if not model or len(model) > 200 or "\n" in model:
        raise ValueError("Inserisci un identificativo del modello valido.")
    connection = find_connection(project_root, connection_name)
    path = general_config_path(project_root)
    data = _read_yaml(path)
    saved = next((item for item in data.get("connections", [])
                  if item.get("name") == connection_name), None)
    if saved is None:
        saved = {key: connection[key] for key in ("name", "provider", "base_url", "credentials")}
        saved["models"] = []
        data.setdefault("connections", []).append(saved)
    models = saved.setdefault("models", [])
    if model not in models:
        models.append(model)
        _atomic_yaml(path, data)
    return model


BATCH_INELIGIBLE_PHASES = frozenset({"image_description", "enrichment_image"})


def assign_phase(project_root: Path, job: str, connection_name: str, model: str, batch: bool = False) -> str:
    if job not in dict(PHASES):
        raise ValueError("Fase non riconosciuta.")
    if not model or not str(model).strip():
        raise ValueError("Seleziona un modello per questa connessione.")
    clean_model = str(model).strip()
    if clean_model.endswith(":batch"):
        clean_model = clean_model[:-len(":batch")].strip()
        batch = True
    if not clean_model:
        raise ValueError("Seleziona un modello per questa connessione.")
    if batch and job in BATCH_INELIGIBLE_PHASES:
        raise ValueError("Questa fase usa immagini e non supporta la modalità batch.")
    # Il modello scelto viene salvato nella connessione: quelli ricavati dai vecchi file
    # YAML altrimenti sparirebbero dall'elenco appena nessuna fase li usa più, mentre la
    # pagina continua a proporli.
    clean_model = add_model(project_root, connection_name, clean_model)
    connection = find_connection(project_root, connection_name)
    credentials = connection["credentials"]
    return save_route(project_root, job, "primary", connection["provider"],
                      credentials[0], clean_model, connection["base_url"],
                      len(credentials) > 1, credentials, batch=batch)


def clear_phase(project_root: Path, job: str) -> str:
    """Rimuove l'assegnazione personalizzata per una fase che ha un fallback (es. study_chat)."""
    if job != "study_chat":
        raise ValueError("Solo la Chat dello Studio può tornare all'opzione predefinita.")
    config_dir = general_config_path(project_root).parent
    paths = find_job_yaml_paths(str(config_dir))
    if job in paths:
        Path(paths[job]).unlink(missing_ok=True)
    return "Chat dello Studio reimpostata come la Revisione."


_ROLE_LABELS = {"primary": "primaria", "secondary": "secondaria", "timeout": "ripiego timeout",
                "rate_limit": "ripiego rate limit", "safety": "ripiego safety",
                "auth": "ripiego autenticazione", "generic": "ripiego generico"}


class ConnectionInUse(Exception):
    """La connessione ha ancora chiavi usate da route o da JEV: non si elimina."""

    def __init__(self, name: str, usages: list[str]):
        self.name = name
        self.usages = usages
        super().__init__(f"La connessione «{name}» è ancora usata da: {'; '.join(usages)}. "
                         "Assegna un'altra connessione a queste impostazioni prima di eliminarla.")


def connection_usages(project_root: Path, name: str) -> list[str]:
    """Impostazioni che usano una chiave della connessione: route dei job LLM (primaria,
    secondaria, rotazione, ripieghi) e decisioni JEV, se attive. Solo i riferimenti espliciti
    nei YAML: una route senza credenziale usa quella predefinita del provider."""
    connection = find_connection(project_root, name)
    keys = set(connection.get("credentials") or [])
    labels = dict(PHASES)
    usages: list[str] = []
    config_dir = general_config_path(project_root).parent
    for job, path in sorted(find_job_yaml_paths(str(config_dir)).items()):
        data = _read_yaml(Path(path))
        roles: list[tuple[str, object]] = [("primary", data.get("primary")),
                                            ("secondary", data.get("secondary"))]
        roles += [("primary", route) for route in data.get("primary_routes") or []]
        roles += list((data.get("fallback") or {}).items())
        used: list[str] = []
        for role, route in roles:
            if isinstance(route, dict) and route.get("credential") in keys:
                label = _ROLE_LABELS.get(role, role)
                if label not in used:
                    used.append(label)
        if used:
            usages.append(f"{labels.get(job, job)} ({', '.join(used)})")
    from rt.core.config import RTConfig, CLASSIFIER_MODES, classifier_job
    cfg = RTConfig.model_validate(_read_yaml(general_config_path(project_root)))
    if any(classifier_job(cfg, job).mode != "off" and classifier_job(cfg, job).credential in keys for job in CLASSIFIER_MODES):
        usages.append("Classificatore")
    return usages


def delete_connection(project_root: Path, name: str) -> list[str]:
    """Elimina una connessione: la voce in general.yaml con i suoi modelli, le credenziali che
    nessun'altra connessione usa e le loro chiavi (archivio cifrato, .env e ambiente del
    processo). Rifiuta con ConnectionInUse se una route o JEV usa ancora una sua chiave.
    Restituisce le variabili delle chiavi rimosse (mai i valori)."""
    from rt.services import config_service
    connection = find_connection(project_root, name)
    usages = connection_usages(project_root, name)
    if usages:
        raise ConnectionInUse(name, usages)
    others = {key for item in list_connections(project_root) if item["name"] != name
              for key in item.get("credentials") or []}
    removable = {key for key in connection.get("credentials") or [] if key not in others}
    path = general_config_path(project_root)
    data = _read_yaml(path)
    connections = [item for item in data.get("connections") or []
                   if not (isinstance(item, dict) and item.get("name") == name)]
    if connections:
        data["connections"] = connections
    else:
        data.pop("connections", None)
    entries = [item for item in data.get("credentials") or [] if isinstance(item, dict)]
    removed = [item for item in entries if item.get("name") in removable]
    kept = [item for item in entries if item.get("name") not in removable]
    if removed:
        data["credentials"] = [item for item in data.get("credentials") or []
                               if not (isinstance(item, dict) and item.get("name") in removable)]
    _atomic_yaml(path, data)
    kept_vars = {item.get("env_var") for item in kept}
    env_vars = [item["env_var"] for item in removed if item.get("env_var") and item["env_var"] not in kept_vars]
    for env_var in env_vars:
        config_service.unset_secret(env_var, project_root=project_root)
    clear_catalog_cache(name)
    return env_vars


# ---------------------------------------------------------------- catalogo modelli per connessione

CATALOG_CACHE_TTL = 600.0
CATALOG_TIMEOUT_SECONDS = 6.0
# Modelli consigliati di default per provider: oggi non esiste una costante globale per provider,
# quindi resta vuoto finché non verrà definita (mantiene l'etichetta «Consigliato» pronta).
RECOMMENDED_MODELS: dict[str, str] = {}

_CATALOG_LOCK = threading.Lock()
_CATALOG_CACHE: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}


def clear_catalog_cache(name: str | None = None) -> None:
    """Svuota la cache in memoria del catalogo modelli (tutta o per una sola connessione)."""
    with _CATALOG_LOCK:
        if name is None:
            _CATALOG_CACHE.clear()
        else:
            for key in [k for k in _CATALOG_CACHE if k[0] == name]:
                _CATALOG_CACHE.pop(key, None)


def _catalog_models_url(provider: str, base_url: str) -> str:
    raw = (base_url or KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, "")).strip().rstrip("/")
    if provider == "openrouter" and not raw:
        raw = KNOWN_PROVIDER_DEFAULT_BASE_URLS["openrouter"]
    if raw.endswith("/chat/completions"):
        raw = raw[:-len("/chat/completions")].rstrip("/")
    if not raw:
        raise ValueError("Inserisci un Base URL HTTP valido.")
    return f"{raw}/models"


def _parse_per_token_price(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val) or val < 0:
        return None
    return round(val * 1_000_000.0, 6)


def _default_catalog_prices(provider: str, model_id: str) -> tuple[float | None, float | None]:
    from rt.llm.pricing import DEFAULT_PRICING
    prov_map = DEFAULT_PRICING.get((provider or "").lower().strip(), {})
    clean = model_id.lower().strip()
    entry = prov_map.get(clean)
    if entry is None and clean.startswith(f"{provider}/"):
        entry = prov_map.get(clean[len(provider) + 1:])
    if entry is None:
        return None, None
    return float(entry.input_per_million), float(entry.output_per_million)


def _catalog_item(provider: str, model_id: str, name: str | None = None,
                  prompt_price: float | None = None, completion_price: float | None = None) -> dict[str, Any]:
    if prompt_price is None and completion_price is None:
        prompt_price, completion_price = _default_catalog_prices(provider, model_id)
    recommended_id = RECOMMENDED_MODELS.get(provider)
    return {
        "id": model_id,
        "name": (name or model_id).strip() or model_id,
        "prompt_price": prompt_price,
        "completion_price": completion_price,
        "recommended": bool(recommended_id and model_id == recommended_id),
    }


def _parse_catalog_payload(provider: str, payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Risposta del catalogo modelli non valida.")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        prompt_price = _parse_per_token_price(pricing.get("prompt"))
        completion_price = _parse_per_token_price(pricing.get("completion"))
        display_name = row.get("name") or row.get("display_name") or model_id
        items.append(_catalog_item(provider, model_id, str(display_name), prompt_price, completion_price))
    items.sort(key=lambda item: (0 if item["recommended"] else 1))
    return items


def fetch_remote_catalog(provider: str, base_url: str, api_key: str | None) -> list[dict[str, Any]]:
    """Scarica l'elenco dei modelli da GET {base_url}/models con timeout di 6 s."""
    from rt.llm.providers import get_provider
    url = _catalog_models_url(provider, base_url)
    prov_adapter = get_provider(provider)
    if api_key and api_key.strip():
        headers = prov_adapter.get_headers(api_key.strip())
    elif provider == "openai_compatible":
        headers = {"Content-Type": "application/json"}
    else:
        raise ValueError("Nessuna chiave API impostata per questa connessione.")
    resp = requests.get(url, headers=headers, timeout=CATALOG_TIMEOUT_SECONDS)
    if resp.status_code >= 400:
        from rt.services.probes import _provider_error
        detail = _provider_error(resp)[:300]
        raise RuntimeError(f"Errore del servizio (HTTP {resp.status_code}): {detail}")
    return _parse_catalog_payload(provider, resp.json())


def connection_catalog(project_root: Path, name: str) -> tuple[list[dict[str, Any]], bool]:
    """Elenco dei modelli dal provider (cache in memoria 10 min) o fallback ai modelli noti."""
    from rt.core.config import load_config
    from rt.llm.credentials import GLOBAL_CREDENTIALS

    conn = find_connection(project_root, name)
    provider = (conn.get("provider") or "").strip()
    base_url = (conn.get("base_url") or KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, "")).strip().rstrip("/")
    cache_key = (conn["name"], provider, base_url)
    now = time.monotonic()

    with _CATALOG_LOCK:
        cached = _CATALOG_CACHE.get(cache_key)
        if cached and (now - cached[0]) < CATALOG_CACHE_TTL:
            return [dict(item) for item in cached[1]], False

    load_config()
    api_key = next(
        (k for k in (GLOBAL_CREDENTIALS.get_api_key(c) for c in conn.get("credentials") or []) if k),
        None,
    )
    try:
        items = fetch_remote_catalog(provider, base_url, api_key)
        with _CATALOG_LOCK:
            _CATALOG_CACHE[cache_key] = (time.monotonic(), items)
        return [dict(item) for item in items], False
    except Exception:
        known = list(dict.fromkeys(m for m in (conn.get("models") or []) if isinstance(m, str) and m.strip()))
        fallback_items = [_catalog_item(provider, m) for m in known]
        fallback_items.sort(key=lambda item: (0 if item["recommended"] else 1))
        return fallback_items, True


def verify_connection_key(provider: str, base_url: str, api_key: str) -> dict[str, Any]:
    """Verifica una chiave non ancora salvata interrogando GET {base_url}/models."""
    from rt.services.context import _sanitize
    clean_key = (api_key or "").strip()
    if not clean_key:
        return {"ok": False, "models_count": 0, "message": "Inserisci una chiave API."}

    def _clean(msg: str) -> str:
        return _sanitize(msg).replace(clean_key, "[chiave]")

    try:
        items = fetch_remote_catalog(provider, base_url, clean_key)
        return {
            "ok": True,
            "models_count": len(items),
            "message": "Chiave valida · elenco dei modelli scaricato",
        }
    except requests.Timeout:
        return {"ok": False, "models_count": 0, "message": "Nessuna risposta dal servizio entro 6 secondi."}
    except requests.RequestException as exc:
        return {"ok": False, "models_count": 0, "message": _clean(f"Servizio non raggiungibile: {exc}")[:300]}
    except Exception as exc:  # noqa: BLE001 - errore umano al client
        msg = _clean(str(exc))
        if "401" in msg or "403" in msg:
            return {"ok": False, "models_count": 0, "message": "Chiave API non valida o non autorizzata."}
        return {"ok": False, "models_count": 0, "message": msg[:300] or "Verifica non riuscita."}
