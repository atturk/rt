"""
rt.services.connections_service
Connessioni LLM e assegnazioni delle sei fasi, condivise da web e API. Spostato da
rt/web/connections.py (RT4-E4).
"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

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
    ("enrichment_image", "Generazione infografiche"),
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
    if not model or not str(model).strip():
        raise ValueError("Seleziona un modello per questa connessione.")
    # Il modello scelto viene salvato nella connessione: quelli ricavati dai vecchi file
    # YAML altrimenti sparirebbero dall'elenco appena nessuna fase li usa più, mentre la
    # pagina continua a proporli.
    model = add_model(project_root, connection_name, str(model))
    connection = find_connection(project_root, connection_name)
    credentials = connection["credentials"]
    return save_route(project_root, job, "primary", connection["provider"],
                      credentials[0], model, connection["base_url"],
                      len(credentials) > 1, credentials)


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
    jev = _read_yaml(general_config_path(project_root)).get("jev") or {}
    jev_active = bool(jev.get("enabled")) or (
        jev.get("relevance_mode", "shadow") != "disabled" and bool(str(jev.get("relevance_model") or "").strip()))
    if jev_active and jev.get("credential", "openrouter") in keys:
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
    return env_vars
