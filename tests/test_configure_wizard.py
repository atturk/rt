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
    _configure_llm_provider_section,
    run_config_wizard
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
        return m

    def mock_text(prompt, default=None):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""  # Usa default
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-deepseek-secret-123"
        return m

    # Mock HTTP response per /models
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]
    }

    with patch("questionary.select", side_effect=mock_select), \
         patch("questionary.text", side_effect=mock_text), \
         patch("questionary.password", side_effect=mock_password), \
         patch("requests.get", return_value=mock_resp):

        _configure_llm_provider_section(config_dir, env_file)

    # Verifiche: .env contiene DEEPSEEK_API_KEY
    with open(env_file, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "DEEPSEEK_API_KEY=sk-deepseek-secret-123" in env_content

    # general.yaml contiene credenziale deepseek_1
    with open(general_file, "r", encoding="utf-8") as f:
        gen_data = yaml.safe_load(f)
    assert len(gen_data["credentials"]) == 1
    assert gen_data["credentials"][0]["name"] == "deepseek_1"
    assert gen_data["credentials"][0]["provider"] == "deepseek"
    assert gen_data["credentials"][0]["env_var"] == "DEEPSEEK_API_KEY"

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
        return m

    def mock_text(prompt, default=None):
        m = MagicMock()
        if "Base URL" in prompt:
            m.ask.return_value = ""
        elif "ID Modello" in prompt:
            m.ask.return_value = "anthropic/claude-3.5-sonnet"
        return m

    def mock_password(prompt, default=None):
        m = MagicMock()
        m.ask.return_value = "sk-or-test"
        return m

    # Mock HTTP failure (timeout / ConnectionError)
    with patch("questionary.select", side_effect=mock_select), \
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

