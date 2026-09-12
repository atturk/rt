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
from typing import Dict, Any, List, Optional, Tuple, Iterable, Set
import yaml
import requests
import questionary

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths, _default_project_root


def parse_telegram_topic_link(link: str) -> Optional[Tuple[int, int]]:
    """
    Parsa un link a un messaggio Telegram di un supergruppo/forum (es. 'https://t.me/c/4490473926/541/679')
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


def _suggest_profile_name(provider: str, model: str, existing_names: Iterable[str]) -> str:
    """
    Suggerisce un nome di profilo univoco sanitizzato (es. provider_model).
    Se esiste già in existing_names, aggiunge _2, _3, ecc.
    """
    existing_set = set(existing_names) if existing_names else set()
    raw = f"{provider}_{model}".lower()
    sanitized = re.sub(r"[^a-z0-9_]+", "_", raw)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "profilo"

    if sanitized not in existing_set:
        return sanitized

    idx = 2
    while f"{sanitized}_{idx}" in existing_set:
        idx += 1
    return f"{sanitized}_{idx}"


def _create_new_model_profile(
    config_dir: str,
    env_path: str,
    general_data: Dict[str, Any],
    default_name_hint: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Contiene la logica interattiva per raccogliere provider, base_url, chiavi (singola o round-robin),
    recupero modelli, pricing inline, e salvataggio credenziali, chiedendo un nome per il nuovo profilo.
    Restituisce (profile_name, profile_dict).
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
        return "", {}

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
                return "", {}
            base_url = base_url.strip()
            if not base_url:
                print("⚠️  Il provider 'openai_compatible' richiede un Base URL non vuoto.")
    else:
        base_url_input = questionary.text(
            f"Base URL per {provider} (lascia vuoto per default '{default_base}'):",
            default=""
        ).ask()
        if base_url_input is None:
            return "", {}
        base_url_input = base_url_input.strip()
        if not base_url_input or base_url_input == default_base:
            base_url = None
        else:
            base_url = base_url_input

    # 3. Round-Robin Multi-chiave o Singola API Key
    multi_input = questionary.confirm(
        f"Vuoi configurare più chiavi API per {provider} in round-robin (per distribuire le richieste su più account/quote)?",
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
                    "🔄 Sostituisci tutte le chiavi da zero",
                    "⏭ Mantieni le chiavi esistenti"
                ],
                default="➕ Aggiungi altre chiavi"
            ).ask()

            if action_choice is None:
                return "", {}

            if action_choice.startswith("⏭"):
                rr_action = "keep"
                collected_keys = list(existing_creds)
            elif action_choice.startswith("🔄"):
                rr_action = "replace"
                collected_keys = []
            else:
                rr_action = "add"
                collected_keys = list(existing_creds)

        if rr_action != "keep":
            while True:
                curr_idx = len(collected_keys) + 1
                cn = "google_1" if (provider == "google" and curr_idx == 1) else f"{provider.lower()}_{curr_idx}"
                ce = f"{provider.upper()}_API_KEY_{curr_idx}"
                prompt_str = f"API key #{curr_idx} per {provider} (invio vuoto per terminare se hai già inserito tutte le chiavi):"
                key_in = questionary.password(prompt_str).ask()
                if key_in is None:
                    return "", {}
                key_val = key_in.strip()
                if not key_val:
                    break
                collected_keys.append((cn, ce, key_val))

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
            api_key_input = questionary.password(
                f"API key per {provider} (lascia vuoto per mantenere esistente):",
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

    if api_key and effective_base_url:
        try:
            target_url = effective_base_url.rstrip("/") + "/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(target_url, headers=headers, timeout=8)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict) and "data" in body and isinstance(body["data"], list):
                    for item in body["data"]:
                        if isinstance(item, dict) and "id" in item and isinstance(item["id"], str):
                            models_list.append(item["id"])
        except Exception:
            pass

    chosen_model = ""
    MANUAL_ENTRY = "✍️ Inserisci manualmente"

    if models_list:
        choices = models_list + [MANUAL_ENTRY]
        selected_model = questionary.select(
            "Seleziona il modello LLM:",
            choices=choices,
            default=choices[0]
        ).ask()

        if selected_model is None:
            return "", {}

        if selected_model != MANUAL_ENTRY:
            chosen_model = selected_model

    if not chosen_model:
        if not models_list:
            print("ℹ️ Impossibile recuperare la lista modelli automaticamente.")
        manual_model = questionary.text(
            "ID Modello (es. deepseek-chat, google/gemini-2.5-flash):"
        ).ask()
        if not manual_model:
            return "", {}
        chosen_model = manual_model.strip()

    # Pricing inline opzionale per questo modello
    _configure_pricing_section(config_dir, provider, chosen_model)

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


_JOB_DISPLAY_ORDER = [
    "outline", "rewrite", "review_asr", "review_science",
    "image_description", "image_unit_judge",
    "recall_quiz", "recall_mirata", "recall_vasta", "recall_eval_mirata", "recall_eval_vasta",
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


def _configure_llm_provider_section(config_dir: str, env_path: str) -> Dict[str, str]:
    """
    Guida l'utente nella configurazione dei profili modello LLM per ciascuna fase della pipeline.
    Restituisce una mappa {job_name: profile_name_o_descrizione}.
    """
    print("\n------------------------------------------------------------")
    print("🤖 1. Configurazione Provider LLM per ciascuna fase")
    print("------------------------------------------------------------")

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

    if not profiles:
        prof_name, prof_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint="generale")
        if not prof_name:
            print("Operazione annullata dall'utente.")
            return {}
        profiles[prof_name] = prof_dict

    job_paths = find_job_yaml_paths(config_dir)
    ordered_job_names: List[str] = []
    for jn in _JOB_DISPLAY_ORDER:
        if jn in job_paths:
            ordered_job_names.append(jn)
    for jn in sorted(job_paths.keys()):
        if jn not in ordered_job_names:
            ordered_job_names.append(jn)

    ordered_jobs: List[Tuple[str, str]] = [(jn, job_paths[jn]) for jn in ordered_job_names]

    job_assignments: Dict[str, str] = {}
    for job_name, job_file in ordered_jobs:
        job_data: Dict[str, Any] = {}
        if os.path.isfile(job_file):
            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    loaded_job = yaml.safe_load(f)
                    if isinstance(loaded_job, dict):
                        job_data = loaded_job
            except Exception:
                pass

        current_match = _find_matching_profile(job_data, profiles)
        has_unrecognized = (current_match is None and _job_has_real_config(job_data))

        choices: List[str] = []
        default_choice: Optional[str] = None
        keep_label = "🔧 Mantieni configurazione attuale (non riconosciuta come profilo salvato)"

        if has_unrecognized:
            choices.append(keep_label)
            default_choice = keep_label

        choices.extend(sorted(profiles.keys()))
        NEW_PROFILE = "➕ Configura un nuovo modello per questa fase"
        choices.append(NEW_PROFILE)

        if default_choice is None:
            if current_match:
                default_choice = current_match
            elif "generale" in profiles:
                default_choice = "generale"
            else:
                default_choice = choices[0]

        selection = questionary.select(
            f"Modello per la fase '{job_name}':",
            choices=choices,
            default=default_choice
        ).ask()

        if selection is None:
            print("Configurazione LLM interrotta dall'utente.")
            break

        if has_unrecognized and selection == keep_label:
            job_assignments[job_name] = "(configurazione attuale mantenuta)"
            continue

        if selection == NEW_PROFILE:
            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint=job_name)
            if not p_name:
                print("Creazione nuovo profilo annullata.")
                break
            profiles[p_name] = p_dict
            selection = p_name

        _apply_profile_to_job(job_file, profiles[selection])
        job_assignments[job_name] = selection

    _save_model_profiles(general_data, profiles)
    _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))

    print(f"\n✅ Assegnazione modelli completata per {len(job_assignments)} job!")
    return job_assignments


def _configure_telegram_section(config_dir: str, env_path: str) -> Dict[str, Any]:
    """
    Guida l'utente nella configurazione di Telegram (Bot Token, Chat ID, discovery live/link topic, lessons_root).
    Restituisce un dizionario con l'esito della configurazione.
    """
    print("\n------------------------------------------------------------")
    print("✈️  2. Configurazione Telegram (Notifiche e Topic per Materia)")
    print("------------------------------------------------------------")

    confirm = questionary.confirm("Configurare Telegram ora?", default=True).ask()
    if not confirm:
        print("⏭  Sezione Telegram saltata.")
        return {"configured": False}

    # 1. Bot Token
    existing_token = os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")
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

    if mode and mode.startswith("📡"):
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
                                    f"Materia per {topic_label} (es. BIOCHIMICA, o 'varie' per Generale/Varie, invio per saltare):"
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

    if (mode and mode.startswith("🔗")) or (not topics_map and not detected_chat_id and mode and not mode.startswith("⏭")):
        if mode and mode.startswith("📡") and not topics_map:
            print("\n⚠️  Nessun messaggio rilevato via discovery live.")
            print("Verifica che il bot sia nel gruppo e che abbia i permessi di lettura messaggi.")

        print("\n--- 🔗 Inserimento Manuale via Link Topic ---")
        while True:
            link = questionary.text(
                "Incolla il link a un messaggio del topic (es. https://t.me/c/4490473926/541/679) [invio per terminare]:"
            ).ask()
            if not link or not link.strip():
                break
            parsed = parse_telegram_topic_link(link)
            if not parsed:
                print("❌ Formato link non valido. Esempio atteso: https://t.me/c/4490473926/541/679")
                continue

            chat_id, topic_id = parsed
            detected_chat_id = chat_id
            print(f"✔ Rilevato Chat ID: {chat_id}, Topic ID: {topic_id}")
            mat = questionary.text(f"Materia per Topic ID {topic_id} (es. BIOCHIMICA, o 'varie' per Varie):").ask()
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
    curr_lessons_root = general_data["telegram"].get("lessons_root", "")
    lessons_root_in = questionary.text(
        "Percorso assoluto cartella lezioni (lessons_root per Telegram /list e /recall):",
        default=curr_lessons_root
    ).ask()

    if lessons_root_in is not None:
        clean_root = os.path.expanduser(lessons_root_in.strip())
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
    print("🎙️  3. Configurazione Motore STT (Active Recall Vocale)")
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


def _configure_pricing_section(config_dir: str, provider: Optional[str], model: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Guida l'utente nella configurazione opzionale di un listino prezzi custom in config/general.yaml.
    """
    print("\n------------------------------------------------------------")
    print("💰 4. Configurazione Pricing Custom (Opzionale)")
    print("------------------------------------------------------------")

    confirm = questionary.confirm(
        "Configurare un listino prezzi custom per il provider/modello scelto? (opzionale, RT ha già stime interne)",
        default=False
    ).ask()

    if not confirm:
        print("⏭  Sezione Pricing custom saltata.")
        return None

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

    inp_str = questionary.text(
        "Costo Input per 1M token in USD (es. 0.14):",
        validate=lambda v: _is_valid_float(v) or "Inserisci un numero valido >= 0"
    ).ask()

    if inp_str is None:
        return None

    out_str = questionary.text(
        "Costo Output per 1M token in USD (es. 0.28):",
        validate=lambda v: _is_valid_float(v) or "Inserisci un numero valido >= 0"
    ).ask()

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
    job_profiles = _configure_llm_provider_section(config_dir, env_path)
    tg_res = _configure_telegram_section(config_dir, env_path)
    stt_engine = _configure_stt_section(config_dir)

    print("\n================================================------------")
    print("✅ Configurazione completata.")
    print("\nRiepilogo:")
    print("Modelli assegnati:")
    if job_profiles:
        for j_name, p_name in sorted(job_profiles.items()):
            print(f"- {j_name}: {p_name}")
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


def configure_config_parser(parser: Any) -> Any:
    """Configura l'argparse parser per rt config."""
    return parser
