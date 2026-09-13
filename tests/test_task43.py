"""
tests/test_task43.py
Unit & integration tests for Task 43: Literal card carousel UI in rt config (_configure_llm_provider_section).
"""

import os
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.configure import (
    _configure_pricing_section,
    _build_configure_roles_app,
    ConfigurePhaseRolesApp,
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
async def test_phase_cards_navigation_and_confirmation(tmp_path):
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

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # 1. Card outline: "right" (passa a rewrite)
            await pilot.press("right")
            # 2. Card rewrite: "left" (torna ad outline)
            await pilot.press("left")
            # 3. Card outline: "down", "down" (va su test_prof_1), "enter" (seleziona test_prof_1 come primario)
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            # 4. Card outline: "c" (salta alla card finale di conferma)
            await pilot.press("c")
            # 5. Card conferma: "enter" (conferma ed applica)
            await pilot.press("enter")

    assert app.result_assignments is not None
    assert app.result_assignments.get("outline") == "test_prof_1"
    with open(outline_job_file, "r", encoding="utf-8") as f:
        updated_job = yaml.safe_dump(yaml.safe_load(f))
    assert "openrouter/free" in updated_job


@pytest.mark.anyio
async def test_phase_cards_no_write_until_confirmation(tmp_path):
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

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # DOWN -> DOWN -> ENTER -> c (va a conferma) -> DOWN -> DOWN -> ENTER (Annulla)
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("c")
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")

    assert app.result_assignments is None
    with open(outline_job_file, "r", encoding="utf-8") as f:
        unchanged_job = yaml.safe_load(f)
    assert unchanged_job["primary"]["model"] == "old_model"


@pytest.mark.anyio
async def test_phase_cards_create_new_profile(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    initial_job_content = {"primary": {"provider": "openrouter", "model": "old_model"}}
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job_content, f)

    new_profile_dict = {
        "provider": "google",
        "round_robin": False,
        "routes": [{"credential": "google_1", "model": "gemini-2.5-flash"}]
    }

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        with patch("rt.pipeline.configure._create_new_model_profile", return_value=("new_gemini", new_profile_dict, "primary")) as mock_create:
            async with app.run_test() as pilot:
                # DOWN -> DOWN -> ENTER (NEW_PROFILE) -> c -> ENTER (conferma)
                await pilot.press("down")
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.press("c")
                await pilot.press("enter")

    mock_create.assert_called_once()
    assert app.result_assignments is not None
    assert app.result_assignments.get("outline") == "new_gemini"


@pytest.mark.anyio
async def test_phase_cards_cursor_preserved_across_cards(tmp_path):
    """Verifica che navigando tra card con LEFT/RIGHT l'indice del cursore sia memorizzato per ciascuna card."""
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    rewrite_job_file = os.path.join(job_dir, "rewrite.yaml")
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": "openrouter", "model": "old_model"}}, f)
    with open(rewrite_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": "openrouter", "model": "old_model"}}, f)

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # Card 0: sposta cursore giù di 1
            await pilot.press("down")
            assert app.option_indices.get(0) == 1
            # Passa a Card 1: muovi cursore giù di 2
            await pilot.press("right")
            assert app.curr_idx == 1
            await pilot.press("down")
            await pilot.press("down")
            assert app.option_indices.get(1) == 2
            # Torna a Card 0: verifica che l'indice salvato sia ancora 1
            await pilot.press("left")
            assert app.curr_idx == 0
            assert app.option_indices.get(0) == 1


@pytest.mark.anyio
async def test_phase_cards_remove_assigned_role(tmp_path):
    """Verifica che la selezione REMOVE_LABEL rimuova l'assegnazione indicata."""
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": "openrouter", "model": "old_model"}}, f)

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        app.pending_selections["outline"]["primary"] = "prof_a"
        # REMOVE_LABEL dovrebbe comparire tra le scelte
        choices = app._get_choices_for_card(0)
        assert app.REMOVE_LABEL in choices
        remove_idx = choices.index(app.REMOVE_LABEL)

        with patch("questionary.select") as mock_sel:
            mock_sel.return_value.ask.return_value = "Primario: prof_a"
            async with app.run_test() as pilot:
                # Sposta cursore su REMOVE_LABEL
                for _ in range(remove_idx):
                    await pilot.press("down")
                await pilot.press("enter")

        assert app.pending_selections["outline"]["primary"] is None


@pytest.mark.anyio
async def test_confirmation_screen_modify_phase_returns_to_card(tmp_path):
    """Verifica che l'opzione 'Modifica una fase' dalla schermata di conferma riporti alla card della fase scelta."""
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    rewrite_job_file = os.path.join(job_dir, "rewrite.yaml")
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": "openrouter", "model": "old_model"}}, f)
    with open(rewrite_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"primary": {"provider": "openrouter", "model": "old_model"}}, f)

    with patch("rt.pipeline.configure.find_job_yaml_paths", return_value={"outline": outline_job_file, "rewrite": rewrite_job_file}):
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        with patch("questionary.select") as mock_sel:
            mock_sel.return_value.ask.return_value = "rewrite"
            async with app.run_test() as pilot:
                # Salta a conferma con 'c'
                await pilot.press("c")
                assert app.curr_idx == 2  # Total groups = 2
                # Seleziona opzione 2 ("✏️ Modifica una fase specificata")
                await pilot.press("down")
                assert app.confirm_option_idx == 1
                await pilot.press("enter")
                # Verifica che curr_idx sia stato impostato all'indice di rewrite (1)
                assert app.curr_idx == 1
