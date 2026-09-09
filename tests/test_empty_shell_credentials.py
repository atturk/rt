"""
tests/test_empty_shell_credentials.py
Test di accettazione per:
- Config out-of-the-box come guscio vuoto (provider/model a None)
- Assenza di credenziali pre-registrate o scorciatoie hardcoded in produzione
- Riconoscimento dello stato di route non configurata vs route a metà (errore)
- Controlli preventivi CLI con messaggi chiari
"""

import os
import sys
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.llm.credentials import CredentialRegistry, CredentialRef
from rt.core.config import RouteConfig, JobRoutingConfig, _load_config_dir, load_config
from rt.cli import _job_has_configured_route, cmd_outline, cmd_rewrite, cmd_review_asr, cmd_review_science, cmd_run


def test_no_built_in_shortcuts_in_clean_registry():
    """1. In un registry pulito, non ci sono credenziali per openrouter/deepseek/google pre-registrate."""
    registry = CredentialRegistry()
    assert registry.validate_credential("openrouter", "openrouter") is False
    assert registry.validate_credential("deepseek", "deepseek") is False
    assert registry.validate_credential("google", "google_1") is False
    assert registry.validate_credential("google", "google_2") is False
    assert registry.validate_credential("mock", "mock") is True
    assert registry.get_default_credential_for_provider("openrouter") is None
    assert registry.get_default_credential_for_provider("deepseek") is None
    assert registry.get_default_credential_for_provider("google") is None
    assert registry.get_default_credential_for_provider("mock") == "mock"


def test_empty_route_does_not_crash():
    """2. RouteConfig con provider=None e model=None non solleva eccezioni ed è is_configured=False."""
    route = RouteConfig(provider=None, model=None)
    assert route.provider is None
    assert route.model is None
    assert route.is_configured is False


def test_half_configured_route_raises_error():
    """3. RouteConfig con provider impostato ma model mancante o vuoto solleva ValueError."""
    with pytest.raises(ValueError, match="Il modello per il provider 'openrouter' non può essere vuoto"):
        RouteConfig(provider="openrouter", model=None)

    with pytest.raises(ValueError, match="Il modello per il provider 'openrouter' non può essere vuoto"):
        RouteConfig(provider="openrouter", model="")


def test_route_with_unregistered_credential_raises_error():
    """4. RouteConfig con provider reale e credenziale esplicita non registrata solleva ValueError."""
    clean_registry = CredentialRegistry()
    with patch("rt.llm.credentials.GLOBAL_CREDENTIALS", clean_registry):
        with pytest.raises(ValueError, match="non valida o incompatibile"):
            RouteConfig(provider="openrouter", model="test-model", credential="openrouter")


def test_original_build_default_jobs_is_empty_shell():
    """Verifica che i default di produzione _build_default_jobs siano un guscio vuoto (provider/model a None)."""
    from tests.conftest import ORIGINAL_BUILD_DEFAULT_JOBS
    jobs = ORIGINAL_BUILD_DEFAULT_JOBS()
    for job_name in ("outline", "rewrite", "review_asr", "review_science",
                     "recall_quiz", "recall_mirata", "recall_vasta"):
        assert job_name in jobs
        assert jobs[job_name].primary.provider is None
        assert jobs[job_name].primary.model is None
        assert jobs[job_name].primary.is_configured is False


def test_config_example_loads_as_empty_shell():
    """5. config.example/ si carica senza eccezioni e produce per ciascuno dei 7 job is_configured=False."""
    cfg = _load_config_dir("config.example")
    assert cfg.version == "2.0.0"
    for job_name in ("outline", "rewrite", "review_asr", "review_science",
                     "recall_quiz", "recall_mirata", "recall_vasta"):
        job_cfg = cfg.jobs.get(job_name)
        assert job_cfg is not None, f"job '{job_name}' mancante in config.example/"
        assert job_cfg.primary is not None
        assert job_cfg.primary.provider is None
        assert job_cfg.primary.model is None
        assert job_cfg.primary.is_configured is False


def test_job_has_configured_route_helper():
    """6. _job_has_configured_route restituisce True solo se il job ha una route primaria configurata."""
    assert _job_has_configured_route(None) is False
    assert _job_has_configured_route(JobRoutingConfig(primary=RouteConfig(provider=None, model=None))) is False
    configured_job = JobRoutingConfig(
        primary=RouteConfig(
            provider="openai_compatible",
            model="local-model",
            base_url="http://localhost:11434/v1"
        )
    )
    assert _job_has_configured_route(configured_job) is True


def _create_unconfigured_config_dir(config_dir_path):
    """Crea una cartella config/ con general.yaml e 4 job privi di provider/model."""
    os.makedirs(config_dir_path, exist_ok=True)
    general_yaml = {
        "version": "2.0.0",
        "mock_llm": False,
        "streaming": True,
        "show_monitor": False,
        "credentials": [
            {"name": "test_cred", "provider": "openrouter", "env_var": "TEST_KEY"}
        ]
    }
    with open(os.path.join(config_dir_path, "general.yaml"), "w") as f:
        yaml.safe_dump(general_yaml, f)

    for job in ("outline", "rewrite", "review_asr", "review_science"):
        job_yaml = {
            "round_robin": False,
            "max_attempts": 3,
            "primary": {
                "provider": None,
                "credential": None,
                "model": None,
                "base_url": None,
                "thinking": True,
                "reasoning_effort": "low",
                "timeout_seconds": 120,
            }
        }
        with open(os.path.join(config_dir_path, f"{job}.yaml"), "w") as f:
            yaml.safe_dump(job_yaml, f)


def test_cli_single_job_commands_abort_when_unconfigured(tmp_path, monkeypatch, capsys):
    """7a. I 4 comandi a job singolo abortiscono con SystemExit(1) e messaggio esplicito se il job non ha provider."""
    monkeypatch.chdir(tmp_path)
    _create_unconfigured_config_dir(tmp_path / "config")

    args = MagicMock()
    args.mock = False
    args.lesson_dir = str(tmp_path / "lesson")
    args.force = False
    args.unit = None

    # outline
    with pytest.raises(SystemExit) as exc:
        cmd_outline(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Il job 'outline' non ha alcun provider configurato in config/outline.yaml" in captured.err

    # rewrite
    with pytest.raises(SystemExit) as exc:
        cmd_rewrite(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Il job 'rewrite' non ha alcun provider configurato in config/rewrite.yaml" in captured.err

    # review_asr
    with pytest.raises(SystemExit) as exc:
        cmd_review_asr(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Il job 'review_asr' non ha alcun provider configurato in config/review_asr.yaml" in captured.err

    # review_science
    with pytest.raises(SystemExit) as exc:
        cmd_review_science(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Il job 'review_science' non ha alcun provider configurato in config/review_science.yaml" in captured.err


def test_cli_cmd_run_reports_all_missing_jobs(tmp_path, monkeypatch, capsys):
    """7b. cmd_run elenca TUTTI i job mancanti prima di iniziare qualsiasi lavoro."""
    monkeypatch.chdir(tmp_path)
    _create_unconfigured_config_dir(tmp_path / "config")

    # Configuriamo solo 'outline' e 'rewrite', lasciando non configurati 'review_asr' e 'review_science'
    for job in ("outline", "rewrite"):
        job_yaml = {
            "round_robin": False,
            "max_attempts": 3,
            "primary": {
                "provider": "openai_compatible",
                "model": "model-1",
                "base_url": "http://localhost:11434/v1",
                "thinking": True,
                "reasoning_effort": "low",
                "timeout_seconds": 120,
            }
        }
        with open(tmp_path / "config" / f"{job}.yaml", "w") as f:
            yaml.safe_dump(job_yaml, f)

    args = MagicMock()
    args.mock = False
    args.input = [str(tmp_path / "lesson")]
    args.force = False

    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "I seguenti job non hanno un provider configurato: review_asr, review_science" in captured.err


def test_cli_commands_bypass_when_mock_flag(tmp_path, monkeypatch):
    """8. Con --mock, nessun controllo di configurazione/provider blocca l'esecuzione."""
    monkeypatch.chdir(tmp_path)
    _create_unconfigured_config_dir(tmp_path / "config")

    args = MagicMock()
    args.mock = True
    args.lesson_dir = str(tmp_path / "lesson")
    args.force = False
    args.unit = None

    with patch("rt.cli.run_outline", return_value={"status": "ok", "action": "RUN"}), \
         patch("rt.cli.confirm_or_revise_outline", return_value=None), \
         patch("rt.cli._print_phase_action"):
        cmd_outline(args)

    with patch("rt.cli.run_rewrite", return_value={"status": "ok", "action": "RUN"}), \
         patch("rt.cli._print_phase_action"):
        cmd_rewrite(args)
