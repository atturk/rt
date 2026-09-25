"""
tests/test_task53.py
Unit & integration tests for Task 53: Config wizard UI for per-phase fallback models (rt config).
"""

import os
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.tui.configure import (
    _configure_llm_provider_section,
    _apply_profile_to_job,
    _apply_fallback_to_job,
    _ask_and_assign_role,
    _find_matching_profile_for_single_route,
)
from rt.llm.errors import RateLimitFailure, SafetyFailure, TimeoutFailure
from rt.llm.router import RoutingEngine
from rt.core.config import JobRoutingConfig


def test_role_constraint_primary_and_fallback_mutual_exclusion(capsys):
    """Verifica che un modello non possa essere contemporaneamente Primario e Fallback nella stessa fase."""
    # 1. Profilo già primario, tentativo di assegnarlo a fallback
    phase_map = {
        "primary": "google_flash",
        "timeout": None,
        "rate_limit": None,
        "safety": None,
        "auth": None,
        "generic": None,
    }

    # Simula utente che prima tenta 'Fallback: rate-limit (429)' (rifiutato) poi '❌ Annulla'
    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.side_effect = [
            "Fallback: rate-limit (429)",
            "❌ Annulla",
        ]
        res = _ask_and_assign_role("google_flash", "outline", phase_map)

    assert res is False
    assert phase_map["rate_limit"] is None
    captured = capsys.readouterr().out
    assert "Un modello non può essere contemporaneamente Primario e Fallback" in captured

    # 2. Profilo già fallback, tentativo di assegnarlo a primario
    phase_map2 = {
        "primary": None,
        "timeout": None,
        "rate_limit": "openrouter_glm",
        "safety": None,
        "auth": None,
        "generic": None,
    }

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.side_effect = [
            "Primario",
            "❌ Annulla",
        ]
        res2 = _ask_and_assign_role("openrouter_glm", "outline", phase_map2)

    assert res2 is False
    assert phase_map2["primary"] is None
    captured2 = capsys.readouterr().out
    assert "Un modello non può essere contemporaneamente Primario e Fallback" in captured2


def test_same_profile_can_be_assigned_to_multiple_fallback_slots():
    """Verifica che lo STESSO profilo possa coprire più ruoli di fallback diversi nella stessa fase."""
    phase_map = {
        "primary": "google_flash",
        "timeout": None,
        "rate_limit": None,
        "safety": None,
        "auth": None,
        "generic": None,
    }

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.return_value = "Fallback: rate-limit (429)"
        res1 = _ask_and_assign_role("openrouter_glm", "outline", phase_map)

    assert res1 is True
    assert phase_map["rate_limit"] == "openrouter_glm"

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.return_value = "Fallback: generico (qualunque altro errore)"
        res2 = _ask_and_assign_role("openrouter_glm", "outline", phase_map)

    assert res2 is True
    assert phase_map["generic"] == "openrouter_glm"
    assert phase_map["rate_limit"] == "openrouter_glm"


@pytest.mark.anyio
async def test_confirm_and_apply_writes_fallback_block_to_job_yaml(tmp_path):
    """Verifica che Conferma e applica scriva sia primary sia fallback: nel file YAML del job."""
    from rt.tui.configure import _build_configure_roles_app

    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_yaml_path = os.path.join(config_dir, "general.yaml")
    general_data = {
        "credentials": [
            {"provider": "google", "name": "google_1", "env_var": "GOOGLE_API_KEY_1"},
            {"provider": "openrouter", "name": "openrouter_1", "env_var": "OPENROUTER_API_KEY"},
        ],
        "model_profiles": {
            "prof_google": {
                "provider": "google",
                "round_robin": False,
                "routes": [{"credential": "google_1", "model": "gemini-2.5-flash"}]
            },
            "prof_openrouter": {
                "provider": "openrouter",
                "round_robin": False,
                "routes": [{"credential": "openrouter_1", "model": "glm-5.3-flash"}]
            }
        }
    }
    with open(general_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general_data, f)

    job_dir = os.path.join(config_dir, "jobs")
    os.makedirs(job_dir, exist_ok=True)
    outline_job_file = os.path.join(job_dir, "outline.yaml")
    initial_job = {"primary": {"provider": "google", "model": "old_model"}}
    with open(outline_job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_job, f)

    select_roles = [
        "Primario",
        "Fallback: rate-limit (429)",
    ]

    with patch("rt.tui.configure.find_job_yaml_paths", return_value={"outline": outline_job_file}), \
         patch("questionary.select") as mock_q:
        mock_q.return_value.ask.side_effect = select_roles
        app = _build_configure_roles_app(config_dir, env_path)
        assert app is not None
        async with app.run_test() as pilot:
            # Seleziona prof_google (indice 2)
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            # In nuova lista scelte, cursore è su prof_openrouter (indice 2)
            await pilot.press("enter")
            # Salta a conferma
            await pilot.press("c")
            # Conferma
            await pilot.press("enter")

    assert app.result_assignments is not None
    assert app.result_assignments.get("outline") == "prof_google"
    with open(outline_job_file, "r", encoding="utf-8") as f:
        saved_job = yaml.safe_load(f)

    assert saved_job["primary"]["model"] == "gemini-2.5-flash"
    assert "fallback" in saved_job
    assert saved_job["fallback"]["rate_limit"]["model"] == "glm-5.3-flash"
    assert saved_job["fallback"]["rate_limit"]["provider"] == "openrouter"


def test_remove_single_fallback_assignment(tmp_path):
    """Verifica che rimuovere un'assegnazione di fallback svuoti solo quello slot lasciando invariati gli altri."""
    job_file = os.path.join(tmp_path, "outline.yaml")
    job_content = {
        "primary": {"provider": "google", "model": "gemini-2.5-flash", "credential": "google_1"},
        "fallback": {
            "rate_limit": {"provider": "openrouter", "model": "glm-5.3-flash", "credential": "openrouter_1"},
            "timeout": {"provider": "deepseek", "model": "deepseek-chat", "credential": "deepseek_1"}
        }
    }
    with open(job_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(job_content, f)

    # Rimuove solo rate_limit
    _apply_fallback_to_job(job_file, "rate_limit", None)

    with open(job_file, "r", encoding="utf-8") as f:
        updated = yaml.safe_load(f)

    assert updated["primary"]["model"] == "gemini-2.5-flash"
    assert "rate_limit" not in updated["fallback"]
    assert updated["fallback"]["timeout"]["model"] == "deepseek-chat"


def test_e2e_select_fallback_route_with_wizard_output(tmp_path):
    """Verifica che LLMRoutingEngine risolva correttamente le route di fallback scritte su disco."""
    from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef

    GLOBAL_CREDENTIALS.register(CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"))
    GLOBAL_CREDENTIALS.register(CredentialRef(name="openrouter_1", provider="openrouter", env_var="OPENROUTER_API_KEY"))
    GLOBAL_CREDENTIALS.register(CredentialRef(name="deepseek_1", provider="deepseek", env_var="DEEPSEEK_API_KEY"))

    job_data = {
        "max_attempts": 5,
        "primary": {"provider": "google", "model": "gemini-2.5-flash", "credential": "google_1"},
        "fallback": {
            "rate_limit": {"provider": "openrouter", "model": "glm-5.3-flash", "credential": "openrouter_1"},
            "generic": {"provider": "deepseek", "model": "deepseek/deepseek-v4-pro", "credential": "deepseek_1"},
        }
    }

    os.environ["GOOGLE_API_KEY_1"] = "fake-g"
    os.environ["OPENROUTER_API_KEY"] = "fake-or"
    os.environ["DEEPSEEK_API_KEY"] = "fake-ds"

    from rt.core.config import RTConfig

    router = RoutingEngine(RTConfig(jobs={"outline": JobRoutingConfig(**job_data)}))
    # 1. Rate limit failure -> Fallback mirato su openrouter/glm-5.3-flash
    exec_route_rl = router.select_fallback_route(
        job_name="outline",
        failure=RateLimitFailure("429 Too Many Requests"),
        visited_route_ids={"google|gemini-2.5-flash|google_1"},
        current_attempt=1
    )
    assert exec_route_rl is not None
    assert exec_route_rl.route.provider == "openrouter"
    assert exec_route_rl.route.model == "glm-5.3-flash"
    assert exec_route_rl.route_role == "fallback_rate_limit"

    # 2. Safety failure (nessun safety slot, fallback su generic deepseek)
    exec_route_safety = router.select_fallback_route(
        job_name="outline",
        failure=SafetyFailure("Safety block"),
        visited_route_ids={"google|gemini-2.5-flash|google_1"},
        current_attempt=1
    )
    assert exec_route_safety is not None
    assert exec_route_safety.route.provider == "deepseek"
    assert exec_route_safety.route.model == "deepseek/deepseek-v4-pro"
    assert exec_route_safety.route_role == "fallback_safety"


