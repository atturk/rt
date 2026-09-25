"""
Unit test per Task 38: schermata a blocchi navigabili per fase e conferma finale in configure.py.
"""

import os
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.tui.configure import (
    _configure_pricing_section,
    _build_configure_roles_app,
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


@pytest.mark.anyio
async def test_phase_blocks_navigation_and_confirmation(tmp_path):
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

    with patch("rt.tui.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # 1. Card outline: "RIGHT" (passa a rewrite)
            await pilot.press("right")
            # 2. Card rewrite: "LEFT" (torna ad outline)
            await pilot.press("left")
            # 3. Card outline: "DOWN", "DOWN" (va su test_prof_1), "ENTER" (seleziona test_prof_1)
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            # 4. Card outline: "c" (salta alla card finale di conferma)
            await pilot.press("c")
            # 5. Card conferma: "ENTER" (conferma ed applica)
            await pilot.press("enter")

    # Verifica che la conferma abbia effettivamente applicato il profilo al file job outline.yaml
    assert app.result_assignments is not None
    assert app.result_assignments.get("outline") == "test_prof_1"
    with open(outline_job_file, "r", encoding="utf-8") as f:
        updated_job = yaml.safe_load(f)
    assert updated_job["primary"]["model"] == "openrouter/free"


@pytest.mark.anyio
async def test_phase_blocks_no_write_until_confirmation(tmp_path):
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

    with patch("rt.tui.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # Sequenza: "DOWN", "DOWN", "ENTER", "c" (va al riepilogo), "DOWN", "DOWN", "ENTER" (Annulla)
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("c")
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")

    assert app.result_assignments is None
    # Verifica che il file job sia rimasto inalterato!
    with open(outline_job_file, "r", encoding="utf-8") as f:
        unchanged_job = yaml.safe_load(f)
    assert unchanged_job["primary"]["model"] == "old_model"
