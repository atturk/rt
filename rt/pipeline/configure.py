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
from typing import Dict, Any, List, Optional, Tuple
import yaml
import requests
import questionary

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, find_job_yaml_paths, _default_project_root, get_api_key


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


def _configure_llm_provider_section(config_dir: str, env_path: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Guida l'utente nella configurazione del provider LLM principale, base_url, API key e modello,
    aggiornando .env, config/general.yaml e tutti i file <job>.yaml.
    Restituisce (provider, model, list_updated_jobs).
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
        return None, None, []

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
                return None, None, []
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
            return None, None, []
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
        return None, None, []

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
            return None, None, []

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
            return None, None, []
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

    return provider, chosen_model, updated_jobs


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
    existing_token = get_api_key("RT_TELEGRAM_BOT_TOKEN") or ""
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

        print("\nListening per messaggi Telegram (Ctrl+C per terminare il polling)...")
        try:
            for _ in range(15):
                if stop_discovery:
                    break
                try:
                    resp = requests.get(
                        f"https://api.telegram.org/bot{bot_token}/getUpdates",
                        params={"offset": last_offset, "timeout": 2},
                        timeout=5
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

    allowed_stt = ["macparakeet", "macwhisper", "api"]
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
    provider, model, updated_jobs = _configure_llm_provider_section(config_dir, env_path)
    tg_res = _configure_telegram_section(config_dir, env_path)
    stt_engine = _configure_stt_section(config_dir)
    pricing_res = _configure_pricing_section(config_dir, provider, model)

    print("\n================================================------------")
    print("✅ Configurazione completata.")
    print("\nRiepilogo:")
    prov_str = f"{provider} / {model}" if provider and model else "Non modificato"
    print(f"- Provider LLM:   {prov_str} (applicato a {len(updated_jobs)} job)")

    if tg_res and tg_res.get("configured"):
        t_cnt = tg_res.get("topics_count", 0)
        print(f"- Telegram:       configurato ({t_cnt} topic mappati)")
    else:
        print("- Telegram:       non configurato")

    print(f"- Motore STT:     {stt_engine}")

    if pricing_res:
        p_p = pricing_res.get("provider")
        p_m = pricing_res.get("model")
        print(f"- Pricing custom: impostato per {p_p}/{p_m}")
    else:
        print("- Pricing custom: non impostato")

    print("\nProssimi passi:")
    print("1. Verifica la configurazione con: ./bin/rt status <una_lezione_di_prova>")
    print("2. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock")
    print("3. Puoi rilanciare 'rt config' in qualsiasi momento per modificare una singola sezione.")
    print("================================================------------\n")


def configure_config_parser(parser: Any) -> Any:
    """Configura l'argparse parser per rt config."""
    return parser
