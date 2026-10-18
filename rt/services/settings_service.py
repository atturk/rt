"""
rt.services.settings_service
Impostazioni modificabili da web e API (credenziali, route dei job LLM, Telegram, motore di
trascrizione, cartella lezioni), salvate senza riscrivere il resto del YAML. Spostato dalla
vecchia web Gradio (RT4-E4).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict
from urllib.parse import urlparse


from rt.core.config import JobRoutingConfig, KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths, load_config, classifier_job
from rt.llm.credentials import CredentialRef, GLOBAL_CREDENTIALS
from rt.services import config_service


def general_config_path(project_root: Path) -> Path:
    """Usa la stessa precedenza di load_config(): config/ nella cwd, poi nel progetto."""
    return config_service.general_config_path(project_root)


def _read_yaml(path: Path) -> dict[str, Any]:
    return config_service.read_yaml(path)


def _atomic_yaml(path: Path, data: dict[str, Any]) -> None:
    config_service.write_yaml_atomic(path, data)


def _env_path(project_root: Path) -> Path:
    return config_service.env_path(project_root)


def _save_secret(project_root: Path, env_var: str, secret: str) -> None:
    config_service.set_secret(env_var, secret, path=_env_path(project_root))


def _validate_secret(secret: str) -> None:
    config_service.validate_secret(secret)


def credential_names(project_root: Path, provider: str | None = None) -> list[str]:
    entries = _read_yaml(general_config_path(project_root)).get("credentials") or []
    return [item["name"] for item in entries if isinstance(item, dict) and item.get("name")
            and (provider is None or item.get("provider") == provider)]


def save_credential(project_root: Path, provider: str, name: str, api_key: str) -> str:
    if provider not in {"openrouter", "deepseek", "google", "openai_compatible"}:
        raise ValueError("Provider non supportato.")
    name = name.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", name):
        raise ValueError("Usa un nome breve con lettere, numeri e _.")
    path = general_config_path(project_root)
    data = _read_yaml(path)
    entries = data.setdefault("credentials", [])
    if not isinstance(entries, list):
        raise ValueError("La sezione credentials non è valida.")
    existing = next((item for item in entries if isinstance(item, dict) and item.get("name") == name), None)
    if existing and existing.get("provider") != provider:
        raise ValueError("Questo nome appartiene a un altro provider.")
    env_var = (existing.get("env_var") if existing else None) or f"RT_{name.upper()}_API_KEY"
    _validate_secret(api_key.strip())
    _save_secret(project_root, env_var, api_key.strip())
    if not existing:
        entries.append({"name": name, "provider": provider, "env_var": env_var})
        _atomic_yaml(path, data)
    GLOBAL_CREDENTIALS.register(CredentialRef(name=name, provider=provider, env_var=env_var))
    return name


# Ruoli modificabili dalla web. I ripieghi per tipo di errore (fallback.timeout, ...) restano
# supportati dal motore per chi li scrive a mano nei YAML, ma la web non li espone più.
ROUTE_ROLES = ("primary", "secondary")


def _legacy_recall_path(paths: dict[str, str]) -> Path | None:
    names = ("recall_quiz", "recall_mirata", "recall_vasta",
             "recall_eval_mirata", "recall_eval_vasta")
    candidates = [Path(paths[name]) for name in names if name in paths]
    for path in candidates:
        data = _read_yaml(path)
        route = (data.get("primary_routes") or [data.get("primary") or {}])[0]
        if isinstance(route, dict) and route.get("model"):
            return path
    return candidates[0] if candidates else None


def route_settings(project_root: Path, job: str, role: str) -> tuple[str, str, str, str, bool]:
    paths = find_job_yaml_paths(str(general_config_path(project_root).parent))
    if job == "recall" and job not in paths:
        previous = _legacy_recall_path(paths)
        if previous:
            paths[job] = str(previous)
    data = _read_yaml(Path(paths[job])) if job in paths else {}
    if role in {"primary", "secondary"}:
        route = data.get(role) or {}
        if role == "primary" and data.get("primary_routes"):
            route = data["primary_routes"][0]
    else:
        route = (data.get("fallback") or {}).get(role) or {}
    provider = route.get("provider") or "openrouter"
    return (provider, route.get("credential") or "", route.get("model") or "",
            route.get("base_url") or KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, ""),
            bool(role == "primary" and data.get("round_robin")))


def route_round_robin_keys(project_root: Path, job: str) -> list[str]:
    paths = find_job_yaml_paths(str(general_config_path(project_root).parent))
    data = _read_yaml(Path(paths[job])) if job in paths else {}
    return [route["credential"] for route in (data.get("primary_routes") or [])
            if isinstance(route, dict) and route.get("credential")]


def save_route(project_root: Path, job: str, role: str, provider: str,
               credential: str, model: str, base_url: str, round_robin: bool,
               round_robin_credentials: list[str] | None = None) -> str:
    if role not in ROUTE_ROLES or provider not in (*KNOWN_PROVIDER_DEFAULT_BASE_URLS, "openai_compatible"):
        raise ValueError("Ruolo o provider non riconosciuto.")
    paths = find_job_yaml_paths(str(general_config_path(project_root).parent))
    if job in {"enrichment_writer", "enrichment_visualizer", "enrichment_image"} and job not in paths:
        target = general_config_path(project_root).parent / "rt" / f"{job}.yaml"
        _atomic_yaml(target, {"primary": {}})
        paths[job] = str(target)
    if job == "recall" and job not in paths:
        target = general_config_path(project_root).parent / "telegram" / "recall.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = _legacy_recall_path(paths)
        _atomic_yaml(target, _read_yaml(previous) if previous else {"primary": {}})
        paths["recall"] = str(target)
    if job not in paths:
        raise ValueError("Job LLM non trovato.")
    model = model.strip()
    if not model:
        raise ValueError("Inserisci l'identificativo del modello.")
    names = credential_names(project_root, provider)
    selected_names = round_robin_credentials if round_robin_credentials is not None else names
    if role == "primary" and round_robin:
        if len(selected_names) < 2 or len(set(selected_names)) != len(selected_names):
            raise ValueError("Per la rotazione servono almeno due chiavi dello stesso provider.")
        if any(name not in names for name in selected_names):
            raise ValueError("La rotazione contiene una chiave non associata al provider scelto.")
        credential = selected_names[0]
    elif credential not in names:
        raise ValueError("Seleziona una chiave del provider scelto.")
    base_url = base_url.strip().rstrip("/")
    if provider == "openai_compatible" and not base_url:
        raise ValueError("Il provider OpenAI-compatible richiede un Base URL.")
    path = Path(paths[job])
    data = _read_yaml(path)
    previous = ((data.get("fallback") or {}).get(role) if role not in {"primary", "secondary"}
                else (data.get(role) or {}))
    route = {**previous, "provider": provider, "credential": credential, "model": model}
    route.pop("base_url", None)
    if previous.get("provider") != provider:
        route.pop("provider_routing", None)
    if base_url and base_url != KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider):
        route["base_url"] = base_url
    if role == "primary":
        if round_robin:
            data["primary_routes"] = [{**route, "credential": name} for name in selected_names]
            data["round_robin"] = True
            data["primary"] = data["primary_routes"][0]
        else:
            data["primary"] = route
            data.pop("primary_routes", None)
            data["round_robin"] = False
    elif role == "secondary":
        data["secondary"] = route
    else:
        data.setdefault("fallback", {})[role] = route
    load_config()  # registra le credenziali dichiarate prima della validazione
    JobRoutingConfig.model_validate(data)
    _atomic_yaml(path, data)
    return f"Modello {role} salvato per {job}."


# Chiavi delle vecchie versioni (bot nei gruppi con i topic): si tolgono al primo salvataggio.
_LEGACY_TELEGRAM_KEYS = ("topics", "topic_names", "misc_topic_id", "default_channel", "wait_timeout_seconds")


def save_telegram(project_root: Path, token: str, chat_id: str) -> str:
    """Token del bot (segreto) e ID della chat personale in cui arrivano le notifiche."""
    if token.strip():
        _validate_secret(token.strip())
    if chat_id.strip():
        _validate_secret(chat_id.strip())
        if not re.fullmatch(r"-?\d+", chat_id.strip()):
            raise ValueError("Chat ID non valido.")
    path = general_config_path(project_root)
    data = _read_yaml(path)
    telegram = data.get("telegram")
    if isinstance(telegram, dict) and any(k in telegram for k in _LEGACY_TELEGRAM_KEYS):
        for key in _LEGACY_TELEGRAM_KEYS:
            telegram.pop(key, None)
        _atomic_yaml(path, data)
    if token.strip():
        _save_secret(project_root, "RT_TELEGRAM_BOT_TOKEN", token.strip())
    if chat_id.strip():
        # Il chat id non è un segreto: resta in .env anche con l'archivio cifrato.
        config_service.set_env_var(_env_path(project_root), "RT_TELEGRAM_CHAT_ID", chat_id.strip(), quote=True)
    return "Impostazioni Telegram salvate."


def set_telegram_enabled(project_root: Path, enabled: bool) -> str:
    """Accende o spegne le notifiche Telegram (telegram.enabled nella configurazione generale)."""
    path = general_config_path(project_root)
    data = _read_yaml(path)
    telegram = data.setdefault("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError("Configurazione Telegram non valida.")
    telegram["enabled"] = bool(enabled)
    _atomic_yaml(path, data)
    return "Notifiche Telegram attivate." if enabled else "Notifiche Telegram disattivate."


def transcription_engines() -> Dict[str, Any]:
    """Quali motori locali girano qui e quale consigliare (macparakeet sul Mac, Parakeet ONNX
    altrove)."""
    import sys

    from rt.core import onnx_stt
    from rt.core.config import default_engine
    from rt.pipeline.setup import find_macparakeet_binary
    return {
        "recommended": default_engine(),
        "macparakeet_available": sys.platform == "darwin",
        "macparakeet_installed": sys.platform == "darwin" and bool(find_macparakeet_binary()),
        "parakeet_available": onnx_stt.available(),
        "parakeet_model_ready": onnx_stt.model_ready(),
    }


def save_transcription(project_root: Path, engine: str, base_url: str,
                       model: str, api_key: str) -> str:
    if api_key.strip():
        _validate_secret(api_key.strip())
    if engine not in {"macparakeet", "parakeet", "custom"}:
        raise ValueError("Motore STT non riconosciuto.")
    base_url, model = base_url.strip().rstrip("/"), model.strip()
    if engine == "custom":
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Inserisci un Base URL HTTP valido per il server STT.")
        if not model:
            raise ValueError("Inserisci l'ID del modello STT.")
    path = general_config_path(project_root)
    data = _read_yaml(path)
    data["transcription"] = {**(data.get("transcription") or {}),
                              "engine": engine, "base_url": base_url or None,
                              "model": model or None}
    telegram = data.setdefault("telegram", {})
    telegram.setdefault("recall", {})["stt_engine"] = engine
    _atomic_yaml(path, data)
    if api_key.strip():
        _save_secret(project_root, "RT_STT_API_KEY", api_key.strip())
    return "Motore di trascrizione salvato."


WORKER_CONCURRENCY_RANGE = (1, 4)


def save_worker_concurrency(project_root: Path, concurrency: int) -> str:
    """Job in parallelo del worker di 'rt web' (worker.concurrency): vale dal prossimo avvio."""
    low, high = WORKER_CONCURRENCY_RANGE
    if not isinstance(concurrency, int) or not low <= concurrency <= high:
        raise ValueError(f"Scegli un numero di job in parallelo tra {low} e {high}.")
    path = general_config_path(project_root)
    data = _read_yaml(path)
    data["worker"] = {**(data.get("worker") or {}), "concurrency": concurrency}
    _atomic_yaml(path, data)
    return "Job in parallelo salvati."


# Avvisi della web che si possono nascondere con "Non mostrare più" (salvati in ui.dismissed_notices).
NOTICES = ("preview_edit_beta", "preview_edit_issues", "setup_wizard")


def save_notice(project_root: Path, notice: str, dismissed: bool) -> str:
    """Nasconde (o rimostra) un avviso della web per tutti i browser: vale lato server."""
    if notice not in NOTICES:
        raise ValueError(f"Avviso sconosciuto: {notice}.")
    path = general_config_path(project_root)
    data = _read_yaml(path)
    ui = dict(data.get("ui") or {})
    current = [n for n in (ui.get("dismissed_notices") or []) if n in NOTICES and n != notice]
    ui["dismissed_notices"] = sorted(current + ([notice] if dismissed else []))
    data["ui"] = ui
    _atomic_yaml(path, data)
    return "Preferenza salvata."


# ---------------------------------------------------------------------------
# Vista d'insieme e pricing (RT4-E4): usate dall'API. Nessun valore segreto esce da qui.
# ---------------------------------------------------------------------------

def secret_is_set(env_var: str) -> bool:
    from rt.core.config import load_env_file
    load_env_file()
    value = os.environ.get(env_var, "").strip()
    return bool(value) and value != "test-disabled-token"


def telegram_value(field: str) -> str:
    """Valore completo del token del bot o del Chat ID ("" se non impostato). Solo per
    l'endpoint di rivelazione su richiesta esplicita: snapshot() ne espone solo l'anteprima."""
    from rt.core.config import load_env_file
    load_env_file()
    env_var = {"bot_token": "RT_TELEGRAM_BOT_TOKEN", "chat_id": "RT_TELEGRAM_CHAT_ID"}[field]
    value = (os.environ.get(env_var) or "").strip()
    return "" if value == "test-disabled-token" else value


def mask_value(value: str) -> str | None:
    """Anteprima parzialmente nascosta: primi e ultimi caratteri (es. 1234…wXyZ)."""
    if not value:
        return None
    n = 4 if len(value) >= 12 else 2 if len(value) >= 6 else 0
    return f"{value[:n]}…{value[-n:]}" if n else "…"


def snapshot(project_root: Path) -> dict[str, Any]:
    """Tutte le impostazioni modificabili, come le mostra la pagina Impostazioni."""
    from rt.core.config import load_env_file
    from rt.security.secrets import default_store_path
    from rt.services.connections_service import PHASES, list_connections, phase_selection
    load_env_file()
    cfg = load_config()
    general = _read_yaml(general_config_path(project_root))
    credentials = []
    for item in general.get("credentials") or []:
        if isinstance(item, dict) and item.get("name"):
            env_var = item.get("env_var") or ""
            credentials.append({"name": item["name"], "provider": item.get("provider") or "",
                                "env_var": env_var, "set": bool(env_var) and secret_is_set(env_var)})
    set_by_name = {c["name"]: c["set"] for c in credentials}
    connections = []
    all_connections = list_connections(project_root)  # legge molti YAML: una volta sola
    for conn in all_connections:
        connections.append({
            "name": conn["name"], "provider": conn.get("provider") or "", "base_url": conn.get("base_url") or "",
            "models": list(conn.get("models") or []),
            "credentials": [{"name": n, "set": set_by_name.get(n, False)} for n in conn.get("credentials") or []],
        })
    phases = []
    for job, label in PHASES:
        connection, model = phase_selection(project_root, job, all_connections)
        phases.append({"job": job, "label": label, "connection": connection, "model": model})
    return {
        "transcription": {
            "engine": cfg.transcription.engine, "base_url": cfg.transcription.base_url,
            "model": cfg.transcription.model, "api_key_set": secret_is_set("RT_STT_API_KEY"),
            **transcription_engines(),
        },
        "telegram": {
            "enabled": cfg.telegram.enabled,
            "bot_token_set": secret_is_set("RT_TELEGRAM_BOT_TOKEN"),
            "bot_token_preview": mask_value(telegram_value("bot_token")),
            "chat_id_set": bool(telegram_value("chat_id")),
            "chat_id_preview": mask_value(telegram_value("chat_id")),
        },
        "worker": {"concurrency": cfg.worker.concurrency, "running": _running_workers()},
        "notices": {"dismissed": [n for n in cfg.ui.dismissed_notices if n in NOTICES]},
        "phases": phases,
        "connections": connections,
        "credentials": credentials,
        "pricing": general.get("pricing") or {},
        "web_search": {
            "searxng_base_url": cfg.searxng_base_url or None,
            "contextual_verification": bool(getattr(cfg, "contextual_web_search", False)),
        },
        "preferences": {
            "secondi_approvazione": cfg.ui.outline_auto_approval_seconds,
            "sfondo_gruppi": {"none": "niente", "gray": "grigi", "colors": "colori"}.get(cfg.ui.group_background, cfg.ui.group_background),
            "modalita_arricchimento": {"off": "disattivata", "manual": "manuale", "pipeline": "automatica"}[classifier_job(cfg,"enrichment").mode],
        },
        "secrets_encrypted": default_store_path().is_file(),
        "data_dir": _data_dir(),
        # Primo avvio: senza connessioni non gira niente, la SPA porta alla configurazione
        # guidata finché non se ne crea una o si sceglie "Configura dopo" (avviso setup_wizard).
        "setup_required": not connections and "setup_wizard" not in cfg.ui.dismissed_notices,
    }


def _running_workers() -> int:
    """Worker (thread) attivi ora: con 'rt web' sono i job che possono girare insieme."""
    try:
        from rt.services.jobs import _optional_queue
        queue = _optional_queue()
        return len(queue.live_workers()) if queue is not None else 0
    except Exception:
        return 0


def _data_dir() -> str | None:
    """Cartella di rt.db e media/ per questo processo (None se il DB è disattivato). Cambiando
    la cartella delle lezioni, il DB predefinito si sposta al prossimo avvio di RT."""
    from rt.db.engine import current_database_url
    from rt.storage import fs
    try:
        return fs.data_dir() if current_database_url() else None
    except Exception:  # noqa: BLE001 - configurazione illeggibile: la pagina mostra solo il resto
        return None


def save_pricing(project_root: Path, pricing: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """Sostituisce il pricing custom (provider -> modello -> prezzi per 1M token)."""
    from rt.llm.pricing import ModelPricing
    clean: dict[str, dict[str, Any]] = {}
    for provider, models in (pricing or {}).items():
        if not str(provider).strip() or not isinstance(models, dict):
            raise ValueError("Pricing non valido: serve provider -> modello -> prezzi.")
        clean[str(provider).strip()] = {
            str(model).strip(): ModelPricing.model_validate(values).model_dump(exclude_none=True)
            for model, values in models.items() if str(model).strip()
        }
    path = general_config_path(project_root)
    data = _read_yaml(path)
    if clean:
        data["pricing"] = clean
    else:
        data.pop("pricing", None)
    _atomic_yaml(path, data)
    return clean


def save_web_search(project_root: Path, searxng_base_url: str | None, contextual_verification: bool | None = None) -> tuple[str | None, bool]:
    """URL base di SearXNG per la ricerca immagini web e toggle verifica contestuale. add_images e
    study_notes lo leggono da load_config() a ogni job: nessun file da modificare a mano.
    searxng_base_url None lascia l'URL com'è (salvataggio del solo interruttore)."""
    from rt.services.probes import normalize_searxng_url
    path = general_config_path(project_root)
    data = _read_yaml(path)
    if searxng_base_url is not None:
        data["searxng_base_url"] = normalize_searxng_url(searxng_base_url) or None
    url = data.get("searxng_base_url")
    if contextual_verification is not None:
        data["contextual_web_search"] = bool(contextual_verification)
    _atomic_yaml(path, data)
    return url or None, bool(data.get("contextual_web_search", False))


def save_secret_by_name(project_root: Path, name: str, value: str) -> str:
    """Salva un segreto dichiarato in configurazione (chiave API di una credenziale, token
    Telegram, chiave STT). Restituisce dove è finito: "store" o "env"."""
    from rt.services.secrets_service import secret_names_from_config
    if name not in secret_names_from_config(general_config_path(project_root)):
        raise KeyError(name)
    _validate_secret(value.strip())
    return config_service.set_secret(name, value.strip(), path=_env_path(project_root))


def delete_secret_by_name(project_root: Path, name: str) -> list[str]:
    """Elimina un segreto dichiarato (archivio cifrato, .env, ambiente del processo), come
    'rt secrets unset'. La credenziale resta dichiarata: la chiave risulta "Mancante"."""
    from rt.services.secrets_service import secret_names_from_config
    if name not in secret_names_from_config(general_config_path(project_root)):
        raise KeyError(name)
    return config_service.unset_secret(name, path=_env_path(project_root))


def save_preferences(project_root: Path, preferences: dict[str, Any]) -> dict[str, Any]:
    path = general_config_path(project_root)
    data = _read_yaml(path)
    ui_data = data.setdefault("ui", {})
    bg_val = preferences.get("sfondo_gruppi", {"none":"niente", "gray":"grigi", "colors":"colori"}.get(ui_data.get("group_background", "colors"), "colori"))
    bg_canonical = {"niente": "none", "grigi": "gray", "colori": "colors"}.get(bg_val, bg_val)
    ui_data["group_background"] = bg_canonical

    secs = int(preferences.get("secondi_approvazione", ui_data.get("outline_auto_approval_seconds", 10)))
    ui_data["outline_auto_approval_seconds"] = secs

    from rt.core.config import RTConfig, ClassifierJobConfig
    from rt.services.classifier_settings import write_classifier
    cfg = RTConfig.model_validate(data)
    classifier = cfg.classifier
    current_mode = classifier_job(cfg, "enrichment").mode
    enr_val = preferences.get("modalita_arricchimento", {"off": "disattivata", "manual": "manuale", "pipeline": "automatica"}[current_mode])
    if "modalita_arricchimento" in preferences:
        classifier.jobs.setdefault("enrichment", ClassifierJobConfig()).mode = {"disattivata": "off", "manuale": "manual", "automatica": "pipeline", "disabled":"off", "automatic":"pipeline"}.get(enr_val, enr_val)
    write_classifier(data, classifier)

    _atomic_yaml(path, data)
    return {
        "secondi_approvazione": secs,
        "sfondo_gruppi": bg_val,
        "modalita_arricchimento": enr_val,
    }
