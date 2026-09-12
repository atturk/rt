"""
Unit test per Task 38: schermata a blocchi navigabili per fase e conferma finale in configure.py.
"""

import os
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.configure import (
    _configure_llm_provider_section,
    _configure_pricing_section
)


def test_pricing_section_no_decorative_box(tmp_path, capsys):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)

    with patch("questionary.confirm") as mock_conf:
        mock_conf.return_value.ask.return_value = False
        _configure_pricing_section(config_dir, "deepseek", "deepseek-chat")

    captured = capsys.readouterr().out
    assert "💰 4. Configurazione Pricing Custom" not in captured
    assert "------------------------------------------------------------" not in captured


def test_phase_blocks_navigation_and_confirmation(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data = {
        "model_profiles": {
            "test_prof_1": {
                "provider": "openrouter",
                "round_robin": False,
                "routes": [{"credential": "openrouter_1", "model": "openrouter/free"}]
            }
        }
    }
    with open(general_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general_data, f)

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    rewrite_job_file = os.path.join(job_dir, "rewrite.yaml")
    initial_job_content = {"primary": {"provider": "openrouter", "model": "old_model"}}
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job_content, f)
    with open(rewrite_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job_content, f)

    # Sequenza mock con 2 job:
    # 1. Fase 1 (outline): seleziona '➡️ Fase successiva'
    # 2. Fase 2 (rewrite): seleziona '⬅️ Fase precedente'
    # 3. Fase 1 (outline): seleziona 'test_prof_1' (passa automaticamente alla Fase 2 rewrite)
    # 4. Fase 2 (rewrite): seleziona '📋 Vai al riepilogo e conferma'
    # 5. Riepilogo: seleziona '✅ Conferma e applica configurazione'
    select_responses = [
        "➡️ Fase successiva",
        "⬅️ Fase precedente",
        "test_prof_1",
        "📋 Vai al riepilogo e conferma",
        "✅ Conferma e applica configurazione"
    ]

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        with patch("questionary.select") as mock_sel:
            mock_sel.return_value.ask.side_effect = select_responses
            res = _configure_llm_provider_section(config_dir, env_path)

    # Verifica che la conferma abbia effettivamente applicato il profilo al file job outline.yaml
    assert res.get("outline") == "test_prof_1"
    with open(outline_job_file, "r", encoding="utf-8") as f:
        updated_job = yaml.safe_load(f)
    assert updated_job["primary"]["model"] == "openrouter/free"


def test_phase_blocks_no_write_until_confirmation(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data = {
        "model_profiles": {
            "test_prof_1": {
                "provider": "openrouter",
                "round_robin": False,
                "routes": [{"credential": "openrouter_1", "model": "openrouter/free"}]
            }
        }
    }
    with open(general_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general_data, f)

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    initial_job_content = {"primary": {"provider": "openrouter", "model": "old_model"}}
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job_content, f)

    # Sequenza: seleziona 'test_prof_1' ma al riepilogo sceglie '❌ Annulla configurazione modelli'
    select_responses = [
        "test_prof_1",
        "❌ Annulla configurazione modelli"
    ]

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        with patch("questionary.select") as mock_sel:
            mock_sel.return_value.ask.side_effect = select_responses
            res = _configure_llm_provider_section(config_dir, env_path)

    assert res == {}
    # Verifica che il file job sia rimasto inalterato!
    with open(outline_job_file, "r", encoding="utf-8") as f:
        unchanged_job = yaml.safe_load(f)
    assert unchanged_job["primary"]["model"] == "old_model"
