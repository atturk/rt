"""
rt.pipeline.configure
Wizard interattivo di configurazione guidata per il progetto RT.
Gestisce la configurazione di:
- Provider LLM (DeepSeek, OpenRouter, Google Gemini, OpenAI Compatible) e credenziali.
- Telegram, STT e Pricing (estesi nei task successivi 21-22).
"""

import os
import sys
import shutil
import json
from typing import Dict, Any, List, Optional, Tuple
import yaml
import requests
import questionary

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths, _default_project_root, get_api_key


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


def _configure_llm_provider_section(config_dir: str, env_path: str) -> None:
    """
    Guida l'utente nella configurazione del provider LLM principale, base_url, API key e modello,
    aggiornando .env, config/general.yaml e tutti i file <job>.yaml.
    """
    print("\n------------------------------------------------------------")
    print("🤖 1. Configurazione Provider LLM principale")
    print("------------------------------------------------------------")

    # 1. Recupero valori correnti per pre-compilazione default
    curr_provider = "deepseek"
    curr_model = ""
    curr_base_url = ""

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

    job_paths = find_job_yaml_paths(config_dir)
    if job_paths:
        first_job_path = next(iter(job_paths.values()))
        try:
            with open(first_job_path, "r", encoding="utf-8") as f:
                jdata = yaml.safe_load(f)
                if isinstance(jdata, dict) and "primary" in jdata and isinstance(jdata["primary"], dict):
                    prim = jdata["primary"]
                    if prim.get("provider"):
                        curr_provider = prim["provider"]
                    if prim.get("model"):
                        curr_model = prim["model"]
                    if prim.get("base_url"):
                        curr_base_url = prim["base_url"]
        except Exception:
            pass

    # 2. Selezione Provider
    allowed_providers = ["deepseek", "openrouter", "google", "openai_compatible"]
    default_p = curr_provider if curr_provider in allowed_providers else "deepseek"
    provider = questionary.select(
        "Provider LLM principale:",
        choices=allowed_providers,
        default=default_p
    ).ask()

    if not provider:
        print("Operazione annullata dall'utente.")
        return

    # 3. Base URL
    default_base = KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, "")
    init_base = curr_base_url or default_base

    if provider == "openai_compatible":
        base_url = ""
        while not base_url:
            base_url = questionary.text(
                "Base URL (es. https://api.together.xyz/v1 - obbligatorio):",
                default=init_base
            ).ask()
            if base_url is None:
                print("Operazione annullata dall'utente.")
                return
            base_url = base_url.strip()
            if not base_url:
                print("⚠️  Il provider 'openai_compatible' richiede un Base URL non vuoto.")
    else:
        base_url_input = questionary.text(
            f"Base URL per {provider} (lascia vuoto per default '{default_base}'):",
            default=init_base
        ).ask()
        if base_url_input is None:
            print("Operazione annullata dall'utente.")
            return
        base_url_input = base_url_input.strip()
        if not base_url_input or base_url_input == default_base:
            base_url = None
        else:
            base_url = base_url_input

    # 4. API Key
    env_var_name = f"{provider.upper()}_API_KEY"
    existing_key = get_api_key(env_var_name) or get_api_key(provider) or ""
    api_key_input = questionary.password(
        f"API key per {provider} (lascia vuoto per mantenere esistente):",
        default=existing_key
    ).ask()

    if api_key_input is None:
        print("Operazione annullata dall'utente.")
        return

    api_key = api_key_input.strip() if api_key_input.strip() else existing_key

    cred_name = "google_1" if provider == "google" else f"{provider.lower()}_1"

    if api_key:
        # Aggiorna .env
        _update_env_file(env_path, env_var_name, api_key)

        # Aggiorna credentials in config/general.yaml
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

    # 5. Recupero Modelli
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
        default_model_choice = curr_model if curr_model in models_list else choices[0]
        selected_model = questionary.select(
            "Seleziona il modello LLM:",
            choices=choices,
            default=default_model_choice
        ).ask()

        if selected_model is None:
            print("Operazione annullata dall'utente.")
            return

        if selected_model != MANUAL_ENTRY:
            chosen_model = selected_model

    if not chosen_model:
        if not models_list:
            print("ℹ️ Impossibile recuperare la lista modelli automaticamente.")
        manual_model = questionary.text(
            "ID Modello (es. deepseek-chat, google/gemini-2.5-flash):",
            default=curr_model
        ).ask()
        if not manual_model:
            print("Operazione annullata dall'utente.")
            return
        chosen_model = manual_model.strip()

    # 6. Aggiornamento di tutti i file <job>.yaml
    updated_jobs: List[str] = []
    for job_name, job_file in sorted(find_job_yaml_paths(config_dir).items()):
        job_data: Dict[str, Any] = {}
        if os.path.isfile(job_file):
            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    loaded_job = yaml.safe_load(f)
                    if isinstance(loaded_job, dict):
                        job_data = loaded_job
            except Exception:
                pass

        if "primary" not in job_data or not isinstance(job_data["primary"], dict):
            job_data["primary"] = {}

        job_data["primary"]["provider"] = provider
        job_data["primary"]["model"] = chosen_model
        job_data["primary"]["credential"] = cred_name
        job_data["primary"]["base_url"] = base_url

        _atomic_write_text(job_file, yaml.safe_dump(job_data, sort_keys=False, allow_unicode=True))
        updated_jobs.append(job_name)

    # 7. Riepilogo finale sezione LLM
    print(f"\n✅ Provider LLM configurato con successo per {len(updated_jobs)} job!")
    print(f"   Provider:    {provider}")
    print(f"   Modello:     {chosen_model}")
    print(f"   Credenziale:  {cred_name} ({env_var_name})")
    if base_url:
        print(f"   Base URL:    {base_url}")


def run_config_wizard(interactive: bool = True) -> None:
    """Esegue il wizard interattivo rt config."""
    print("================================----------------------------")
    print("⚙️  RT CONFIG — Wizard di configurazione guidata")
    print("================================----------------------------")

    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    _configure_llm_provider_section(config_dir, env_path)

    print("\n✨ Configurazione completata!")


def configure_config_parser(parser: Any) -> Any:
    """Configura l'argparse parser per rt config."""
    return parser
