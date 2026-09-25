"""
rt.pipeline.configure
Wizard interattivo di configurazione guidata per il progetto RT.
Gestisce la configurazione di:
- Provider LLM (DeepSeek, OpenRouter, Google Gemini, OpenAI Compatible) e credenziali.
- Telegram (bot token, chat ID, discovery live topic, lessons_root).
- STT (motore trascrizione risposte vocali).
- Pricing custom opzionale.
"""

import os
import sys
import shutil
import json
import re
import time
import concurrent.futures
from contextlib import contextmanager
from typing import Dict, Any, List, Optional, Tuple, Iterable, Set, Callable, Generator
import yaml
import requests
import questionary
from textual.app import App, ComposeResult
from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths, _default_project_root
from rt.pipeline.setup import clean_input_path


def _is_placeholder_or_invalid_bot_token(token: str) -> bool:
    """Verifica se il token è vuoto, il valore di esempio di .env.example o ha un formato non valido."""
    if not token or not token.strip():
        return True
    t = token.strip()
    if t == "123456:ABC-your-bot-token":
        return True
    if not re.match(r"^\d+:[A-Za-z0-9_-]{30,}$", t):
        return True
    return False


def parse_telegram_topic_link(link: str) -> Optional[Tuple[int, int]]:
    """
    Parsa un link a un messaggio Telegram di un supergruppo/forum (es. 'https://t.me/c/1234567890/12/34')
    e restituisce (chat_id, message_thread_id) come tuple di int, con prefisso -100 sul chat_id.
    Ritorna None se il formato non è valido.
    """
    if not link or not isinstance(link, str):
        return None
    m = re.search(r"t\.me/c/(\d+)/(\d+)", link.strip())
    if not m:
        return None
    channel_num = m.group(1)
    topic_id = int(m.group(2))
    chat_id = int(f"-100{channel_num}")
    return chat_id, topic_id


def _is_valid_float(val: str) -> bool:
    try:
        f = float(val.strip())
        return f >= 0.0
    except Exception:
        return False


def _atomic_write_text(file_path: str, content: str) -> None:
    """Scrive un file di testo in modo atomico tramite file temporaneo + os.replace."""
    tmp_path = file_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, file_path)


def _update_env_file(env_path: str, key: str, value: str) -> None:
    """
    Aggiorna o inserisce una variabile d'ambiente nel file .env preservando le righe esistenti.
    """
    lines: List[str] = []
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
            prefix = "export " if stripped.startswith("export ") else ""
            new_lines.append(f"{prefix}{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    _atomic_write_text(env_path, "".join(new_lines))
    os.environ[key] = value


def _resolve_or_bootstrap_config_paths() -> Tuple[str, str]:
    """
    Risolve i percorsi per la cartella config/ ed il file .env.
    Se config/ non esiste in cwd né in project root, inizializza config/ copiando da config.example/.
    """
    cwd_config = os.path.join(os.getcwd(), "config")
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.isdir(cwd_config):
        return cwd_config, cwd_env

    project_root = _default_project_root()
    root_config = os.path.join(project_root, "config")
    root_env = os.path.join(project_root, ".env")
    if os.path.isdir(root_config):
        return root_config, root_env

    # Inizializzazione primo avvio
    example_config = os.path.join(project_root, "config.example")
    if os.path.isdir(example_config):
        shutil.copytree(example_config, root_config)
    else:
        os.makedirs(root_config, exist_ok=True)

    example_env = os.path.join(project_root, ".env.example")
    if not os.path.isfile(root_env) and os.path.isfile(example_env):
        shutil.copy2(example_env, root_env)
    elif not os.path.isfile(root_env):
        with open(root_env, "w", encoding="utf-8") as f:
            f.write("# RT Environment Configuration\n")

    return root_config, root_env


def _load_model_profiles(general_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Legge general_data.get("model_profiles", {}), normalizza ignorando voci malformate.
    """
    profiles_raw = general_data.get("model_profiles")
    if not isinstance(profiles_raw, dict):
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for name, p_data in profiles_raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(p_data, dict):
            continue
        provider = p_data.get("provider")
        routes = p_data.get("routes")
        if not isinstance(provider, str) or not provider.strip():
            continue
        if not isinstance(routes, list):
            continue

        valid_routes: List[Dict[str, Any]] = []
        for r in routes:
            if isinstance(r, dict) and "credential" in r and "model" in r:
                valid_routes.append({
                    "credential": str(r["credential"]),
                    "model": str(r["model"]),
                })

        normalized[name.strip()] = {
            "provider": provider.strip(),
            "base_url": p_data.get("base_url") if isinstance(p_data.get("base_url"), str) and p_data.get("base_url").strip() else None,
            "round_robin": bool(p_data.get("round_robin", False)),
            "routes": valid_routes,
        }
    return normalized


def _save_model_profiles(general_data: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> None:
    """
    Scrive general_data["model_profiles"] = profiles.
    """
    general_data["model_profiles"] = profiles


def _format_profile_display(profile_name: Optional[str], profiles: Dict[str, Any]) -> str:
    """
    Formatta il nome del profilo aggiungendo '(N chiavi API)' se è configurato in round-robin con N route (N >= 2).
    """
    if not profile_name:
        return "(non impostato)"
    prof_data = profiles.get(profile_name)
    if isinstance(prof_data, dict) and prof_data.get("round_robin") is True:
        routes = prof_data.get("routes", [])
        n_keys = len(routes) if isinstance(routes, list) else 0
        if n_keys > 1:
            return f"{profile_name} ({n_keys} chiavi API)"
    return profile_name


def _suggest_profile_name(provider: str, model: str, existing_names: Iterable[str]) -> str:
    """
    Suggerisce un nome di profilo univoco sanitizzato (es. provider_model).
    Se esiste già in existing_names, aggiunge _2, _3, ecc.
    """
    existing_set = set(existing_names) if existing_names else set()
    raw = f"{provider}_{model}".lower()
    sanitized = re.sub(r"[^a-z0-9_.-]+", "_", raw)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "profilo"

    if sanitized not in existing_set:
        return sanitized

    idx = 2
    while f"{sanitized}_{idx}" in existing_set:
        idx += 1
    return f"{sanitized}_{idx}"


FALLBACK_ROLES: List[Tuple[str, str]] = [
    ("primary", "Primario"),
    ("timeout", "Fallback: timeout"),
    ("rate_limit", "Fallback: rate-limit (429)"),
    ("safety", "Fallback: errore di safety"),
    ("auth", "Fallback: errore di autenticazione"),
    ("generic", "Fallback: generico (qualunque altro errore)"),
]

FALLBACK_ROLE_MAP: Dict[str, str] = {
    "Primario": "primary",
    "Fallback: timeout": "timeout",
    "Fallback: rate-limit (429)": "rate_limit",
    "Fallback: errore di safety": "safety",
    "Fallback: errore di autenticazione": "auth",
    "Fallback: generico (qualunque altro errore)": "generic",
}


def _get_next_free_credential_index(
    general_data: Dict[str, Any],
    provider: str,
    collected_keys: Optional[List[Tuple[str, str, str]]] = None
) -> int:
    """
    Calcola il primo indice numerico univoco libero >= 1 per il provider specificato,
    considerando tutte le credenziali già registrate in general_data e quelle già raccolte.
    """
    used_indices: Set[int] = set()
    prov_clean = provider.lower().strip()
    creds = general_data.get("credentials", [])
    if isinstance(creds, list):
        for c in creds:
            if isinstance(c, dict) and str(c.get("provider", "")).lower().strip() == prov_clean:
                cn = str(c.get("name", ""))
                parts = cn.split("_")
                if len(parts) >= 2 and parts[-1].isdigit():
                    used_indices.add(int(parts[-1]))

    if collected_keys:
        for cn, ce, _ in collected_keys:
            parts = cn.split("_")
            if len(parts) >= 2 and parts[-1].isdigit():
                used_indices.add(int(parts[-1]))

    idx = 1
    while idx in used_indices:
        idx += 1
    return idx


def _create_new_model_profile(
    config_dir: str,
    env_path: str,
    general_data: Dict[str, Any],
    default_name_hint: Optional[str] = None,
    ask_role: bool = False,
    group_label: Optional[str] = None,
    current_phase_assignments: Optional[Dict[str, Optional[str]]] = None
) -> Any:
    """
    Contiene la logica interattiva per raccogliere provider, base_url, chiavi (singola o round-robin),
    recupero modelli, pricing inline, e salvataggio credenziali, chiedendo un nome per il nuovo profilo.
    Restituisce (profile_name, profile_dict) se ask_role=False,
    oppure (profile_name, profile_dict, role_name_o_None) se ask_role=True.
    """
    general_yaml_path = os.path.join(config_dir, "general.yaml")

    # 1. Selezione Provider
    allowed_providers = ["deepseek", "openrouter", "google", "openai_compatible"]
    provider = questionary.select(
        "Provider LLM:",
        choices=allowed_providers,
        default="deepseek"
    ).ask()

    if not provider:
        return ("", {}, None) if ask_role else ("", {})

    # 2. Base URL
    default_base = KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, "")

    if provider == "openai_compatible":
        base_url = ""
        while not base_url:
            base_url = questionary.text(
                "Base URL (es. https://api.together.xyz/v1 - obbligatorio):",
                default=default_base
            ).ask()
            if base_url is None:
                return ("", {}, None) if ask_role else ("", {})
            base_url = base_url.strip()
            if not base_url:
                print("⚠️  Il provider 'openai_compatible' richiede un Base URL non vuoto.")
    else:
        base_url_input = questionary.text(
            f"Base URL per {provider} (lascia vuoto per default '{default_base}'):",
            default=""
        ).ask()
        if base_url_input is None:
            return ("", {}, None) if ask_role else ("", {})
        base_url_input = base_url_input.strip()
        if not base_url_input or base_url_input == default_base:
            base_url = None
        else:
            base_url = base_url_input


    # 3. Round-Robin Multi-chiave o Singola API Key
    multi_input = questionary.confirm(
        f"Vuoi configurare più chiavi API per {provider}?",
        default=False
    ).ask()

    if multi_input is None:
        return "", {}

    is_multi = (multi_input is True)
    collected_keys: List[Tuple[str, str, str]] = []  # (cred_name, env_var_name, key_val)
    rr_action = "add"

    if is_multi:
        existing_creds: List[Tuple[str, str, str]] = []
        creds = general_data.get("credentials")
        if isinstance(creds, list):
            for c in creds:
                if isinstance(c, dict) and c.get("provider") == provider:
                    cn = c.get("name", "")
                    ce = c.get("env_var", "")
                    val = os.environ.get(ce, "")
                    if cn and ce:
                        existing_creds.append((cn, ce, val))

        if existing_creds:
            print(f"\nTrovate {len(existing_creds)} chiavi round-robin già configurate per {provider}.")
            action_choice = questionary.select(
                f"Gestione chiavi round-robin per {provider}:",
                choices=[
                    "➕ Aggiungi altre chiavi",
                    "🆕 Crea un pool separato (nuove chiavi indipendenti, non condivise con altri profili)",
                    "🔄 Sostituisci le chiavi di questo pool con altre nuove",
                    "⏭ Mantieni le chiavi esistenti"
                ],
                default="➕ Aggiungi altre chiavi"
            ).ask()

            if action_choice is None:
                return "", {}

            if action_choice.startswith("⏭"):
                rr_action = "keep"
                collected_keys = list(existing_creds)
            elif action_choice.startswith("🆕"):
                rr_action = "separate_pool"
                collected_keys = []
            elif action_choice.startswith("🔄"):
                rr_action = "replace"
                collected_keys = []
            else:
                rr_action = "add"
                collected_keys = list(existing_creds)

        if rr_action != "keep":
            batch_prompt = (
                f"Incolla una o più API key per {provider}, separate da virgola "
                f"(invio vuoto per terminare se hai già inserito tutte le chiavi):"
            )
            while True:
                batch_in = questionary.password(batch_prompt).ask()
                if batch_in is None:
                    return "", {}
                raw_keys = [k.strip() for k in batch_in.split(",") if k.strip()]
                if not raw_keys:
                    break
                for key_val in raw_keys:
                    if rr_action == "replace":
                        curr_idx = len(collected_keys) + 1
                    else:
                        curr_idx = _get_next_free_credential_index(general_data, provider, collected_keys)
                    cn = "google_1" if (provider == "google" and curr_idx == 1) else f"{provider.lower()}_{curr_idx}"
                    ce = f"{provider.upper()}_API_KEY_{curr_idx}"
                    collected_keys.append((cn, ce, key_val))
                print(f"✅ {len(raw_keys)} chiave/i aggiunta/e (totale: {len(collected_keys)}).")

        if len(collected_keys) < 2:
            if len(collected_keys) == 1:
                print("\n⚠️ Avviso: Inserita una sola chiave. Il round-robin richiede almeno 2 chiavi. Procedo con configurazione singola (round_robin: false).")
                is_multi = False
            else:
                print("⚠️ Nessuna API key fornita. Operazione annullata.")
                return "", {}

    if not is_multi:
        if collected_keys:
            cred_name, env_var_name, api_key = collected_keys[0]
        else:
            env_var_name = f"{provider.upper()}_API_KEY"
            existing_key = os.environ.get(env_var_name, "")
            if existing_key:
                print(f"\nTrovata una chiave già configurata per {provider}.")
            prompt_msg = (
                f"API key per {provider} (lascia vuoto per mantenere esistente):"
                if existing_key
                else f"API key per {provider}:"
            )
            api_key_input = questionary.password(
                prompt_msg,
                default=existing_key
            ).ask()

            if api_key_input is None:
                return "", {}

            api_key = api_key_input.strip() if api_key_input.strip() else existing_key
            cred_name = "google_1" if provider == "google" else f"{provider.lower()}_1"

        if api_key:
            _update_env_file(env_path, env_var_name, api_key)
            creds = general_data.get("credentials")
            if not isinstance(creds, list):
                creds = []

            found_cred = False
            for c in creds:
                if isinstance(c, dict) and (c.get("name") == cred_name or c.get("env_var") == env_var_name):
                    c["name"] = cred_name
                    c["provider"] = provider
                    c["env_var"] = env_var_name
                    found_cred = True
                    break

            if not found_cred:
                creds.append({
                    "name": cred_name,
                    "provider": provider,
                    "env_var": env_var_name
                })

            general_data["credentials"] = creds
            _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
    else:
        creds = general_data.get("credentials")
        if not isinstance(creds, list):
            creds = []

        for cn, ce, key_val in collected_keys:
            if key_val:
                _update_env_file(env_path, ce, key_val)
            found_c = False
            for c in creds:
                if isinstance(c, dict) and (c.get("name") == cn or c.get("env_var") == ce):
                    c["name"] = cn
                    c["provider"] = provider
                    c["env_var"] = ce
                    found_c = True
                    break
            if not found_c:
                creds.append({
                    "name": cn,
                    "provider": provider,
                    "env_var": ce
                })

        general_data["credentials"] = creds
        _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
        api_key = collected_keys[0][2]
        cred_name = collected_keys[0][0]
        env_var_name = collected_keys[0][1]

    # 4. Recupero Modelli
    effective_base_url = base_url or default_base
    models_list: List[str] = []
    fetch_error_reason: Optional[str] = None

    if api_key and effective_base_url:
        if provider == "google":
            try:
                native_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                resp = requests.get(native_url, timeout=8)
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and "models" in body and isinstance(body["models"], list):
                        for item in body["models"]:
                            if isinstance(item, dict) and "name" in item and isinstance(item["name"], str):
                                m_name = item["name"]
                                if m_name.startswith("models/"):
                                    m_name = m_name[len("models/"):]
                                models_list.append(m_name)
                else:
                    fetch_error_reason = f"HTTP {resp.status_code} da endpoint nativo Google models"
            except Exception as ex:
                fetch_error_reason = f"Errore di rete ({type(ex).__name__}: {ex})"

        models_pricing: Dict[str, Dict[str, float]] = {}
        if not models_list:
            try:
                target_url = effective_base_url.rstrip("/") + "/models"
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(target_url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and "data" in body and isinstance(body["data"], list):
                        for item in body["data"]:
                            if isinstance(item, dict) and "id" in item and isinstance(item["id"], str):
                                m_id = item["id"]
                                models_list.append(m_id)
                                p_dict = item.get("pricing")
                                if isinstance(p_dict, dict):
                                    try:
                                        p_in = float(p_dict.get("prompt", 0)) * 1_000_000.0
                                        p_out = float(p_dict.get("completion", 0)) * 1_000_000.0
                                        models_pricing[m_id] = {
                                            "input_per_million": round(p_in, 4),
                                            "output_per_million": round(p_out, 4)
                                        }
                                    except (ValueError, TypeError):
                                        pass
                    if not models_list:
                        fetch_error_reason = "Risposta 200 ma nessun modello trovato nella struttura 'data'"
                else:
                    fetch_error_reason = f"HTTP {resp.status_code} su {target_url}"
            except Exception as ex:
                fetch_error_reason = f"Errore di rete ({type(ex).__name__}: {ex})"
    else:
        if not api_key:
            fetch_error_reason = "Nessuna API key configurata o inserita per questo provider"
        elif not effective_base_url:
            fetch_error_reason = "Nessun Base URL specificato per questo provider"

    chosen_model = ""
    while True:
        if models_list:
            model_in = questionary.autocomplete(
                "Seleziona o digita il modello LLM:",
                choices=models_list,
                default="",
                ignore_case=True,
                match_middle=True,
                validate=lambda v: bool(v and v.strip()) or "Inserisci un ID modello valido"
            ).ask()
            if model_in is None:
                return "", {}
            chosen_model = model_in.strip()
        else:
            if fetch_error_reason:
                print(f"ℹ️ Impossibile recuperare la lista modelli automaticamente: {fetch_error_reason}")
            else:
                print("ℹ️ Impossibile recuperare la lista modelli automaticamente.")
            manual_model = questionary.text(
                "ID Modello (es. deepseek-chat, google/gemini-2.5-flash):",
                validate=lambda v: bool(v and v.strip()) or "Inserisci un ID modello valido"
            ).ask()
            if manual_model is None:
                return "", {}
            chosen_model = manual_model.strip()

        if not chosen_model:
            return "", {}

        confirm_model = questionary.confirm(
            f"Hai selezionato '{chosen_model}' — confermi?",
            default=True
        ).ask()
        if confirm_model is None:
            return "", {}
        if confirm_model:
            break

    # Pricing inline opzionale per questo modello (con eventuale pricing rilevato automaticamente)
    detected_p = models_pricing.get(chosen_model) if 'models_pricing' in locals() else None
    _configure_pricing_section(config_dir, provider, chosen_model, detected_pricing=detected_p)

    # Scelta nome del profilo
    existing_profiles = _load_model_profiles(general_data)
    if default_name_hint and default_name_hint not in existing_profiles:
        suggested_name = default_name_hint
    else:
        suggested_name = _suggest_profile_name(provider, chosen_model, existing_profiles.keys())

    while True:
        profile_name_in = questionary.text(
            "Nome per questo profilo modello (per riusarlo in altre fasi):",
            default=suggested_name
        ).ask()
        if not profile_name_in or not profile_name_in.strip():
            return "", {}
        profile_name = profile_name_in.strip()
        if profile_name in existing_profiles:
            overwrite = questionary.confirm(
                f"⚠️  Il profilo '{profile_name}' esiste già. Vuoi sovrascriverlo?",
                default=False
            ).ask()
            if overwrite:
                break
            else:
                suggested_name = _suggest_profile_name(provider, chosen_model, existing_profiles.keys())
        else:
            break

    if is_multi:
        routes = [{"credential": cn, "model": chosen_model} for cn, ce, kv in collected_keys]
    else:
        routes = [{"credential": cred_name, "model": chosen_model}]

    profile_dict = {
        "provider": provider,
        "base_url": base_url,
        "round_robin": is_multi,
        "routes": routes,
    }

    if ask_role and group_label is not None and current_phase_assignments is not None:
        role_choices = [label for _, label in FALLBACK_ROLES] + ["❌ Annulla"]
        while True:
            try:
                chosen = questionary.select(
                    f"Come vuoi usare il nuovo profilo '{profile_name}' per la fase '{group_label}'?",
                    choices=role_choices,
                    default="Primario"
                ).ask()
            except (EOFError, Exception):
                chosen = "Primario"

            if not chosen or chosen == "❌ Annulla":
                return profile_name, profile_dict, None
            rk = FALLBACK_ROLE_MAP.get(chosen)
            if not rk:
                return profile_name, profile_dict, None
            if rk == "primary":
                conflicting = [k for k in ("timeout", "rate_limit", "safety", "auth", "generic") if current_phase_assignments.get(k) == profile_name]
                if conflicting:
                    print(f"\n⚠️  Il profilo '{profile_name}' è già assegnato come fallback ({', '.join(conflicting)}) per questa fase.")
                    print("   Un modello non può essere contemporaneamente Primario e Fallback nella stessa fase.\n")
                    continue
            else:
                if current_phase_assignments.get("primary") == profile_name:
                    print(f"\n⚠️  Il profilo '{profile_name}' è già assegnato come Primario per questa fase.")
                    print("   Un modello non può essere contemporaneamente Primario e Fallback nella stessa fase.\n")
                    continue
            return profile_name, profile_dict, rk

    if ask_role:
        return profile_name, profile_dict, None
    return profile_name, profile_dict


def _apply_profile_to_job(job_file: str, profile: Dict[str, Any]) -> None:
    """
    Applica un profilo modello a un file <job>.yaml preservando i campi di tuning non-provider/model/credential.
    """
    job_data: Dict[str, Any] = {}
    if os.path.isfile(job_file):
        try:
            with open(job_file, "r", encoding="utf-8") as f:
                loaded_job = yaml.safe_load(f)
                if isinstance(loaded_job, dict):
                    job_data = loaded_job
        except Exception:
            pass

    tuning_fields: Dict[str, Any] = {}
    source_dict: Optional[Dict[str, Any]] = None
    if "primary" in job_data and isinstance(job_data["primary"], dict):
        source_dict = job_data["primary"]
    elif "primary_routes" in job_data and isinstance(job_data["primary_routes"], list) and len(job_data["primary_routes"]) > 0:
        if isinstance(job_data["primary_routes"][0], dict):
            source_dict = job_data["primary_routes"][0]

    if source_dict:
        for k in ("thinking", "reasoning_effort", "max_thinking_tokens", "max_tokens", "timeout_seconds", "provider_routing"):
            if k in source_dict:
                tuning_fields[k] = source_dict[k]

    provider = profile["provider"]
    base_url = profile.get("base_url")
    is_multi = profile.get("round_robin", False)
    routes_in = profile.get("routes", [])

    if is_multi:
        routes_list: List[Dict[str, Any]] = []
        for r in routes_in:
            r_entry: Dict[str, Any] = {
                "provider": provider,
                "model": r.get("model", ""),
                "credential": r.get("credential", ""),
            }
            if base_url:
                r_entry["base_url"] = base_url
            r_entry.update(tuning_fields)
            routes_list.append(r_entry)

        job_data["round_robin"] = True
        job_data["primary_routes"] = routes_list
        job_data.pop("primary", None)
        job_data.pop("secondary", None)
    else:
        first_r = routes_in[0] if routes_in else {"credential": f"{provider}_1", "model": ""}
        prim: Dict[str, Any] = {
            "provider": provider,
            "model": first_r.get("model", ""),
            "credential": first_r.get("credential", ""),
        }
        if base_url:
            prim["base_url"] = base_url
        prim.update(tuning_fields)

        job_data["primary"] = prim
        job_data.pop("primary_routes", None)
        job_data.pop("secondary", None)
        job_data["round_robin"] = False

    _atomic_write_text(job_file, yaml.safe_dump(job_data, sort_keys=False, allow_unicode=True))


def _apply_fallback_to_job(job_file: str, slot: str, profile: Optional[Dict[str, Any]]) -> None:
    """
    Applica o rimuove un profilo modello per uno specifico slot di fallback in <job>.yaml.
    Se il profilo è round-robin, assegna la prima route del profilo allo slot di fallback.
    """
    job_data: Dict[str, Any] = {}
    if os.path.isfile(job_file):
        try:
            with open(job_file, "r", encoding="utf-8") as f:
                loaded_job = yaml.safe_load(f)
                if isinstance(loaded_job, dict):
                    job_data = loaded_job
        except Exception:
            pass

    if profile is None:
        if "fallback" in job_data and isinstance(job_data["fallback"], dict):
            job_data["fallback"].pop(slot, None)
            if not job_data["fallback"]:
                job_data.pop("fallback", None)
    else:
        provider = profile["provider"]
        base_url = profile.get("base_url")
        routes_in = profile.get("routes", [])
        first_r = routes_in[0] if routes_in else {"credential": f"{provider}_1", "model": ""}
        fb_entry: Dict[str, Any] = {
            "provider": provider,
            "model": first_r.get("model", ""),
            "credential": first_r.get("credential", ""),
        }
        if base_url:
            fb_entry["base_url"] = base_url

        if "fallback" not in job_data or not isinstance(job_data["fallback"], dict):
            job_data["fallback"] = {}
        job_data["fallback"][slot] = fb_entry

    _atomic_write_text(job_file, yaml.safe_dump(job_data, sort_keys=False, allow_unicode=True))


def _find_matching_profile_for_single_route(route_dict: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Trova il profilo modello corrispondente a un singolo blocco route (es. fallback slot).
    """
    if not isinstance(route_dict, dict):
        return None
    r_prov = route_dict.get("provider")
    r_mod = route_dict.get("model")
    r_cred = route_dict.get("credential")
    r_base = route_dict.get("base_url")
    if not r_prov:
        return None

    norm_r_base = r_base.strip() if isinstance(r_base, str) and r_base.strip() else None

    for prof_name, prof_data in profiles.items():
        if prof_data.get("provider") != r_prov:
            continue
        prof_base = prof_data.get("base_url")
        norm_prof_base = prof_base.strip() if isinstance(prof_base, str) and prof_base.strip() else None
        if norm_prof_base != norm_r_base:
            continue
        for r in prof_data.get("routes", []):
            if isinstance(r, dict) and r.get("credential") == r_cred and r.get("model") == r_mod:
                return prof_name
    return None


def _ask_and_assign_role(profile_name: str, group_label: str, phase_map: Dict[str, Optional[str]]) -> bool:
    """
    Chiede all'utente il ruolo con cui usare profile_name per la fase group_label.
    Valida il vincolo di mutua esclusione tra Primario e Fallback per la stessa fase.
    """
    role_choices = [label for _, label in FALLBACK_ROLES] + ["❌ Annulla"]

    while True:
        try:
            chosen = questionary.select(
                f"Come vuoi usare '{profile_name}' per la fase '{group_label}'?",
                choices=role_choices,
                default="Primario"
            ).ask()
        except (EOFError, Exception):
            chosen = "Primario"

        if not chosen or chosen == "❌ Annulla":
            return False

        role_key = FALLBACK_ROLE_MAP.get(chosen)
        if not role_key:
            return False

        if role_key == "primary":
            conflicting_fbs = [k for k in ("timeout", "rate_limit", "safety", "auth", "generic") if phase_map.get(k) == profile_name]
            if conflicting_fbs:
                print(f"\n⚠️  Il profilo '{profile_name}' è già assegnato come fallback ({', '.join(conflicting_fbs)}) per questa fase.")
                print("   Un modello non può essere contemporaneamente Primario e Fallback nella stessa fase.\n")
                continue
        else:
            if phase_map.get("primary") == profile_name:
                print(f"\n⚠️  Il profilo '{profile_name}' è già assegnato come Primario per questa fase.")
                print("   Un modello non può essere contemporaneamente Primario e Fallback nella stessa fase.\n")
                continue

        phase_map[role_key] = profile_name
        print(f"✅ Assegnato '{profile_name}' come {chosen} per '{group_label}'.")
        return True


_JOB_GROUPS: List[Tuple[str, List[str]]] = [
    ("outline", ["outline"]),
    ("rewrite", ["rewrite"]),
    ("review", ["review"]),
    ("immagini", ["image_description", "image_unit_judge"]),
    ("recall", ["recall", "recall_quiz", "recall_mirata", "recall_vasta",
                "recall_eval_mirata", "recall_eval_vasta"]),
]


def _job_has_real_config(job_data: Dict[str, Any]) -> bool:
    """
    Ritorna True se il job ha una configurazione LLM reale (non un guscio vuoto senza provider).
    """
    if not isinstance(job_data, dict):
        return False
    if job_data.get("round_robin") is True:
        routes = job_data.get("primary_routes")
        if isinstance(routes, list) and len(routes) > 0:
            first = routes[0]
            if isinstance(first, dict) and first.get("provider"):
                return True
    prim = job_data.get("primary")
    if isinstance(prim, dict) and prim.get("provider"):
        return True
    return False


def _find_matching_profile(job_data: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Confronta la configurazione LLM attuale di un job con la libreria dei profili noti.
    Restituisce il nome del profilo se v'è corrispondenza esatta, altrimenti None.
    """
    if not _job_has_real_config(job_data):
        return None

    is_rr = bool(job_data.get("round_robin", False))
    job_provider: Optional[str] = None
    job_base_url: Optional[str] = None
    job_routes_set: Set[Tuple[str, str]] = set()

    if is_rr:
        routes = job_data.get("primary_routes", [])
        if isinstance(routes, list) and len(routes) > 0:
            first = routes[0]
            if isinstance(first, dict):
                job_provider = first.get("provider")
                job_base_url = first.get("base_url")
            for r in routes:
                if isinstance(r, dict):
                    cred = str(r.get("credential", ""))
                    mod = str(r.get("model", ""))
                    job_routes_set.add((cred, mod))
    else:
        prim = job_data.get("primary", {})
        if isinstance(prim, dict):
            job_provider = prim.get("provider")
            job_base_url = prim.get("base_url")
            cred = str(prim.get("credential", ""))
            mod = str(prim.get("model", ""))
            job_routes_set.add((cred, mod))

    if not job_provider:
        return None

    norm_job_base = job_base_url.strip() if isinstance(job_base_url, str) and job_base_url.strip() else None

    for prof_name, prof_data in profiles.items():
        if prof_data.get("provider") != job_provider:
            continue
        if bool(prof_data.get("round_robin", False)) != is_rr:
            continue

        prof_base = prof_data.get("base_url")
        norm_prof_base = prof_base.strip() if isinstance(prof_base, str) and prof_base.strip() else None
        if norm_prof_base != norm_job_base:
            continue

        prof_routes = prof_data.get("routes", [])
        prof_routes_set = set(
            (str(r.get("credential", "")), str(r.get("model", "")))
            for r in prof_routes if isinstance(r, dict)
        )

        if job_routes_set == prof_routes_set:
            return prof_name

    return None


def _run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Esegue una funzione sincrona (es. prompt questionary) in un thread separato per evitare conflitti con l'event loop di Textual."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        return future.result()


class ConfigurePhaseRolesApp(App[None]):
    """Textual App per la configurazione dei ruoli LLM per fase della pipeline."""

    BINDINGS = [
        ("up", "cursor_up", "Su"),
        ("k", "cursor_up", "Su"),
        ("down", "cursor_down", "Giù"),
        ("j", "cursor_down", "Giù"),
        ("left", "card_prev", "Card precedente"),
        ("b", "card_prev", "Card precedente"),
        ("right", "card_next", "Card successiva"),
        ("n", "card_next", "Card successiva"),
        ("c", "jump_confirm", "Conferma"),
        ("f", "jump_confirm", "Conferma"),
        ("enter", "select", "Seleziona"),
        ("space", "select", "Seleziona"),
        ("1", "select_1", "Opzione 1"),
        ("2", "select_2", "Opzione 2"),
        ("3", "select_3", "Opzione 3"),
        ("q", "quit_wizard", "Esci"),
        ("ctrl+q", "quit_wizard", "Esci"),
        ("ctrl+c", "quit_wizard", "Esci"),
    ]

    def __init__(
        self,
        config_dir: str,
        env_path: str,
        general_data: Dict[str, Any],
        general_yaml_path: str,
        profiles: Dict[str, Dict[str, Any]],
        job_paths: Dict[str, str],
        grouped_jobs: List[Tuple[str, List[str]]],
        group_info: Dict[str, Tuple[List[str], bool, Optional[str]]],
        pending_selections: Dict[str, Dict[str, Optional[str]]],
    ) -> None:
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        apply_saved_theme(self)
        self.config_dir = config_dir
        self.env_path = env_path
        self.general_data = general_data
        self.general_yaml_path = general_yaml_path
        self.profiles = profiles
        self.job_paths = job_paths
        self.grouped_jobs = grouped_jobs
        self.group_info = group_info
        self.pending_selections = pending_selections

        self.curr_idx: int = 0
        self.option_indices: Dict[int, int] = {}
        self.confirm_option_idx: int = 0
        self.result_assignments: Optional[Dict[str, str]] = None

    SKIP_LABEL = "⏭ Lascia vuoto per ora"
    NEW_PROFILE = "➕ Configura un nuovo modello per questa fase"
    REMOVE_LABEL = "🗑 Rimuovi un'assegnazione"
    keep_label = "🔧 Mantieni configurazione attuale (non riconosciuta come profilo salvato)"

    _test_key_sequence: Optional[Iterable[str]] = None

    def compose(self) -> ComposeResult:
        yield Static(id="carousel_view")

    def on_mount(self) -> None:
        self._update_view()

    def _simulate_keys(self, keys: Iterable[str]) -> None:
        key_map = {
            "up": self.action_cursor_up,
            "k": self.action_cursor_up,
            "down": self.action_cursor_down,
            "j": self.action_cursor_down,
            "left": self.action_card_prev,
            "b": self.action_card_prev,
            "right": self.action_card_next,
            "n": self.action_card_next,
            "c": self.action_jump_confirm,
            "f": self.action_jump_confirm,
            "enter": self.action_select,
            " ": self.action_select,
            "space": self.action_select,
            "q": self.action_quit_wizard,
            "quit": self.action_quit_wizard,
            "esci": self.action_quit_wizard,
            "1": self.action_select_1,
            "2": self.action_select_2,
            "3": self.action_select_3,
        }
        for k in keys:
            if self.result_assignments is not None:
                break
            action = key_map.get(k.strip().lower())
            if action:
                action()

    def run(self, *args: Any, **kwargs: Any) -> Any:
        if self._test_key_sequence is not None:
            self._simulate_keys(self._test_key_sequence)
            return None
        return super().run(*args, **kwargs)

    def _get_choices_for_card(self, idx: int) -> List[str]:
        if idx >= len(self.grouped_jobs):
            return []
        group_label, _ = self.grouped_jobs[idx]
        _, has_unrecognized, _ = self.group_info[group_label]
        phase_map = self.pending_selections.get(group_label, {})

        choices: List[str] = []
        if has_unrecognized and phase_map.get("primary") == self.keep_label:
            choices.append(self.keep_label)
        choices.append(self.SKIP_LABEL)
        choices.extend(sorted(self.profiles.keys()))
        choices.append(self.NEW_PROFILE)

        has_assigned_roles = any(phase_map.get(r) for r in ("primary", "timeout", "rate_limit", "safety", "auth", "generic"))
        if has_assigned_roles:
            choices.append(self.REMOVE_LABEL)
        return choices

    def _render_panel(self) -> Panel:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx >= total_groups:
            # Confirmation View
            lines = [
                "📋 RIEPILOGO ASSEGNAZIONI FASI",
                "-" * 50,
            ]
            for idx, (gl, gjobs) in enumerate(self.grouped_jobs, start=1):
                pmap = self.pending_selections.get(gl, {})
                prim = pmap.get("primary")
                status_icon = "✅" if prim else "⏳"
                prim_str = _format_profile_display(prim, self.profiles) if prim else "(nessun primario)"
                fb_parts = [f"{k}->{_format_profile_display(v, self.profiles)}" for k, v in pmap.items() if k != "primary" and v]
                fb_str = f" [FB: {', '.join(fb_parts)}]" if fb_parts else ""
                lines.append(f" {status_icon} [{idx}/{total_groups}] {gl}: {prim_str}{fb_str}")
            lines.append("-" * 50)
            lines.append("\nCome desideri procedere?\n")

            confirm_choices = [
                "✅ Conferma e applica configurazione",
                "✏️ Modifica una fase specificata",
                "❌ Annulla configurazione modelli"
            ]
            for opt_i, opt_text in enumerate(confirm_choices):
                pointer = "▶ " if opt_i == self.confirm_option_idx else "  "
                lines.append(f"{pointer}{opt_text}")

            lines.append("\n[UP/DOWN=Sposta cursore | ENTER=Seleziona | LEFT=Torna alla card precedente | Q=Esci]")
            return Panel(Text("\n".join(lines)), title="📋 CONFERMA CONFIGURAZIONE MODELLI", border_style="magenta")
        else:
            # Phase Card View
            group_label, group_jobs = self.grouped_jobs[self.curr_idx]
            _, has_unrecognized, _ = self.group_info[group_label]
            phase_map = self.pending_selections.get(group_label, {})
            choices = self._get_choices_for_card(self.curr_idx)

            opt_idx = self.option_indices.get(self.curr_idx, 0)
            if opt_idx >= len(choices):
                opt_idx = 0
            self.option_indices[self.curr_idx] = opt_idx

            status_line = []
            for i, (gl, _) in enumerate(self.grouped_jobs):
                prim = self.pending_selections.get(gl, {}).get("primary")
                st = "✅" if prim else "⏳"
                marker = f"[{gl} {st}]" if i == self.curr_idx else f"{gl} {st}"
                status_line.append(marker)
            status_bar = "Avanzamento: " + " | ".join(status_line)

            lines = [
                status_bar,
                "",
                f"Configurazione ruoli per la fase '{group_label}' (inclusi {len(group_jobs)} job: {', '.join(group_jobs)}):",
                "",
            ]
            prim_val = phase_map.get("primary")
            prim_display = _format_profile_display(prim_val, self.profiles) if prim_val else "(non impostato — obbligatorio)"
            lines.append(f"  ⭐ Primario (obbligatorio):    {prim_display}")
            lines.append("  🛡️  Fallback (tutti opzionali):")
            for r_key, r_title in [
                ("timeout", "Fallback timeout:       "),
                ("rate_limit", "Fallback rate-limit:    "),
                ("safety", "Fallback safety:        "),
                ("auth", "Fallback auth:          "),
                ("generic", "Fallback generico:      "),
            ]:
                val = phase_map.get(r_key)
                val_str = _format_profile_display(val, self.profiles) if val else "(non impostato)"
                lines.append(f"     {r_title} {val_str}")
            lines.append("")
            lines.append("Opzioni disponibili:")
            for opt_i, opt_text in enumerate(choices):
                pointer = "▶ " if opt_i == opt_idx else "  "
                lines.append(f"  {pointer}{opt_text}")

            lines.append("\n[UP/DOWN=Sposta cursore | ENTER=Seleziona | LEFT/RIGHT=Cambia card | C=Conferma / Q=Esci]")
            return Panel(Text("\n".join(lines)), title=f"🤖 FASE [{self.curr_idx + 1}/{total_groups}]: {group_label}", border_style="cyan")

    def _update_view(self) -> None:
        try:
            widget = self.query_one("#carousel_view", Static)
            widget.update(self._render_panel())
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx >= total_groups:
            self.confirm_option_idx = (self.confirm_option_idx - 1) % 3
        else:
            choices = self._get_choices_for_card(self.curr_idx)
            if choices:
                opt_idx = self.option_indices.get(self.curr_idx, 0)
                self.option_indices[self.curr_idx] = (opt_idx - 1) % len(choices)
        self._update_view()

    def action_cursor_down(self) -> None:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx >= total_groups:
            self.confirm_option_idx = (self.confirm_option_idx + 1) % 3
        else:
            choices = self._get_choices_for_card(self.curr_idx)
            if choices:
                opt_idx = self.option_indices.get(self.curr_idx, 0)
                self.option_indices[self.curr_idx] = (opt_idx + 1) % len(choices)
        self._update_view()

    def action_card_prev(self) -> None:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx >= total_groups:
            self.curr_idx = total_groups - 1
        else:
            self.curr_idx = max(0, self.curr_idx - 1)
        self._update_view()

    def action_card_next(self) -> None:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx < total_groups:
            self.curr_idx = min(total_groups, self.curr_idx + 1)
        self._update_view()

    def action_jump_confirm(self) -> None:
        self.curr_idx = len(self.grouped_jobs)
        self._update_view()

    @contextmanager
    def _safe_suspend(self) -> Generator[None, None, None]:
        try:
            with self.suspend():
                yield
        except Exception:
            yield

    def action_quit_wizard(self) -> None:
        self.result_assignments = None
        if self.is_running:
            self.exit()

    def action_select_1(self) -> None:
        if self.curr_idx >= len(self.grouped_jobs):
            self.confirm_option_idx = 0
            self.action_select()

    def action_select_2(self) -> None:
        if self.curr_idx >= len(self.grouped_jobs):
            self.confirm_option_idx = 1
            self.action_select()

    def action_select_3(self) -> None:
        if self.curr_idx >= len(self.grouped_jobs):
            self.confirm_option_idx = 2
            self.action_select()

    def action_select(self) -> None:
        total_groups = len(self.grouped_jobs)
        if self.curr_idx >= total_groups:
            if self.confirm_option_idx == 0:  # Conferma e applica
                job_assignments: Dict[str, str] = {}
                for gl, group_jobs in self.grouped_jobs:
                    pmap = self.pending_selections.get(gl, {})
                    primary_sel = pmap.get("primary")
                    g_jobs, g_has_unrec, g_match = self.group_info[gl]
                    for jn in group_jobs:
                        job_file = self.job_paths[jn]
                        if g_has_unrec and primary_sel == self.keep_label:
                            job_assignments[jn] = "(configurazione attuale mantenuta)"
                        elif not primary_sel or primary_sel == self.SKIP_LABEL:
                            job_assignments[jn] = "(non configurato)"
                        else:
                            _apply_profile_to_job(job_file, self.profiles[primary_sel])
                            job_assignments[jn] = primary_sel

                        for slot in ("timeout", "rate_limit", "safety", "auth", "generic"):
                            fb_prof_name = pmap.get(slot)
                            fb_prof_dict = self.profiles.get(fb_prof_name) if fb_prof_name else None
                            _apply_fallback_to_job(job_file, slot, fb_prof_dict)

                _save_model_profiles(self.general_data, self.profiles)
                _atomic_write_text(self.general_yaml_path, yaml.safe_dump(self.general_data, sort_keys=False, allow_unicode=True))
                self.result_assignments = job_assignments
                if self.is_running:
                    self.exit()
            elif self.confirm_option_idx == 1:  # Modifica una fase
                def _choose_phase() -> Optional[str]:
                    try:
                        return questionary.select(
                            "Seleziona la fase da modificare:",
                            choices=[gl for gl, _ in self.grouped_jobs]
                        ).ask()
                    except (EOFError, Exception):
                        return None
                with self._safe_suspend():
                    phase_choice = _run_in_thread(_choose_phase)
                if phase_choice:
                    for i, (gl, _) in enumerate(self.grouped_jobs):
                        if gl == phase_choice:
                            self.curr_idx = i
                            break
                self._update_view()
            elif self.confirm_option_idx == 2:  # Annulla
                self.result_assignments = None
                if self.is_running:
                    self.exit()
        else:
            group_label, group_jobs = self.grouped_jobs[self.curr_idx]
            choices = self._get_choices_for_card(self.curr_idx)
            opt_idx = self.option_indices.get(self.curr_idx, 0)
            if opt_idx >= len(choices):
                opt_idx = 0
            selected_choice = choices[opt_idx]

            if selected_choice == self.keep_label:
                self.pending_selections[group_label]["primary"] = self.keep_label
                self._update_view()
            elif selected_choice == self.SKIP_LABEL:
                for r in ("primary", "timeout", "rate_limit", "safety", "auth", "generic"):
                    self.pending_selections[group_label][r] = None
                self._update_view()
            elif selected_choice == self.REMOVE_LABEL:
                role_titles = [
                    ("primary", "Primario"),
                    ("timeout", "Fallback timeout"),
                    ("rate_limit", "Fallback rate-limit"),
                    ("safety", "Fallback safety"),
                    ("auth", "Fallback auth"),
                    ("generic", "Fallback generico"),
                ]
                phase_map = self.pending_selections[group_label]
                occupied_roles = [(rk, f"{rt}: {phase_map[rk]}") for rk, rt in role_titles if phase_map.get(rk)]
                if occupied_roles:
                    def _ask_remove() -> Optional[str]:
                        try:
                            return questionary.select(
                                f"Quale assegnazione vuoi rimuovere per la fase '{group_label}'?",
                                choices=[lbl for _, lbl in occupied_roles] + ["❌ Annulla"],
                                default=occupied_roles[0][1]
                            ).ask()
                        except (EOFError, Exception):
                            return None
                    with self._safe_suspend():
                        del_choice = _run_in_thread(_ask_remove)
                    if del_choice and del_choice != "❌ Annulla":
                        for rk, lbl in occupied_roles:
                            if lbl == del_choice:
                                self.pending_selections[group_label][rk] = None
                                print(f"✅ Rimossa assegnazione {rk} per '{group_label}'.")
                                break
                self._update_view()
            elif selected_choice == self.NEW_PROFILE:
                with self._safe_suspend():
                    res_create = _run_in_thread(
                        _create_new_model_profile,
                        self.config_dir,
                        self.env_path,
                        self.general_data,
                        ask_role=True,
                        group_label=group_label,
                        current_phase_assignments=self.pending_selections[group_label],
                    )
                p_name = ""
                p_dict: Dict[str, Any] = {}
                p_role: Optional[str] = None
                if isinstance(res_create, tuple):
                    if len(res_create) == 3:
                        p_name, p_dict, p_role = res_create
                    elif len(res_create) == 2:
                        p_name, p_dict = res_create
                if p_name:
                    self.profiles[p_name] = p_dict
                    _save_model_profiles(self.general_data, self.profiles)
                    if p_role:
                        self.pending_selections[group_label][p_role] = p_name
                    elif p_role is None and isinstance(res_create, tuple) and len(res_create) == 2:
                        with self._safe_suspend():
                            _run_in_thread(_ask_and_assign_role, p_name, group_label, self.pending_selections[group_label])
                self._update_view()
            else:
                with self._safe_suspend():
                    _run_in_thread(_ask_and_assign_role, selected_choice, group_label, self.pending_selections[group_label])
                self._update_view()


def _build_configure_roles_app(config_dir: str, env_path: str) -> Optional[ConfigurePhaseRolesApp]:
    """Costruisce e restituisce l'istanza di ConfigurePhaseRolesApp per config_dir ed env_path, o None se nessun job trovato."""
    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
        except Exception:
            pass

    profiles = _load_model_profiles(general_data)

    job_paths = find_job_yaml_paths(config_dir)
    known_jobs: Set[str] = set()
    grouped_jobs: List[Tuple[str, List[str]]] = []
    for label, group_j_names in _JOB_GROUPS:
        # I cinque file storici restano leggibili nelle installazioni aggiornate.
        # Quando esiste il nuovo recall.yaml, il wizard mostra solo la route unica.
        present = (["recall"] if label == "recall" and "recall" in job_paths
                   else [jn for jn in group_j_names if jn in job_paths])
        if label == "recall" and "recall" in job_paths:
            known_jobs.update(jn for jn in group_j_names if jn in job_paths)
        if present:
            grouped_jobs.append((label, present))
            known_jobs.update(present)

    for jn in sorted(job_paths.keys()):
        if jn not in known_jobs:
            grouped_jobs.append((jn, [jn]))

    if not grouped_jobs:
        return None

    keep_label = "🔧 Mantieni configurazione attuale (non riconosciuta come profilo salvato)"

    pending_selections: Dict[str, Dict[str, Optional[str]]] = {}
    group_info: Dict[str, Tuple[List[str], bool, Optional[str]]] = {}

    for group_label, group_jobs in grouped_jobs:
        first_job_name = group_jobs[0]
        first_job_file = job_paths[first_job_name]
        job_data: Dict[str, Any] = {}
        if os.path.isfile(first_job_file):
            try:
                with open(first_job_file, "r", encoding="utf-8") as f:
                    loaded_job = yaml.safe_load(f)
                    if isinstance(loaded_job, dict):
                        job_data = loaded_job
            except Exception:
                pass

        current_match = _find_matching_profile(job_data, profiles)
        has_unrecognized = (current_match is None and _job_has_real_config(job_data))
        group_info[group_label] = (group_jobs, has_unrecognized, current_match)

        phase_map: Dict[str, Optional[str]] = {
            "primary": None,
            "timeout": None,
            "rate_limit": None,
            "safety": None,
            "auth": None,
            "generic": None,
        }

        if current_match:
            phase_map["primary"] = current_match
        elif has_unrecognized:
            phase_map["primary"] = keep_label

        fb_data = job_data.get("fallback")
        if isinstance(fb_data, dict):
            for slot in ("timeout", "rate_limit", "safety", "auth", "generic"):
                if slot in fb_data and isinstance(fb_data[slot], dict):
                    fb_match = _find_matching_profile_for_single_route(fb_data[slot], profiles)
                    phase_map[slot] = fb_match

        pending_selections[group_label] = phase_map

    return ConfigurePhaseRolesApp(
        config_dir=config_dir,
        env_path=env_path,
        general_data=general_data,
        general_yaml_path=general_yaml_path,
        profiles=profiles,
        job_paths=job_paths,
        grouped_jobs=grouped_jobs,
        group_info=group_info,
        pending_selections=pending_selections,
    )


def _configure_llm_provider_section(config_dir: str, env_path: str) -> Dict[str, str]:
    """
    Guida l'utente nella configurazione dei profili modello LLM per ciascuna fase della pipeline
    attraverso un carosello di card testuali navigabili (LEFT/RIGHT, UP/DOWN) e conferma finale.
    Restituisce una mappa {job_name: profile_name_o_descrizione}.
    """
    print("\n------------------------------------------------------------")
    print("🤖 Configurazione Provider LLM per ciascuna fase")
    print("------------------------------------------------------------")
    print("Ora configuriamo il modello LLM da usare per ciascuna fase della pipeline.")
    print("Nota: solo il ruolo 'Primario' è obbligatorio, i 5 ruoli di 'Fallback' sono tutti facoltativi/opzionali.")
    print("Usa le frecce SINISTRA/DESTRA per spostarti tra le card di ciascuna fase.")
    print("Le modifiche verranno salvate su disco SOLO dopo la conferma finale.\n")

    app = _build_configure_roles_app(config_dir, env_path)
    if not app:
        print("⚠️ Nessun file job YAML trovato per la configurazione dei modelli.")
        return {}

    app.run()

    if app.result_assignments is not None:
        print(f"\n✅ Assegnazione modelli completata per {len(app.result_assignments)} job!")
        return app.result_assignments
    else:
        print("Configurazione LLM interrotta dall'utente.")
        return {}




def _configure_telegram_section(config_dir: str, env_path: str) -> Dict[str, Any]:
    """
    Guida l'utente nella configurazione di Telegram (Bot Token, Chat ID, discovery live/link topic, lessons_root).
    Restituisce un dizionario con l'esito della configurazione.
    """
    print("\n------------------------------------------------------------")
    print("✈️  Configurazione Telegram (Notifiche e Topic per Materia)")
    print("------------------------------------------------------------")

    confirm = questionary.confirm("Configurare Telegram ora?", default=True).ask()
    if not confirm:
        print("⏭  Sezione Telegram saltata.")
        return {"configured": False}

    # 1. Bot Token
    existing_token = os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")
    if _is_placeholder_or_invalid_bot_token(existing_token):
        existing_token = ""
    bot_token = ""
    if existing_token:
        masked = existing_token[:6] + "..." if len(existing_token) > 6 else existing_token
        change = questionary.confirm(f"Bot token Telegram già presente ({masked}). Vuoi modificarlo?", default=False).ask()
        if not change:
            bot_token = existing_token

    if not bot_token:
        print("\nℹ️  Per creare un bot Telegram:")
        print("   1. Apri Telegram e cerca @BotFather")
        print("   2. Invia /newbot e segui le istruzioni per ottenere il Bot Token")
        token_input = questionary.password("Bot Token Telegram:").ask()
        if not token_input or not token_input.strip():
            print("⚠️  Bot token non inserito, sezione Telegram interrotta.")
            return {"configured": False}
        bot_token = token_input.strip()
        _update_env_file(env_path, "RT_TELEGRAM_BOT_TOKEN", bot_token)

    # 2. Discovery Gruppo / Topic
    mode = questionary.select(
        "Come vuoi configurare gruppo e topic Telegram?",
        choices=[
            "📡 Discovery live (manda un messaggio nel gruppo/topic dal telefono)",
            "🔗 Incolla link topic (manuale)",
            "⏭ Salta questa parte"
        ]
    ).ask()

    detected_chat_id: Optional[int] = None
    topics_map: Dict[str, int] = {}
    misc_topic_id: Optional[int] = None

    while mode and mode.startswith("📡"):
        print("\n--- 📡 Discovery Live Topic ---")
        print("ISTRUZIONI:")
        print("1. Assicurati che il bot sia stato aggiunto al tuo gruppo Telegram.")
        print("2. Assicurati che il bot sia Amministratore o che Group Privacy sia disattivata (@BotFather -> /mybots -> Bot Settings -> Group Privacy -> Turn off).")
        print("3. Invia ORA dal tuo telefono un messaggio in ciascun topic che vuoi mappare.")

        last_offset = 0
        mapped_threads = set()
        stop_discovery = False

        print("\nListening per messaggi Telegram per al massimo 3 minuti (Ctrl+C per terminare prima)...")
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                if stop_discovery:
                    break
                try:
                    resp = requests.get(
                        f"https://api.telegram.org/bot{bot_token}/getUpdates",
                        params={"offset": last_offset, "timeout": 15},
                        timeout=20
                    )
                    if resp.status_code == 409:
                        print("⚠️  Conflitto 409: sembra che 'rt telegram-daemon' sia già attivo per questo bot. Fermalo prima di proseguire.")
                        break
                    elif resp.status_code == 200:
                        data = resp.json()
                        if data.get("ok") and isinstance(data.get("result"), list):
                            for update in data["result"]:
                                last_offset = max(last_offset, update.get("update_id", 0) + 1)
                                msg = update.get("message") or update.get("channel_post")
                                if not msg or not isinstance(msg, dict):
                                    continue
                                chat = msg.get("chat", {})
                                chat_id = chat.get("id")
                                if not chat_id:
                                    continue

                                if detected_chat_id is None:
                                    detected_chat_id = chat_id
                                    chat_title = chat.get("title", f"Chat {chat_id}")
                                    print(f"\n📌 Gruppo rilevato: {chat_title} (ID: {chat_id})")
                                elif chat_id != detected_chat_id:
                                    print(f"⚠️  Messaggio ignorato da un altro chat ({chat_id})")
                                    continue

                                thread_id = msg.get("message_thread_id")
                                if thread_id in mapped_threads:
                                    continue
                                mapped_threads.add(thread_id)

                                snippet = str(msg.get("text", "")).strip()[:30]
                                topic_label = f"Topic ID {thread_id}" if thread_id is not None else "Topic 'Generale' (radice)"
                                print(f"\n📩 Nuovo messaggio rilevato in {topic_label}: '{snippet}'")

                                mat = questionary.text(
                                    f"Materia per {topic_label} (o 'varie' per Generale/Varie, invio per saltare):"
                                ).ask()
                                if mat and mat.strip():
                                    mat_clean = mat.strip().upper()
                                    if mat_clean in ("VARIE", "GENERALE") or thread_id is None:
                                        if thread_id is not None:
                                            misc_topic_id = thread_id
                                    else:
                                        topics_map[mat_clean] = thread_id

                                cont = questionary.confirm("Continuare l'ascolto per altri topic?", default=True).ask()
                                if not cont:
                                    stop_discovery = True
                                    break
                except Exception:
                    pass
        except KeyboardInterrupt:
            print("\nPolling interrotto dall'utente.")

        if not topics_map and not detected_chat_id:
            print("\n⚠️  Nessun messaggio rilevato via discovery live.")
            print("Verifica che il bot sia nel gruppo e che abbia i permessi di lettura messaggi.")
            disc_action = questionary.select(
                "Come vuoi procedere?",
                choices=[
                    "🔄 Riprova discovery live",
                    "🔗 Passa all'inserimento manuale via link",
                    "⏭ Annulla/salta questa parte"
                ]
            ).ask()
            if disc_action and disc_action.startswith("🔄"):
                continue
            elif disc_action and disc_action.startswith("🔗"):
                mode = "🔗 Incolla link topic (manuale)"
                break
            else:
                mode = "⏭ Salta questa parte"
                break
        else:
            break

    if mode and mode.startswith("🔗"):
        print("\n--- 🔗 Inserimento Manuale via Link Topic ---")
        while True:
            link = questionary.text(
                "Incolla il link a un messaggio del topic (es. https://t.me/c/1234567890/12/34) [invio per terminare]:"
            ).ask()
            if not link or not link.strip():
                break
            parsed = parse_telegram_topic_link(link)
            if not parsed:
                print("❌ Formato link non valido. Esempio atteso: https://t.me/c/1234567890/12/34")
                continue

            chat_id, topic_id = parsed
            detected_chat_id = chat_id
            print(f"✔ Rilevato Chat ID: {chat_id}, Topic ID: {topic_id}")
            mat = questionary.text(f"Materia per Topic ID {topic_id}:").ask()
            if mat and mat.strip():
                mat_clean = mat.strip().upper()
                if mat_clean in ("VARIE", "GENERALE"):
                    misc_topic_id = topic_id
                else:
                    topics_map[mat_clean] = topic_id

    # Aggiorna .env con RT_TELEGRAM_CHAT_ID se rilevato
    if detected_chat_id:
        _update_env_file(env_path, "RT_TELEGRAM_CHAT_ID", str(detected_chat_id))

    # Aggiorna config/general.yaml
    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
        except Exception:
            pass

    if "telegram" not in general_data or not isinstance(general_data["telegram"], dict):
        general_data["telegram"] = {}

    existing_topics = general_data["telegram"].get("topics", {})
    if not isinstance(existing_topics, dict):
        existing_topics = {}

    existing_topics.update(topics_map)
    general_data["telegram"]["topics"] = existing_topics
    if misc_topic_id is not None:
        general_data["telegram"]["misc_topic_id"] = misc_topic_id

    # lessons_root
    curr_lessons_root = general_data["telegram"].get("lessons_root") or ""
    lessons_root_in = questionary.text(
        "Percorso assoluto cartella lezioni (puoi anche trascinarla qui):",
        default=curr_lessons_root
    ).ask()

    if lessons_root_in is not None:
        clean_root = clean_input_path(lessons_root_in)
        if clean_root and not os.path.isdir(clean_root):
            print(f"⚠️  Avviso: la cartella '{clean_root}' non esiste attualmente su questo sistema.")
        if clean_root:
            general_data["telegram"]["lessons_root"] = clean_root

    _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))

    print("\n✅ Configurazione Telegram salvata in config/general.yaml e .env!")
    if detected_chat_id:
        print(f"   Chat ID: {detected_chat_id}")
    if existing_topics:
        print(f"   Topics mappati ({len(existing_topics)}): {existing_topics}")
    if misc_topic_id:
        print(f"   Topic Varie (misc_topic_id): {misc_topic_id}")

    return {
        "configured": True,
        "chat_id": detected_chat_id,
        "topics_count": len(existing_topics)
    }


def _configure_stt_section(config_dir: str) -> str:
    """
    Guida l'utente nella configurazione del motore STT per l'active recall vocale.
    """
    print("\n------------------------------------------------------------")
    print("🎙️  Configurazione Motore STT (Active Recall Vocale)")
    print("------------------------------------------------------------")

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    curr_stt = "macparakeet"

    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
                    curr_stt = general_data.get("telegram", {}).get("recall", {}).get("stt_engine", "macparakeet")
        except Exception:
            pass

    allowed_stt = ["macparakeet", "api"]
    default_stt = curr_stt if curr_stt in allowed_stt else "macparakeet"

    stt_choice = ""
    while not stt_choice:
        choice = questionary.select(
            "Motore STT per trascrizione risposte vocali (active recall):",
            choices=allowed_stt,
            default=default_stt
        ).ask()

        if choice is None:
            print("Operazione annullata dall'utente.")
            return default_stt

        if choice == "api":
            print("⚠️  Il motore 'api' non è ancora implementato in RT (solleverà NotImplementedError durante il recall vocale).")
            confirm = questionary.confirm("Vuoi impostare comunque 'api'?", default=False).ask()
            if confirm:
                stt_choice = "api"
        else:
            stt_choice = choice

    if "telegram" not in general_data or not isinstance(general_data["telegram"], dict):
        general_data["telegram"] = {}
    if "recall" not in general_data["telegram"] or not isinstance(general_data["telegram"]["recall"], dict):
        general_data["telegram"]["recall"] = {}

    general_data["telegram"]["recall"]["stt_engine"] = stt_choice
    _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))

    print(f"✅ Motore STT impostato su: '{stt_choice}'")
    return stt_choice


def _configure_pricing_section(
    config_dir: str,
    provider: Optional[str],
    model: Optional[str],
    detected_pricing: Optional[Dict[str, float]] = None
) -> Optional[Dict[str, Any]]:
    """
    Guida l'utente nella configurazione opzionale di un listino prezzi custom in config/general.yaml.
    Se detected_pricing è presente, mostra i valori rilevati e chiede se modificarli (default: No/salva diretto).
    """
    if detected_pricing and "input_per_million" in detected_pricing and "output_per_million" in detected_pricing:
        det_in = detected_pricing["input_per_million"]
        det_out = detected_pricing["output_per_million"]
        modify_confirm = questionary.confirm(
            f"Costo rilevato per milione di token: input ${det_in:.2f}; output ${det_out:.2f}. Vuoi modificarlo?",
            default=False
        ).ask()

        if modify_confirm is None:
            return None

        if not modify_confirm:
            if not provider or not model:
                return None
            provider = provider.strip()
            model = model.strip()
            general_yaml_path = os.path.join(config_dir, "general.yaml")
            general_data: Dict[str, Any] = {}
            if os.path.isfile(general_yaml_path):
                try:
                    with open(general_yaml_path, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                        if isinstance(loaded, dict):
                            general_data = loaded
                except Exception:
                    pass

            pricing_map = general_data.get("pricing")
            if not isinstance(pricing_map, dict):
                pricing_map = {}
            if provider not in pricing_map or not isinstance(pricing_map[provider], dict):
                pricing_map[provider] = {}

            p_item: Dict[str, Any] = {
                "input_per_million": det_in,
                "output_per_million": det_out,
            }
            pricing_map[provider][model] = p_item
            general_data["pricing"] = pricing_map
            _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
            print(f"✅ Pricing salvato per {provider}/{model}: input=${det_in:.2f}/1M, output=${det_out:.2f}/1M")
            return {"provider": provider, "model": model, "pricing": p_item}

        default_in_str = str(det_in)
        default_out_str = str(det_out)
    else:
        confirm = questionary.confirm(
            "Vuoi configurare un listino prezzi custom per questo modello? (opzionale, RT ha già stime interne)",
            default=False
        ).ask()

        if not confirm:
            print("⏭  Sezione Pricing custom saltata.")
            return None
        default_in_str = ""
        default_out_str = ""

    if not provider:
        p_in = questionary.text("Nome provider per pricing (es. deepseek):").ask()
        provider = p_in.strip() if p_in else None
    if not model:
        m_in = questionary.text("Nome modello per pricing (es. deepseek-chat):").ask()
        model = m_in.strip() if m_in else None

    if not provider or not model:
        print("⚠️  Provider o modello mancante, sezione pricing saltata.")
        return None

    provider = provider.strip()
    model = model.strip()

    kwargs_in: Dict[str, Any] = {"validate": lambda v: _is_valid_float(v) or "Inserisci un numero valido >= 0"}
    if default_in_str:
        kwargs_in["default"] = default_in_str
    inp_str = questionary.text("Costo Input per 1M token in USD (es. 0.14):", **kwargs_in).ask()

    if inp_str is None:
        return None

    kwargs_out: Dict[str, Any] = {"validate": lambda v: _is_valid_float(v) or "Inserisci un numero valido >= 0"}
    if default_out_str:
        kwargs_out["default"] = default_out_str
    out_str = questionary.text("Costo Output per 1M token in USD (es. 0.28):", **kwargs_out).ask()

    if out_str is None:
        return None

    reasoning_cost: Optional[float] = None
    has_reasoning = questionary.confirm(
        "Il modello ha un costo di reasoning separato dall'output?",
        default=False
    ).ask()

    if has_reasoning:
        reas_str = questionary.text(
            "Costo Reasoning per 1M token in USD (es. 0.55):",
            validate=lambda v: _is_valid_float(v) or "Inserisci un numero valido >= 0"
        ).ask()
        if reas_str and reas_str.strip():
            reasoning_cost = float(reas_str.strip())

    inp_val = float(inp_str.strip())
    out_val = float(out_str.strip())

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
        except Exception:
            pass

    pricing_map = general_data.get("pricing")
    if not isinstance(pricing_map, dict):
        pricing_map = {}

    if provider not in pricing_map or not isinstance(pricing_map[provider], dict):
        pricing_map[provider] = {}

    p_item: Dict[str, Any] = {
        "input_per_million": inp_val,
        "output_per_million": out_val,
    }
    if reasoning_cost is not None:
        p_item["reasoning_per_million"] = reasoning_cost

    pricing_map[provider][model] = p_item
    general_data["pricing"] = pricing_map

    _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))

    print(f"✅ Pricing custom salvato per {provider}/{model}: input=${inp_val}/1M, output=${out_val}/1M")
    return {"provider": provider, "model": model, "pricing": p_item}


def run_config_wizard(interactive: bool = True) -> None:
    """Esegue il wizard interattivo rt config."""
    print("================================================------------")
    print("⚙️  RT CONFIG — Wizard di configurazione guidata")
    print("================================================------------")

    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    if interactive:
        _maybe_prompt_theme_first_time(config_dir)
    job_profiles = _configure_llm_provider_section(config_dir, env_path)
    tg_res = _configure_telegram_section(config_dir, env_path)
    stt_engine = _configure_stt_section(config_dir)

    print("\n================================================------------")
    print("✅ Configurazione completata.")
    print("\nRiepilogo:")
    print("Modelli assegnati:")
    if job_profiles:
        general_yaml_path = os.path.join(config_dir, "general.yaml")
        general_data_summary: Dict[str, Any] = {}
        if os.path.isfile(general_yaml_path):
            try:
                with open(general_yaml_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        general_data_summary = loaded
            except Exception:
                pass
        profiles_summary = _load_model_profiles(general_data_summary)
        for j_name, p_name in sorted(job_profiles.items()):
            print(f"- {j_name}: {_format_profile_display(p_name, profiles_summary)}")
    else:
        print("- (nessun job aggiornato)")

    if tg_res and tg_res.get("configured"):
        t_cnt = tg_res.get("topics_count", 0)
        print(f"- Telegram:       configurato ({t_cnt} topic mappati)")
    else:
        print("- Telegram:       non configurato")

    print(f"- Motore STT:     {stt_engine}")

    print("\nProssimi passi:")
    print("1. Verifica la configurazione con: ./bin/rt status <una_lezione_di_prova>")
    print("2. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock")
    print("3. Puoi rilanciare 'rt config' in qualsiasi momento per modificare una singola sezione.")
    print("================================================------------\n")


def run_telegram_only() -> None:
    """Configura direttamente solo la sezione Telegram."""
    print("================================================------------")
    print("⚙️  RT CONFIG — Configurazione Telegram")
    print("================================================------------")
    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    _configure_telegram_section(config_dir, env_path)


def _edit_model_profile(
    config_dir: str,
    env_path: str,
    general_yaml_path: str,
    general_data: Dict[str, Any],
    profiles: Dict[str, Dict[str, Any]],
    profile_name: str
) -> None:
    """Permette di modificare o eliminare un singolo profilo modello."""
    prof_dict = profiles.get(profile_name)
    if not prof_dict:
        return

    provider = prof_dict.get("provider", "")
    base_url = prof_dict.get("base_url")
    is_rr = prof_dict.get("round_robin", False)
    routes = prof_dict.get("routes", [])
    model_name = routes[0].get("model", "") if routes else ""

    print(f"\n--- Profilo: '{profile_name}' ---")
    print(f"Provider: {provider}")
    if base_url:
        print(f"Base URL: {base_url}")
    print(f"Modello:  {model_name}")
    print(f"Modalità: {'Round-Robin (' + str(len(routes)) + ' chiavi)' if is_rr else 'Singola chiave (' + (routes[0].get('credential', '') if routes else '') + ')'}")

    pricing_data = general_data.get("pricing", {}).get(provider, {}).get(model_name)
    if pricing_data and isinstance(pricing_data, dict):
        inp = pricing_data.get("input_per_million")
        outp = pricing_data.get("output_per_million")
        print(f"Pricing:  Input=${inp}/1M, Output=${outp}/1M")

    while True:
        action = questionary.select(
            f"Operazione su profilo '{profile_name}':",
            choices=[
                "✏️ Rinomina profilo",
                "🔧 Cambia provider/base URL/modello (riconfigura da capo questo profilo)",
                "🔑 Aggiorna API key",
                "💰 Modifica pricing",
                "🗑️ Elimina profilo",
                "⏭ Torna alla lista"
            ]
        ).ask()

        if not action or action.startswith("⏭"):
            break

        if action.startswith("✏️"):
            new_name_in = questionary.text("Nuovo nome per questo profilo:", default=profile_name).ask()
            if not new_name_in or not new_name_in.strip():
                continue
            new_name = new_name_in.strip()
            if new_name == profile_name:
                continue
            if new_name in profiles:
                print(f"⚠️ Il profilo '{new_name}' esiste già.")
                continue
            profiles[new_name] = profiles.pop(profile_name)
            _save_model_profiles(general_data, profiles)
            _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
            print(f"✅ Profilo rinominato da '{profile_name}' a '{new_name}'.")
            profile_name = new_name

        elif action.startswith("🔧"):
            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint=profile_name)
            if p_name:
                if p_name != profile_name and profile_name in profiles:
                    profiles.pop(profile_name)
                profiles[p_name] = p_dict
                _save_model_profiles(general_data, profiles)
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
                print(f"✅ Profilo '{p_name}' aggiornato.")
                break

        elif action.startswith("🔑"):
            if not routes:
                print("⚠️ Nessuna credenziale associata a questo profilo.")
                continue
            for r in routes:
                cred_name = r.get("credential", "")
                env_var = None
                for c in general_data.get("credentials", []):
                    if isinstance(c, dict) and c.get("name") == cred_name:
                        env_var = c.get("env_var")
                        break
                if not env_var:
                    env_var = f"{provider.upper()}_API_KEY"

                curr_val = os.environ.get(env_var, "")
                new_key = questionary.password(
                    f"Nuova API key per {cred_name} ({env_var}):",
                    default=curr_val
                ).ask()
                if new_key and new_key.strip():
                    _update_env_file(env_path, env_var, new_key.strip())
                    os.environ[env_var] = new_key.strip()
                    print(f"✅ API key per {env_var} aggiornata.")

        elif action.startswith("💰"):
            _configure_pricing_section(config_dir, provider, model_name)
            if os.path.isfile(general_yaml_path):
                try:
                    with open(general_yaml_path, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                        if isinstance(loaded, dict):
                            general_data.update(loaded)
                except Exception:
                    pass

        elif action.startswith("🗑️"):
            print(f"⚠️ Attenzione: eliminando il profilo '{profile_name}', i file YAML dei job rimarranno invariati")
            print("ma al prossimo 'rt config' non verranno più riconosciuti come profilo salvato.")
            confirm_del = questionary.confirm(f"Sei sicuro di voler eliminare il profilo '{profile_name}'?", default=False).ask()
            if confirm_del:
                profiles.pop(profile_name, None)
                _save_model_profiles(general_data, profiles)
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
                print(f"✅ Profilo '{profile_name}' eliminato.")
                break


def run_models_management() -> None:
    """Apre il menu di gestione dei profili modello salvati in config/general.yaml."""
    print("================================================------------")
    print("⚙️  RT CONFIG — Gestione Profili Modello")
    print("================================================------------")
    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    general_yaml_path = os.path.join(config_dir, "general.yaml")

    while True:
        general_data: Dict[str, Any] = {}
        if os.path.isfile(general_yaml_path):
            try:
                with open(general_yaml_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        general_data = loaded
            except Exception:
                pass

        profiles = _load_model_profiles(general_data)
        if not profiles:
            print("Nessun profilo modello salvato. Usa 'rt config' per crearne uno.")
            return

        EXIT = "⏭ Esci"
        NEW = "➕ Crea un nuovo profilo"
        choices = sorted(profiles.keys()) + [NEW, EXIT]
        choice = questionary.select(
            "Profili modello salvati (seleziona per modificare):",
            choices=choices
        ).ask()

        if choice is None or choice == EXIT:
            return

        if choice == NEW:
            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data)
            if p_name:
                profiles[p_name] = p_dict
                _save_model_profiles(general_data, profiles)
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
            continue

        _edit_model_profile(config_dir, env_path, general_yaml_path, general_data, profiles, choice)


def _edit_single_topic_mapping(
    general_yaml_path: str,
    general_data: Dict[str, Any],
    topics_map: Dict[str, Any],
    mat_name: str
) -> None:
    curr_val = topics_map.get(mat_name)
    print(f"\n--- Gestione Topic per materia: '{mat_name}' ---")
    if isinstance(curr_val, dict):
        print(f"Chat ID: {curr_val.get('chat_id')}, Topic ID: {curr_val.get('message_thread_id')}")
    else:
        print(f"Topic ID: {curr_val}")

    action = questionary.select(
        f"Operazione su materia '{mat_name}':",
        choices=[
            "✏️ Rinomina materia",
            "🔧 Modifica chat_id / topic_id",
            "🗑️ Rimuovi mappatura",
            "⏭ Torna alla lista"
        ]
    ).ask()

    if not action or action.startswith("⏭"):
        return

    if action.startswith("✏️"):
        new_mat = questionary.text("Nuovo nome materia (in maiuscolo):", default=mat_name).ask()
        if not new_mat or not new_mat.strip():
            return
        new_mat_clean = new_mat.strip().upper()
        if new_mat_clean == mat_name:
            return
        if new_mat_clean in topics_map:
            print(f"⚠️ La materia '{new_mat_clean}' ha già una mappatura topic.")
            return
        val = topics_map.pop(mat_name)
        topics_map[new_mat_clean] = val
        general_data["telegram"]["topics"] = topics_map
        _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
        print(f"✅ Materia rinominata da '{mat_name}' a '{new_mat_clean}'.")

    elif action.startswith("🔧"):
        # RT supporta un solo gruppo Telegram per bot (chat_id globale in RT_TELEGRAM_BOT_TOKEN/
        # RT_TELEGRAM_CHAT_ID) — 'topics' mappa solo materia -> message_thread_id (int), MAI un
        # chat_id per-topic: lo schema Pydantic (TelegramRuntimeConfig.topics: Dict[str, int])
        # non lo supporta e farebbe fallire la validazione all'avvio di qualunque comando 'rt'.
        t_id_def = str(curr_val.get("message_thread_id", "")) if isinstance(curr_val, dict) else str(curr_val or "")
        new_tid = questionary.text("Topic ID:", default=t_id_def).ask()

        if new_tid and new_tid.strip():
            try:
                tid_int = int(new_tid.strip())
                topics_map[mat_name] = tid_int
                general_data["telegram"]["topics"] = topics_map
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
                print(f"✅ Mappatura '{mat_name}' aggiornata: topic_id={tid_int}.")
            except ValueError:
                print("❌ Il Topic ID deve essere un numero intero.")

    elif action.startswith("🗑️"):
        confirm_del = questionary.confirm(f"Sei sicuro di voler rimuovere la mappatura per '{mat_name}'?", default=False).ask()
        if confirm_del:
            topics_map.pop(mat_name, None)
            general_data["telegram"]["topics"] = topics_map
            _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
            print(f"✅ Mappatura '{mat_name}' rimossa.")


def run_topics_management() -> None:
    """Apre il menu di gestione delle mappature materia -> topic Telegram in config/general.yaml."""
    print("================================================------------")
    print("⚙️  RT CONFIG — Gestione Topic Telegram")
    print("================================================------------")
    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    general_yaml_path = os.path.join(config_dir, "general.yaml")

    while True:
        general_data: Dict[str, Any] = {}
        if os.path.isfile(general_yaml_path):
            try:
                with open(general_yaml_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        general_data = loaded
            except Exception:
                pass

        if "telegram" not in general_data or not isinstance(general_data["telegram"], dict):
            general_data["telegram"] = {}

        topics_map = general_data["telegram"].get("topics", {})
        if not isinstance(topics_map, dict):
            topics_map = {}

        print("\n--- Mappature Materie <-> Topic Telegram Attuali ---")
        if not topics_map:
            print("  (Nessuna mappatura topic configurata)")
        else:
            for mat, val in sorted(topics_map.items()):
                if isinstance(val, dict):
                    cid = val.get("chat_id")
                    tid = val.get("message_thread_id")
                    print(f"  • {mat} -> chat_id: {cid}, topic_id: {tid}")
                else:
                    print(f"  • {mat} -> topic_id: {val}")

        EXIT = "⏭ Esci"
        ADD = "➕ Aggiungi nuova mappatura topic"
        choices = [f"✏️ Gestisci '{m}'" for m in sorted(topics_map.keys())] + [ADD, EXIT]

        action = questionary.select(
            "Seleziona un'operazione:",
            choices=choices
        ).ask()

        if action is None or action == EXIT:
            break

        if action == ADD:
            bot_token = os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")
            if _is_placeholder_or_invalid_bot_token(bot_token):
                print("⚠️ Bot Token Telegram non configurato. Esegui prima 'rt config --telegram'.")
                continue

            link = questionary.text(
                "Incolla il link a un messaggio del topic (es. https://t.me/c/1234567890/12/34):"
            ).ask()
            if not link or not link.strip():
                continue
            parsed = parse_telegram_topic_link(link)
            if not parsed:
                print("❌ Formato link non valido. Esempio atteso: https://t.me/c/1234567890/12/34")
                continue
            chat_id, topic_id = parsed
            configured_chat_id = os.environ.get("RT_TELEGRAM_CHAT_ID", "")
            if configured_chat_id and configured_chat_id.strip() and str(chat_id) != configured_chat_id.strip():
                print(
                    f"⚠️  Questo link appartiene a un gruppo Telegram diverso da quello configurato "
                    f"(chat_id {chat_id} vs {configured_chat_id}). RT supporta un solo gruppo Telegram "
                    f"per bot: questo topic non può essere aggiunto perché appartiene a un gruppo diverso."
                )
                continue
            mat = questionary.text(f"Materia per Topic ID {topic_id}:").ask()
            if mat and mat.strip():
                mat_clean = mat.strip().upper()
                topics_map[mat_clean] = topic_id
                general_data["telegram"]["topics"] = topics_map
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
                print(f"✅ Mappatura '{mat_clean}' aggiunta.")
            continue

        mat_name = action.replace("✏️ Gestisci '", "")[:-1]
        _edit_single_topic_mapping(general_yaml_path, general_data, topics_map, mat_name)


def run_theme_selection(config_dir: Optional[str] = None) -> Optional[str]:
    """Configura direttamente il tema dell'interfaccia (scuro/chiaro) e salva in general.yaml."""
    if config_dir is None:
        config_dir, _ = _resolve_or_bootstrap_config_paths()

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
        except Exception:
            pass

    ui_data = general_data.get("ui")
    curr_theme = "dark"
    if isinstance(ui_data, dict):
        curr_theme = ui_data.get("theme", "dark")

    default_choice = "🌕 Chiaro" if curr_theme == "light" else "🌑 Scuro"

    print("\n------------------------------------------------------------")
    print("🎨 Configurazione Tema Interfaccia Terminale")
    print("------------------------------------------------------------")

    try:
        choice = questionary.select(
            "Il tuo terminale ha uno sfondo scuro o chiaro?",
            choices=[
                "🌑 Scuro",
                "🌕 Chiaro",
            ],
            default=default_choice,
        ).ask()
    except Exception:
        choice = None

    if choice is None:
        print("Operazione annullata.")
        return None

    selected_theme = "light" if "Chiaro" in choice else "dark"

    if "ui" not in general_data or not isinstance(general_data["ui"], dict):
        general_data["ui"] = {}
    general_data["ui"]["theme"] = selected_theme

    _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
    label = "Chiaro" if selected_theme == "light" else "Scuro"
    print(f"\n✅ Tema impostato su: {label} (salvato in config/general.yaml)")
    return selected_theme


def _maybe_prompt_theme_first_time(config_dir: str) -> None:
    """Propone la scelta del tema durante la prima esecuzione del wizard se non ancora configurato."""
    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data: Dict[str, Any] = {}
    if os.path.isfile(general_yaml_path):
        try:
            with open(general_yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    general_data = loaded
        except Exception:
            pass
    ui_dict = general_data.get("ui")
    if isinstance(ui_dict, dict) and "theme" in ui_dict and ui_dict["theme"] in ("dark", "light"):
        return
    res = run_theme_selection(config_dir=config_dir)
    if res is None and os.path.isfile(general_yaml_path):
        if "ui" not in general_data or not isinstance(general_data["ui"], dict):
            general_data["ui"] = {}
        if "theme" not in general_data["ui"]:
            general_data["ui"]["theme"] = "dark"
            _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))


def configure_config_parser(parser: Any) -> Any:
    """Configura l'argparse parser per rt config."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--models", action="store_true", help="Apre direttamente il menu di gestione dei profili modello salvati (senza attraversare l'intero wizard)")
    group.add_argument("--telegram", action="store_true", help="Configura direttamente solo la sezione Telegram (senza attraversare l'intero wizard)")
    group.add_argument("--topics", action="store_true", help="Apre direttamente il menu di gestione dei topic Telegram già configurati (senza attraversare l'intero wizard)")
    group.add_argument("--theme", action="store_true", help="Configura direttamente il tema dell'interfaccia terminale (scuro/chiaro)")
    return parser
