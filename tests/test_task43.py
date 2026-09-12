"""
tests/test_task43.py
Unit & integration tests for Task 43: Literal card carousel UI in rt config (_configure_llm_provider_section).
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


def test_phase_cards_navigation_and_confirmation(tmp_path):
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

    # Sequenza tasti:
    # 1. Card outline: "RIGHT" (passa a rewrite)
    # 2. Card rewrite: "LEFT" (torna ad outline)
    # 3. Card outline: "DOWN" (va su test_prof_1), "ENTER" (seleziona test_prof_1)
    # 4. Card outline: "c" (salta alla card finale di conferma)
    # 5. Card conferma: "ENTER" (conferma ed applica)
    key_sequence = [
        "RIGHT",
        "LEFT",
        "DOWN",
        "DOWN",
        "ENTER",
        "c",
        "ENTER"
    ]

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        with patch("rt.pipeline.configure.read_single_key", side_effect=key_sequence):
            res = _configure_llm_provider_section(config_dir, env_path)

    assert res.get("outline") == "test_prof_1"
    with open(outline_job_file, "r", encoding="utf-8") as f:
        updated_job = yaml.safe_dump(yaml.safe_load(f))
    assert "openrouter/free" in updated_job


def test_phase_cards_no_write_until_confirmation(tmp_path):
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

    # Sequenza: "DOWN", "DOWN", "ENTER", "c" (va a conferma), "DOWN", "DOWN", "ENTER" (Annulla)
    key_sequence = [
        "DOWN",
        "DOWN",
        "ENTER",
        "c",
        "DOWN",
        "DOWN",
        "ENTER"
    ]

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        with patch("rt.pipeline.configure.read_single_key", side_effect=key_sequence):
            res = _configure_llm_provider_section(config_dir, env_path)

    assert res == {}
    with open(outline_job_file, "r", encoding="utf-8") as f:
        unchanged_job = yaml.safe_load(f)
    assert unchanged_job["primary"]["model"] == "old_model"


def test_phase_cards_create_new_profile(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    initial_job_content = {"primary": {"provider": "openrouter", "model": "old_model"}}
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job_content, f)

    # Card choices when initial job has unrecognized config and no profiles exist:
    # [keep_label, SKIP_LABEL, NEW_PROFILE]
    # DOWN -> DOWN -> NEW_PROFILE -> ENTER -> calls _create_new_model_profile
    # Then "c" -> ENTER (conferma)
    key_sequence = [
        "DOWN",
        "DOWN",
        "ENTER",
        "c",
        "ENTER"
    ]

    new_profile_dict = {
        "provider": "google",
        "round_robin": False,
        "routes": [{"credential": "google_1", "model": "gemini-2.5-flash"}]
    }

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        with patch("rt.pipeline.configure.read_single_key", side_effect=key_sequence):
            with patch("rt.pipeline.configure._create_new_model_profile", return_value=("new_gemini", new_profile_dict)) as mock_create:
                res = _configure_llm_provider_section(config_dir, env_path)

    mock_create.assert_called_once()
    assert res.get("outline") == "new_gemini"
