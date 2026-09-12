"""
tests/test_configure_wizard.py
Unit test per il wizard di configurazione rt config (rt/pipeline/configure.py).
"""

import os
import shutil
import json
import pytest
from unittest.mock import patch, MagicMock
import yaml
import requests

from rt.pipeline.configure import (
    _resolve_or_bootstrap_config_paths,
    _update_env_file,
    _load_model_profiles,
    _save_model_profiles,
    _suggest_profile_name,
    _create_new_model_profile,
    _apply_profile_to_job,
    _job_has_real_config,
    _find_matching_profile,
    _configure_llm_provider_section,
    _configure_telegram_section,
    _configure_stt_section,
    _configure_pricing_section,
    run_config_wizard,
    run_models_management,
    run_telegram_only,
    configure_config_parser,
)
from rt.core.config import load_config, find_job_yaml_paths


def test_resolve_or_bootstrap_config_paths_first_run(tmp_path, monkeypatch):
    """Verifica che al primo avvio (niente config/ in cwd né root), config/ venga creata da config.example/."""
    fake_cwd = str(tmp_path / "workdir")
    os.makedirs(fake_cwd, exist_ok=True)
    monkeypatch.chdir(fake_cwd)

    # In un repo fittizio senza config/ ma con config.example/
    fake_root = str(tmp_path / "repo")
    example_dir = os.path.join(fake_root, "config.example")
    os.makedirs(example_dir, exist_ok=True)
    with open(os.path.join(example_dir, "general.yaml"), "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\n")

    with patch("rt.pipeline.configure._default_project_root", return_value=fake_root):
        config_dir, env_path = _resolve_or_bootstrap_config_paths()

    assert config_dir == os.path.join(fake_root, "config")
    assert os.path.isfile(os.path.join(config_dir, "general.yaml"))
    assert env_path == os.path.join(fake_root, ".env")


def test_update_env_file_preserves_other_keys(tmp_path):
    """Verifica che _update_env_file aggiorni o aggiunga una chiave preservando le altre righe."""
    env_file = str(tmp_path / ".env")
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("RT_TELEGRAM_BOT_TOKEN=123456:ABC\nDEEPSEEK_API_KEY=old_key\n")

    # Aggiorna una chiave esistente
    _update_env_file(env_file, "DEEPSEEK_API_KEY", "new_key")
    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "RT_TELEGRAM_BOT_TOKEN=123456:ABC" in content
    assert "DEEPSEEK_API_KEY=new_key" in content
    assert "DEEPSEEK_API_KEY=old_key" not in content

    # Aggiunge una nuova chiave
    _update_env_file(env_file, "OPENROUTER_API_KEY", "or_key_123")
    with open(env_file, "r", encoding="utf-8") as f:
        content2 = f.read()

    assert "RT_TELEGRAM_BOT_TOKEN=123456:ABC" in content2
    assert "DEEPSEEK_API_KEY=new_key" in content2
    assert "OPENROUTER_API_KEY=or_key_123" in content2


def test_configure_llm_provider_section_success_http_models(tmp_path):
    """Verifica la configurazione del provider LLM con recupero HTTP dei modelli riuscito."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)

    # Creiamo un general.yaml ed un job.yaml di prova
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\ncredentials: []\n")

    outline_job = os.path.join(config_dir, "outline.yaml")
    with open(outline_job, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "primary": {"provider": None, "model": None, "max_tokens": 8192, "thinking": True}
        }, f)

    env_file = str(tmp_path / ".env")

    # Mock degli input di questionary
    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "deepseek"
        elif "modello LLM" in prompt:
            m.ask.return_value = "deepseek-reasoner"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""  # Usa default
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = default or "generale"
        else:
            m.ask.return_value = default or ""
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-deepseek-secret-123"
        return m

    def mock_autocomplete(prompt, choices, default=None, **kwargs):
        m = MagicMock()
        m.ask.return_value = "deepseek-reasoner"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    # Mock HTTP response per /models
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]
    }

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.autocomplete", side_effect=mock_autocomplete), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", return_value=mock_resp):

        _configure_llm_provider_section(config_dir, env_file)

    # Verifiche: .env contiene DEEPSEEK_API_KEY
    with open(env_file, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "DEEPSEEK_API_KEY=sk-deepseek-secret-123" in env_content

    # general.yaml contiene credenziale deepseek_1 e model_profiles
    with open(general_file, "r", encoding="utf-8") as f:
        gen_data = yaml.safe_load(f)
    assert len(gen_data["credentials"]) == 1
    assert gen_data["credentials"][0]["name"] == "deepseek_1"
    assert gen_data["credentials"][0]["provider"] == "deepseek"
    assert gen_data["credentials"][0]["env_var"] == "DEEPSEEK_API_KEY"
    assert "model_profiles" in gen_data
    assert "outline" in gen_data["model_profiles"]

    # outline.yaml ha provider, model e credential aggiornati ma max_tokens e thinking intatti
    with open(outline_job, "r", encoding="utf-8") as f:
        job_data = yaml.safe_load(f)
    assert job_data["primary"]["provider"] == "deepseek"
    assert job_data["primary"]["model"] == "deepseek-reasoner"
    assert job_data["primary"]["credential"] == "deepseek_1"
    assert job_data["primary"]["max_tokens"] == 8192
    assert job_data["primary"]["thinking"] is True


def test_configure_llm_provider_section_http_failure_fallback_manual(tmp_path):
    """Verifica il fallback ad inserimento manuale del modello quando la richiesta HTTP dei modelli fallisce."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\ncredentials: []\n")

    rewrite_job = os.path.join(config_dir, "rewrite.yaml")
    with open(rewrite_job, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "primary": {"provider": None, "model": None, "max_tokens": 4096}
        }, f)

    env_file = str(tmp_path / ".env")

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "openrouter"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""
        elif "ID Modello" in prompt:
            m.ask.return_value = "anthropic/claude-3.5-sonnet"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = default or "generale"
        else:
            m.ask.return_value = default or ""
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-or-test"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    # Mock HTTP failure (timeout / ConnectionError)
    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _configure_llm_provider_section(config_dir, env_file)

    with open(rewrite_job, "r", encoding="utf-8") as f:
        job_data = yaml.safe_load(f)

    assert job_data["primary"]["provider"] == "openrouter"
    assert job_data["primary"]["model"] == "anthropic/claude-3.5-sonnet"
    assert job_data["primary"]["credential"] == "openrouter_1"
    assert job_data["primary"]["max_tokens"] == 4096


def test_parse_telegram_topic_link():
    """Verifica il parsing dei link a messaggi/topic Telegram."""
    from rt.pipeline.configure import parse_telegram_topic_link

    # Link valido con message_id
    res1 = parse_telegram_topic_link("https://t.me/c/4490473926/541/679")
    assert res1 == (-1004490473926, 541)

    # Link valido senza message_id
    res2 = parse_telegram_topic_link("t.me/c/123456789/42")
    assert res2 == (-100123456789, 42)

    # Link non valido
    assert parse_telegram_topic_link("https://t.me/somechannel/123") is None
    assert parse_telegram_topic_link("invalido") is None
    assert parse_telegram_topic_link("") is None


def test_configure_telegram_section_skip(tmp_path):
    """Verifica che saltare la sezione Telegram non lasci modifiche inattese."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    from rt.pipeline.configure import _configure_telegram_section

    with patch("questionary.confirm", return_value=MagicMock(ask=lambda: False)):
        _configure_telegram_section(config_dir, env_file)

    assert not os.path.isfile(env_file)


def test_configure_telegram_section_manual_link_flow(tmp_path):
    """Verifica il flusso di inserimento manuale del link topic Telegram."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"telegram": {"topics": {"PATOLOGIA": 10}}}, f)

    env_file = str(tmp_path / ".env")

    from rt.pipeline.configure import _configure_telegram_section

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        m.ask.return_value = True
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "🔗 Incolla link topic (manuale)"
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "123456:BOT_TOKEN_TEST"
        return m

    text_calls = []

    def mock_text(prompt, default=None):
        m = MagicMock()
        if "Incolla il link" in prompt:
            # Primo link, poi stringa vuota per terminare
            val = "https://t.me/c/4490473926/541/679" if len(text_calls) == 0 else ""
            text_calls.append(val)
            m.ask.return_value = val
        elif "Materia per Topic ID" in prompt:
            m.ask.return_value = "BIOCHIMICA"
        elif "lessons_root" in prompt:
            m.ask.return_value = str(tmp_path / "lezioni")
        else:
            m.ask.return_value = ""
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.password", side_effect=mock_password), \
         patch("questionary.text", side_effect=mock_text):

        _configure_telegram_section(config_dir, env_file)

    # Verifica .env
    with open(env_file, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "RT_TELEGRAM_BOT_TOKEN=123456:BOT_TOKEN_TEST" in env_content
    assert "RT_TELEGRAM_CHAT_ID=-1004490473926" in env_content

    # Verifica general.yaml (merge con PATOLOGIA pre-esistente)
    with open(general_file, "r", encoding="utf-8") as f:
        gen_data = yaml.safe_load(f)
    assert gen_data["telegram"]["topics"]["PATOLOGIA"] == 10
    assert gen_data["telegram"]["topics"]["BIOCHIMICA"] == 541
    assert gen_data["telegram"]["lessons_root"] == str(tmp_path / "lezioni")


def test_configure_stt_section_macparakeet(tmp_path):
    """Verifica l'impostazione del motore STT su macparakeet."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"telegram": {"recall": {"stt_engine": "macwhisper"}}}, f)

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "macparakeet"
        return m

    with patch("questionary.select", side_effect=mock_select):
        res = _configure_stt_section(config_dir)

    assert res == "macparakeet"
    with open(general_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["telegram"]["recall"]["stt_engine"] == "macparakeet"


def test_configure_stt_section_api_warning(tmp_path):
    """Verifica l'impostazione del motore STT su api con conferma avviso."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "api"
        return m

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        m.ask.return_value = True
        return m

    with patch("questionary.select", side_effect=mock_select), \
         patch("questionary.confirm", side_effect=mock_confirm):
        res = _configure_stt_section(config_dir)

    assert res == "api"
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["telegram"]["recall"]["stt_engine"] == "api"


def test_configure_pricing_section(tmp_path):
    """Verifica la scrittura di un listino prezzi custom in general.yaml."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        if "costo di reasoning" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = True
        return m

    def mock_text(prompt, validate=None):
        m = MagicMock()
        if "Costo Input" in prompt:
            m.ask.return_value = "0.14"
        elif "Costo Output" in prompt:
            m.ask.return_value = "0.28"
        elif "Costo Reasoning" in prompt:
            m.ask.return_value = "0.55"
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.text", side_effect=mock_text):
        res = _configure_pricing_section(config_dir, "deepseek", "deepseek-reasoner")

    assert res is not None
    assert res["provider"] == "deepseek"
    assert res["model"] == "deepseek-reasoner"
    assert res["pricing"]["input_per_million"] == 0.14
    assert res["pricing"]["output_per_million"] == 0.28
    assert res["pricing"]["reasoning_per_million"] == 0.55

    with open(general_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["pricing"]["deepseek"]["deepseek-reasoner"]["input_per_million"] == 0.14
    assert data["pricing"]["deepseek"]["deepseek-reasoner"]["output_per_million"] == 0.28
    assert data["pricing"]["deepseek"]["deepseek-reasoner"]["reasoning_per_million"] == 0.55


def test_run_config_wizard_full_flow(tmp_path, monkeypatch):
    """Verifica che run_config_wizard sia eseguibile e completi senza sollevare eccezioni."""
    fake_cwd = str(tmp_path / "workdir")
    os.makedirs(fake_cwd, exist_ok=True)
    monkeypatch.chdir(fake_cwd)

    fake_root = str(tmp_path / "repo")
    example_dir = os.path.join(fake_root, "config.example")
    os.makedirs(example_dir, exist_ok=True)
    with open(os.path.join(example_dir, "general.yaml"), "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\ncredentials: []\n")

    with patch("rt.pipeline.configure._default_project_root", return_value=fake_root), \
         patch("rt.pipeline.configure._configure_llm_provider_section", return_value={"outline": "generale"}), \
         patch("rt.pipeline.configure._configure_telegram_section", return_value={"configured": True, "topics_count": 2}), \
         patch("rt.pipeline.configure._configure_stt_section", return_value="macparakeet"):

        run_config_wizard()


def test_configure_llm_provider_section_multi_key_round_robin(tmp_path):
    """Verifica la configurazione da zero con 3 chiavi round-robin per lo stesso provider."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\ncredentials: []\n")

    outline_job = os.path.join(config_dir, "outline.yaml")
    with open(outline_job, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "primary": {"provider": None, "model": None, "max_tokens": 8192, "thinking": True}
        }, f)

    env_file = str(tmp_path / ".env")

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        elif "chiavi API" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "google"
        elif "modello LLM" in prompt:
            m.ask.return_value = "gemini-2.5-flash"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""
        elif "ID Modello" in prompt:
            m.ask.return_value = "gemini-2.5-flash"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = default or "generale"
        else:
            m.ask.return_value = default or ""
        return m

    passwords = ["key-google-1", "key-google-2", "key-google-3", ""]
    pass_idx = 0

    def mock_password(prompt, default=None):
        nonlocal pass_idx
        m = MagicMock()
        val = passwords[pass_idx] if pass_idx < len(passwords) else ""
        pass_idx += 1
        m.ask.return_value = val
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _configure_llm_provider_section(config_dir, env_file)

    # 1. .env ha le 3 chiavi
    with open(env_file, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "GOOGLE_API_KEY_1=key-google-1" in env_content
    assert "GOOGLE_API_KEY_2=key-google-2" in env_content
    assert "GOOGLE_API_KEY_3=key-google-3" in env_content

    # 2. general.yaml ha le 3 credenziali
    with open(general_file, "r", encoding="utf-8") as f:
        gen_data = yaml.safe_load(f)
    assert len(gen_data["credentials"]) == 3
    assert [c["name"] for c in gen_data["credentials"]] == ["google_1", "google_2", "google_3"]

    # 3. outline.yaml ha round_robin: true e primary_routes con 3 elementi e tuning preservato
    with open(outline_job, "r", encoding="utf-8") as f:
        job_data = yaml.safe_load(f)
    assert job_data["round_robin"] is True
    assert len(job_data["primary_routes"]) == 3
    for idx, route in enumerate(job_data["primary_routes"], start=1):
        assert route["provider"] == "google"
        assert route["model"] == "gemini-2.5-flash"
        assert route["credential"] == f"google_{idx}"
        assert route["max_tokens"] == 8192
        assert route["thinking"] is True


def test_configure_llm_provider_section_multi_key_append_rerun(tmp_path, monkeypatch):
    """Verifica che una riesecuzione con aggiunta di una 4ª chiave appenda la route a quelle esistenti."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "version": "2.0.0",
            "credentials": [
                {"name": f"google_{i}", "provider": "google", "env_var": f"GOOGLE_API_KEY_{i}"}
                for i in range(1, 4)
            ]
        }, f)

    outline_job = os.path.join(config_dir, "outline.yaml")
    with open(outline_job, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "round_robin": True,
            "primary_routes": [
                {"provider": "google", "model": "gemini-2.5-flash", "credential": f"google_{i}", "max_tokens": 8192}
                for i in range(1, 4)
            ]
        }, f)

    env_file = str(tmp_path / ".env")
    monkeypatch.setenv("GOOGLE_API_KEY_1", "k1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "k2")
    monkeypatch.setenv("GOOGLE_API_KEY_3", "k3")

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        elif "chiavi API" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "google"
        elif "Gestione chiavi" in prompt:
            m.ask.return_value = "➕ Aggiungi altre chiavi"
        elif "modello LLM" in prompt:
            m.ask.return_value = "gemini-2.5-flash"
        elif "Modello per" in prompt:
            m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""
        elif "ID Modello" in prompt:
            m.ask.return_value = "gemini-2.5-flash"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = "generale"
        else:
            m.ask.return_value = default or ""
        return m

    passwords = ["k4", ""]
    pass_idx = 0

    def mock_password(prompt, default=None):
        nonlocal pass_idx
        m = MagicMock()
        val = passwords[pass_idx] if pass_idx < len(passwords) else ""
        pass_idx += 1
        m.ask.return_value = val
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _configure_llm_provider_section(config_dir, env_file)

    with open(outline_job, "r", encoding="utf-8") as f:
        job_data = yaml.safe_load(f)

    assert job_data["round_robin"] is True
    assert len(job_data["primary_routes"]) == 4
    assert [r["credential"] for r in job_data["primary_routes"]] == ["google_1", "google_2", "google_3", "google_4"]
    assert job_data["primary_routes"][3]["max_tokens"] == 8192


def test_configure_llm_provider_section_multi_key_single_key_fallback(tmp_path):
    """Verifica che inserire 1 sola chiave nel flusso multi provochi il fallback alla configurazione singola."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        f.write("version: '2.0.0'\ncredentials: []\n")

    outline_job = os.path.join(config_dir, "outline.yaml")
    with open(outline_job, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": None, "model": None}}, f)

    env_file = str(tmp_path / ".env")

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        elif "chiavi API" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "deepseek"
        elif "Modello per" in prompt:
            m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""
        elif "ID Modello" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = "generale"
        else:
            m.ask.return_value = default or ""
        return m

    passwords = ["sk-only-one", ""]
    pass_idx = 0

    def mock_password(prompt, default=None):
        nonlocal pass_idx
        m = MagicMock()
        val = passwords[pass_idx] if pass_idx < len(passwords) else ""
        pass_idx += 1
        m.ask.return_value = val
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _configure_llm_provider_section(config_dir, env_file)

    with open(outline_job, "r", encoding="utf-8") as f:
        job_data = yaml.safe_load(f)

    # Invece di primary_routes, ha il blocco primary singolo e round_robin è False
    assert "primary_routes" not in job_data
    assert job_data["primary"]["provider"] == "deepseek"
    assert job_data["primary"]["model"] == "deepseek-chat"
    assert job_data["primary"]["credential"] == "deepseek_1"
    assert job_data.get("round_robin") is False


def test_suggest_profile_name_sanitization_and_uniqueness():
    """Verifica la sanitizzazione e la generazione di nomi univoci per i profili modello."""
    s1 = _suggest_profile_name("openrouter", "openai/gpt-5.6-luna", [])
    assert s1 == "openrouter_openai_gpt_5_6_luna"

    s2 = _suggest_profile_name("openrouter", "openai/gpt-5.6-luna", ["openrouter_openai_gpt_5_6_luna"])
    assert s2 == "openrouter_openai_gpt_5_6_luna_2"

    s3 = _suggest_profile_name("google", "gemini-3.5-flash", ["google_gemini_3_5_flash", "google_gemini_3_5_flash_2"])
    assert s3 == "google_gemini_3_5_flash_3"


def test_load_and_save_model_profiles():
    """Verifica il caricamento, la normalizzazione ed il salvataggio dei profili modello."""
    gen_data = {
        "model_profiles": {
            "generale": {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "round_robin": False,
                "routes": [{"credential": "openrouter_1", "model": "openai/gpt-5"}]
            },
            "malformed": "non_a_dict"
        }
    }

    profiles = _load_model_profiles(gen_data)
    assert "generale" in profiles
    assert "malformed" not in profiles
    assert profiles["generale"]["provider"] == "openrouter"

    _save_model_profiles(gen_data, profiles)
    assert gen_data["model_profiles"] == profiles


def test_configure_llm_provider_section_first_run_and_rerun(tmp_path):
    """Verifica che il primo avvio crei il profilo 'generale' e che il rerun lo riusi."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0", "credentials": []}, f)

    job_file = os.path.join(config_dir, "outline.yaml")
    with open(job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": None}}, f)

    env_file = str(tmp_path / ".env")

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "deepseek"
        elif "modello LLM" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Modello per" in prompt:
            if "generale" in choices:
                m.ask.return_value = "generale"
            else:
                m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "ID Modello" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = "generale"
        else:
            m.ask.return_value = default or ""
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-deepseek-test"
        return m

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    # Primo avvio e Rerun
    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        res1 = _configure_llm_provider_section(config_dir, env_file)
        res2 = _configure_llm_provider_section(config_dir, env_path=env_file)

    assert res1 == {"outline": "generale"}

    with open(general_file, "r", encoding="utf-8") as f:
        gen_data = yaml.safe_load(f)

    assert "model_profiles" in gen_data
    assert "generale" in gen_data["model_profiles"]
    assert res2 == {"outline": "generale"}


def test_find_matching_profile_exact_match_and_mismatches():
    """Verifica la corrispondenza esatta dei profili noti rispetto alla configurazione YAML dei job."""
    profiles = {
        "generale": {
            "provider": "openrouter",
            "base_url": None,
            "round_robin": False,
            "routes": [{"credential": "openrouter_1", "model": "openai/gpt-5.6-luna"}]
        },
        "rewrite_rr": {
            "provider": "google",
            "base_url": None,
            "round_robin": True,
            "routes": [
                {"credential": "google_1", "model": "gemini-3.5-flash"},
                {"credential": "google_2", "model": "gemini-3.5-flash"}
            ]
        }
    }

    # Job vuoto -> None
    assert _find_matching_profile({"primary": {"provider": None}}, profiles) is None

    # Match esatto singola chiave
    job_single = {
        "round_robin": False,
        "primary": {"provider": "openrouter", "model": "openai/gpt-5.6-luna", "credential": "openrouter_1"}
    }
    assert _find_matching_profile(job_single, profiles) == "generale"

    # Match esatto round robin
    job_rr = {
        "round_robin": True,
        "primary_routes": [
            {"provider": "google", "model": "gemini-3.5-flash", "credential": "google_1"},
            {"provider": "google", "model": "gemini-3.5-flash", "credential": "google_2"}
        ]
    }
    assert _find_matching_profile(job_rr, profiles) == "rewrite_rr"

    # Mismatch modello -> None
    job_diff_model = {
        "round_robin": False,
        "primary": {"provider": "openrouter", "model": "anthropic/claude-3", "credential": "openrouter_1"}
    }
    assert _find_matching_profile(job_diff_model, profiles) is None


def test_per_phase_model_selection_and_reuse(tmp_path):
    """Verifica la selezione per-fase ed il riuso immediato di un profilo creato al volo."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0", "credentials": []}, f)

    outline_file = os.path.join(config_dir, "outline.yaml")
    rewrite_file = os.path.join(config_dir, "rewrite.yaml")
    science_file = os.path.join(config_dir, "review_science.yaml")
    for fp in (outline_file, rewrite_file, science_file):
        with open(fp, "w", encoding="utf-8") as f:
            yaml.safe_dump({"primary": {"provider": None}}, f)

    env_file = str(tmp_path / ".env")

    select_calls = []

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "google" if len(select_calls) > 0 else "deepseek"
        elif "modello LLM" in prompt:
            m.ask.return_value = "gemini-3.5-flash" if "google" in prompt or "Google" in str(choices) else "deepseek-chat"
        elif "Modello per" in prompt:
            phase = prompt.split("'")[1] if "'" in prompt else ""
            select_calls.append(phase)
            if phase == "outline":
                m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
            elif phase == "rewrite":
                m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
            elif phase == "review_science":
                m.ask.return_value = "rewrite"
            else:
                m.ask.return_value = choices[0]
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    confirm_count = 0

    def mock_confirm(prompt, default=False):
        nonlocal confirm_count
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        elif "chiavi API" in prompt:
            confirm_count += 1
            m.ask.return_value = (confirm_count > 1)
        else:
            m.ask.return_value = False
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "ID Modello" in prompt:
            m.ask.return_value = "gemini-3.5-flash"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = default or "profilo"
        else:
            m.ask.return_value = default or ""
        return m

    passwords = ["sk-deepseek-1", "gkey1", "gkey2", ""]
    pass_idx = 0

    def mock_password(prompt, default=None):
        nonlocal pass_idx
        m = MagicMock()
        val = passwords[pass_idx] if pass_idx < len(passwords) else "secret"
        pass_idx += 1
        m.ask.return_value = val
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        assignments = _configure_llm_provider_section(config_dir, env_file)

    assert assignments["outline"] == "outline"
    assert assignments["rewrite"] == "rewrite"
    assert assignments["review_science"] == "rewrite"

    with open(rewrite_file, "r", encoding="utf-8") as f:
        rw_data = yaml.safe_load(f)
    assert rw_data["round_robin"] is True
    assert len(rw_data["primary_routes"]) >= 2

    with open(science_file, "r", encoding="utf-8") as f:
        sc_data = yaml.safe_load(f)
    assert sc_data["round_robin"] is True
    assert len(sc_data["primary_routes"]) >= 2


def test_rerun_unrecognized_config_keep_choice(tmp_path):
    """Verifica che la scelta 'Mantieni configurazione attuale' preservi intatto il file YAML del job."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "version": "2.0.0",
            "model_profiles": {
                "generale": {
                    "provider": "openrouter",
                    "routes": [{"credential": "or_1", "model": "gpt-4"}]
                }
            }
        }, f)

    outline_file = os.path.join(config_dir, "outline.yaml")
    custom_content = {
        "round_robin": False,
        "primary": {"provider": "custom_provider", "model": "custom_model_v9", "credential": "custom_cred"}
    }
    with open(outline_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(custom_content, f)

    env_file = str(tmp_path / ".env")

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Modello per" in prompt:
            keep_choice = [c for c in choices if "Mantieni" in c][0]
            m.ask.return_value = keep_choice
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    with patch("questionary.select", side_effect=mock_select):
        res = _configure_llm_provider_section(config_dir, env_file)

    assert res["outline"] == "(configurazione attuale mantenuta)"

    with open(outline_file, "r", encoding="utf-8") as f:
        data_after = yaml.safe_load(f)

    assert data_after == custom_content


def test_skip_option_and_no_forced_bootstrap(tmp_path):
    """Verifica che al primo avvio non venga forzato 'generale' e 'Lascia vuoto per ora' preservi i job."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)

    outline_file = os.path.join(config_dir, "outline.yaml")
    with open(outline_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": None}}, f)

    env_file = str(tmp_path / ".env")

    prompt_choices = {}

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Modello per" in prompt:
            prompt_choices[prompt] = list(choices)
            m.ask.return_value = "⏭ Lascia vuoto per ora"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    with patch("questionary.select", side_effect=mock_select):
        res = _configure_llm_provider_section(config_dir, env_file)

    # Scelte al primo avvio: soltanto SKIP_LABEL e NEW_PROFILE (nessun profilo pre-creato)
    assert any("outline" in p for p in prompt_choices)
    outline_key = [p for p in prompt_choices if "outline" in p][0]
    assert prompt_choices[outline_key] == ["⏭ Lascia vuoto per ora", "➕ Configura un nuovo modello per questa fase"]

    assert res["outline"] == "(non configurato)"
    with open(outline_file, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
    assert content == {"primary": {"provider": None}}


def test_grouped_jobs_recall_and_immagini(tmp_path):
    """Verifica che recall (5 job) ed immagini (2 job) ricevano ciascuno 1 sola domanda ed applichino la scelta a tutti."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)

    recall_jobs = ["recall_quiz", "recall_mirata", "recall_vasta", "recall_eval_mirata", "recall_eval_vasta"]
    image_jobs = ["image_description", "image_unit_judge"]

    for jn in recall_jobs + image_jobs:
        with open(os.path.join(config_dir, f"{jn}.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"primary": {"provider": None}}, f)

    env_file = str(tmp_path / ".env")

    model_questions = []

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "deepseek"
        elif "modello LLM" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Modello per" in prompt:
            model_questions.append(prompt)
            m.ask.return_value = "➕ Configura un nuovo modello per questa fase"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "ID Modello" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = default or "prof"
        else:
            m.ask.return_value = default or ""
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-test"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        res = _configure_llm_provider_section(config_dir, env_file)

    # Deve esserci esattamente UNA domanda per immagini ed UNA domanda per recall
    img_q = [q for q in model_questions if "immagini" in q]
    recall_q = [q for q in model_questions if "recall" in q]
    assert len(img_q) == 1
    assert len(recall_q) == 1

    # Tutti i 5 job di recall ed i 2 di immagini hanno lo stesso profilo in assignments
    for jn in recall_jobs:
        assert res[jn] == "recall_quiz"
        with open(os.path.join(config_dir, f"{jn}.yaml"), "r", encoding="utf-8") as f:
            jdata = yaml.safe_load(f)
        assert jdata["primary"]["provider"] == "deepseek"
        assert jdata["primary"]["model"] == "deepseek-chat"

    for jn in image_jobs:
        assert res[jn] == "image_description"
        with open(os.path.join(config_dir, f"{jn}.yaml"), "r", encoding="utf-8") as f:
            jdata = yaml.safe_load(f)
        assert jdata["primary"]["provider"] == "deepseek"
        assert jdata["primary"]["model"] == "deepseek-chat"


def test_api_key_prompt_conditional_message(tmp_path, monkeypatch):
    """Verifica che il messaggio per l'API key sia diverso a seconda che esista o meno una chiave nell'ambiente."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)
    env_file = str(tmp_path / ".env")

    # Scenario 1: nessuna chiave esistente nell'ambiente
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    prompts_1 = []

    def mock_password_1(prompt, default=None):
        prompts_1.append(prompt)
        m = MagicMock()
        m.ask.return_value = "sk-key-1"
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "Provider LLM" in prompt:
            m.ask.return_value = "deepseek"
        else:
            m.ask.return_value = default or (choices[0] if choices else "")
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "ID Modello" in prompt:
            m.ask.return_value = "deepseek-chat"
        elif "Nome per questo profilo" in prompt:
            m.ask.return_value = "p1"
        else:
            m.ask.return_value = default or ""
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password_1), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert any("API key per deepseek:" in p for p in prompts_1)
    assert not any("mantenere esistente" in p for p in prompts_1)

    # Scenario 2: chiave esistente nell'ambiente
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing_secret_key")
    prompts_2 = []

    def mock_password_2(prompt, default=None):
        prompts_2.append(prompt)
        m = MagicMock()
        m.ask.return_value = ""
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password_2), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert any("mantenere esistente" in p for p in prompts_2)


def test_autocomplete_selection_and_confirm_yes(tmp_path):
    """Verifica selezione con autocomplete da lista HTTP e conferma positiva."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "deepseek"
        return m

    def mock_autocomplete(prompt, choices, default=None, **kwargs):
        m = MagicMock()
        assert choices == ["model-a", "model-b"]
        m.ask.return_value = "model-b"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        m.ask.return_value = default or "prof1"
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "key123"
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.autocomplete", side_effect=mock_autocomplete), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", return_value=mock_resp):

        name, prof = _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert name == "deepseek_model_b"
    assert prof["routes"][0]["model"] == "model-b"


def test_autocomplete_rejection_and_reselection(tmp_path):
    """Verifica che il rifiuto della conferma permetta di riselezionare un altro modello."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    auto_calls = 0

    def mock_autocomplete(prompt, choices, default=None, **kwargs):
        nonlocal auto_calls
        auto_calls += 1
        m = MagicMock()
        m.ask.return_value = "model-a" if auto_calls == 1 else "model-b"
        return m

    confirm_calls = 0

    def mock_confirm(prompt, default=True):
        nonlocal confirm_calls
        m = MagicMock()
        if "confermi" in prompt:
            confirm_calls += 1
            # Primo giro rifiuta, secondo giro accetta
            m.ask.return_value = (confirm_calls > 1)
        else:
            m.ask.return_value = False
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "deepseek"
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        m.ask.return_value = default or "prof2"
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "key123"
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.autocomplete", side_effect=mock_autocomplete), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", return_value=mock_resp):

        name, prof = _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert auto_calls == 2
    assert confirm_calls == 2
    assert prof["routes"][0]["model"] == "model-b"


def test_autocomplete_custom_free_text_accepted(tmp_path):
    """Verifica che un testo libero digitato in autocomplete venga accettato come modello valido."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "model-a"}]}

    def mock_autocomplete(prompt, choices, default=None, **kwargs):
        m = MagicMock()
        # Testo personalizzato non in choices
        m.ask.return_value = "my-org/custom-model-x"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "deepseek"
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        m.ask.return_value = default or "prof3"
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "key123"
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.autocomplete", side_effect=mock_autocomplete), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", return_value=mock_resp):

        name, prof = _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert prof["routes"][0]["model"] == "my-org/custom-model-x"


def test_text_fallback_with_confirm(tmp_path):
    """Verifica che in assenza di lista modelli il prompt text libero funzioni con conferma."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        m.ask.return_value = "deepseek"
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "ID Modello" in prompt:
            m.ask.return_value = "deepseek-reasoner"
        else:
            m.ask.return_value = default or "prof4"
        return m

    def mock_confirm(prompt, default=True):
        m = MagicMock()
        if "confermi" in prompt:
            m.ask.return_value = True
        else:
            m.ask.return_value = False
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "key123"
        return m

    with patch("questionary.confirm", side_effect=mock_confirm), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", side_effect=requests.RequestException("Timeout")):

        name, prof = _create_new_model_profile(config_dir, env_file, {"version": "2.0.0"})

    assert prof["routes"][0]["model"] == "deepseek-reasoner"


def test_models_management_zero_profiles(tmp_path, monkeypatch):
    """Verifica che run_models_management con zero profili esca senza cicli infiniti."""
    fake_cwd = str(tmp_path / "workdir")
    os.makedirs(fake_cwd, exist_ok=True)
    monkeypatch.chdir(fake_cwd)
    config_dir = os.path.join(fake_cwd, "config")
    os.makedirs(config_dir, exist_ok=True)
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0", "model_profiles": {}}, f)

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, str(tmp_path / ".env"))):
        run_models_management()


def test_models_management_rename_profile(tmp_path):
    """Verifica la rinominazione di un profilo salvato tramite il menu rt config --models."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "version": "2.0.0",
            "model_profiles": {
                "fast_profile": {
                    "provider": "openrouter",
                    "routes": [{"credential": "or_1", "model": "openai/gpt-4o"}]
                }
            }
        }, f)

    select_calls = 0
    op_calls = 0

    def mock_select(prompt, choices, default=None):
        nonlocal select_calls, op_calls
        m = MagicMock()
        if "seleziona per modificare" in prompt:
            select_calls += 1
            m.ask.return_value = "fast_profile" if select_calls == 1 else "⏭ Esci"
        elif "Operazione su profilo" in prompt:
            op_calls += 1
            m.ask.return_value = "✏️ Rinomina profilo" if op_calls == 1 else "⏭ Torna alla lista"
        else:
            m.ask.return_value = choices[0]
        return m

    def mock_text(prompt, default=None, **kwargs):
        m = MagicMock()
        if "Nuovo nome" in prompt:
            m.ask.return_value = "turbo_profile"
        else:
            m.ask.return_value = default or ""
        return m

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, env_file)), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text):
        run_models_management()

    with open(general_file, "r", encoding="utf-8") as f:
        gdata = yaml.safe_load(f)

    assert "fast_profile" not in gdata["model_profiles"]
    assert "turbo_profile" in gdata["model_profiles"]
    assert gdata["model_profiles"]["turbo_profile"]["provider"] == "openrouter"


def test_models_management_delete_profile(tmp_path):
    """Verifica l'eliminazione con conferma di un profilo dal menu rt config --models."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "version": "2.0.0",
            "model_profiles": {
                "to_delete": {
                    "provider": "google",
                    "routes": [{"credential": "g_1", "model": "gemini-flash"}]
                }
            }
        }, f)

    def mock_select(prompt, choices, default=None):
        m = MagicMock()
        if "seleziona per modificare" in prompt:
            m.ask.return_value = "to_delete"
        elif "Operazione su profilo" in prompt:
            m.ask.return_value = "🗑️ Elimina profilo"
        else:
            m.ask.return_value = choices[0]
        return m

    def mock_confirm(prompt, default=False):
        m = MagicMock()
        m.ask.return_value = True
        return m

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, env_file)), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.confirm", side_effect=mock_confirm):
        run_models_management()

    with open(general_file, "r", encoding="utf-8") as f:
        gdata = yaml.safe_load(f)

    assert "to_delete" not in gdata.get("model_profiles", {})


def test_models_management_update_api_key(tmp_path):
    """Verifica l'aggiornamento dell'API key di un profilo esistente nel file .env."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")
    general_file = os.path.join(config_dir, "general.yaml")
    with open(general_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "version": "2.0.0",
            "credentials": [{"name": "deepseek_1", "provider": "deepseek", "env_var": "DEEPSEEK_API_KEY"}],
            "model_profiles": {
                "ds_profile": {
                    "provider": "deepseek",
                    "routes": [{"credential": "deepseek_1", "model": "deepseek-chat"}]
                }
            }
        }, f)

    select_calls = 0
    op_calls = 0

    def mock_select(prompt, choices, default=None):
        nonlocal select_calls, op_calls
        m = MagicMock()
        if "seleziona per modificare" in prompt:
            select_calls += 1
            m.ask.return_value = "ds_profile" if select_calls == 1 else "⏭ Esci"
        elif "Operazione su profilo" in prompt:
            op_calls += 1
            m.ask.return_value = "🔑 Aggiorna API key" if op_calls == 1 else "⏭ Torna alla lista"
        else:
            m.ask.return_value = choices[0]
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-new-secret-key-999"
        return m

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, env_file)), \
         patch("questionary.select", side_effect=mock_select), \
         patch("questionary.password", side_effect=mock_password):
        run_models_management()

    with open(env_file, "r", encoding="utf-8") as f:
        env_content = f.read()

    assert "DEEPSEEK_API_KEY=sk-new-secret-key-999" in env_content


def test_run_telegram_only(tmp_path):
    """Verifica che rt config --telegram invochi la sezione Telegram senza toccare profili o file job.yaml."""
    config_dir = str(tmp_path / "config")
    os.makedirs(config_dir, exist_ok=True)
    env_file = str(tmp_path / ".env")

    outline_job = os.path.join(config_dir, "outline.yaml")
    job_content = "primary:\n  provider: google\n  model: gemini\n"
    with open(outline_job, "w", encoding="utf-8") as f:
        f.write(job_content)

    mock_tg = MagicMock(return_value={"configured": True})

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, env_file)), \
         patch("rt.pipeline.configure._configure_telegram_section", mock_tg):
        run_telegram_only()

    mock_tg.assert_called_once_with(config_dir, env_file)

    # Il file job non dev'essere modificato
    with open(outline_job, "r", encoding="utf-8") as f:
        assert f.read() == job_content


def test_configure_config_parser_mutually_exclusive():
    """Verifica che --models e --telegram siano mutuamente esclusivi nel CLI parser."""
    import argparse
    parser = argparse.ArgumentParser()
    configure_config_parser(parser)

    args_models = parser.parse_args(["--models"])
    assert args_models.models is True
    assert args_models.telegram is False

    args_telegram = parser.parse_args(["--telegram"])
    assert args_telegram.models is False
    assert args_telegram.telegram is True

    with pytest.raises(SystemExit):
        parser.parse_args(["--models", "--telegram"])



