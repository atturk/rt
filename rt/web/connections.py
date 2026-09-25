"""Connessioni LLM e assegnazioni delle sei fasi della web app."""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths
from rt.web.settings import (_atomic_yaml, _read_yaml, credential_names,
                             general_config_path, route_settings, save_credential,
                             save_route)


PHASES = (
    ("outline", "Outline"),
    ("rewrite", "Rewrite"),
    ("review", "Review"),
    ("recall", "Recall"),
    ("image_description", "Descrizione immagine"),
    ("image_unit_judge", "Giudice immagini"),
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


def phase_selection(project_root: Path, job: str) -> tuple[str | None, str | None]:
    _, credential, model, _, _ = route_settings(project_root, job, "primary")
    connection = next((item for item in list_connections(project_root)
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


def assign_phase(project_root: Path, job: str, connection_name: str, model: str) -> str:
    if job not in dict(PHASES):
        raise ValueError("Fase non riconosciuta.")
    connection = find_connection(project_root, connection_name)
    if model not in model_names(project_root, connection_name):
        raise ValueError("Seleziona un modello salvato per questa connessione.")
    credentials = connection["credentials"]
    return save_route(project_root, job, "primary", connection["provider"],
                      credentials[0], model, connection["base_url"],
                      len(credentials) > 1, credentials)
