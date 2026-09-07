"""
tests/test_prices_interactive.py
Test di accettazione per 'rt prices-check --interactive':
1. Tracciamento path in collect_configured_routes (primary, secondary, primary_routes, fallback)
2. Scrittura end-to-end con mock questionary
3. Preservazione commenti e formattazione con ruamel.yaml
4. Nessuna voce applicabile
5. Utente annulla (Ctrl+C / None)
6. Guard _has_real_config_source senza cartella config/
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from ruamel.yaml import YAML
import argparse

from rt.core.config import RouteConfig, JobRoutingConfig, JobFallbackConfig, RTConfig
from rt.llm.pricing_sync import collect_configured_routes, check_configured_pricing
from rt.cli import cmd_prices_check


def test_collect_configured_routes_path_tracking():
    """1. Verifica che ogni voce restituita contenga la chiave 'path' corretta."""
    cfg = RTConfig(
        jobs={
            "outline": JobRoutingConfig(
                primary=RouteConfig(provider="deepseek", model="deepseek-v4-flash"),
                secondary=RouteConfig(provider="openrouter", model="deepseek/deepseek-v4-pro"),
                primary_routes=[
                    RouteConfig(provider="google", model="gemini-2.5-flash"),
                    RouteConfig(provider="google", model="gemini-3.5-flash-lite"),
                ],
                fallback=JobFallbackConfig(
                    timeout=RouteConfig(provider="openrouter", model="deepseek/deepseek-v4-flash-fb"),
                    rate_limit=RouteConfig(provider="google", model="gemini-2.5-flash-lite"),
                )
            )
        }
    )
    routes = collect_configured_routes(cfg)
    paths_by_model = {r["model"]: r["path"] for r in routes}

    assert paths_by_model["deepseek-v4-flash"] == ("primary",)
    assert paths_by_model["deepseek/deepseek-v4-pro"] == ("secondary",)
    assert paths_by_model["gemini-2.5-flash"] == ("primary_routes", 0)
    assert paths_by_model["gemini-3.5-flash-lite"] == ("primary_routes", 1)
    assert paths_by_model["deepseek/deepseek-v4-flash-fb"] == ("fallback", "timeout")
    assert paths_by_model["gemini-2.5-flash-lite"] == ("fallback", "rate_limit")


def test_prices_interactive_apply_e2e(tmp_path, monkeypatch):
    """2. Test end-to-end della scrittura con mock questionary."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")

    outline_yaml = """# Outline Job Configuration
max_attempts: 4
primary:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  thinking: true
"""
    (config_dir / "outline.yaml").write_text(outline_yaml, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {
                "key": "deepseek/deepseek-v4-flash",
                "input_per_million": 0.25,
                "output_per_million": 0.50,
            },
            "stale": True,
        }
    ]

    mock_checkbox = MagicMock()
    mock_checkbox.ask.return_value = [fake_report[0]]
    mock_confirm = MagicMock()
    mock_confirm.ask.return_value = True

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox", return_value=mock_checkbox) as patched_questionary, \
         patch("questionary.confirm", return_value=mock_confirm):

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)

        patched_questionary.assert_called_once()

    # Ricarica con ruamel.yaml e verifica
    yaml = YAML()
    with open(config_dir / "outline.yaml", "r", encoding="utf-8") as f:
        data = yaml.load(f)

    assert data["primary"]["pricing"]["input_per_million"] == 0.25
    assert data["primary"]["pricing"]["output_per_million"] == 0.50
    assert data["primary"]["thinking"] is True


def test_prices_interactive_comment_preservation(tmp_path, monkeypatch):
    """3. Test che verifica la preservazione dei commenti nel file YAML."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")

    header_comment = "# ==========================================\n# INTESTAZIONE IMPORTANTE PER OUTLINE\n# ==========================================\n"
    outline_yaml = header_comment + """max_attempts: 4
primary:
  # Provider primario
  provider: "deepseek"
  model: "deepseek-v4-flash"
"""
    (config_dir / "outline.yaml").write_text(outline_yaml, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {
                "key": "deepseek/deepseek-v4-flash",
                "input_per_million": 0.30,
                "output_per_million": 0.60,
            },
            "stale": True,
        }
    ]

    mock_checkbox = MagicMock()
    mock_checkbox.ask.return_value = [fake_report[0]]
    mock_confirm = MagicMock()
    mock_confirm.ask.return_value = True

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox", return_value=mock_checkbox), \
         patch("questionary.confirm", return_value=mock_confirm):

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)

    raw_text = (config_dir / "outline.yaml").read_text(encoding="utf-8")
    assert "# INTESTAZIONE IMPORTANTE PER OUTLINE" in raw_text
    assert "# Provider primario" in raw_text
    assert "input_per_million: 0.3" in raw_text or "input_per_million: 0.30" in raw_text


def test_prices_interactive_no_applicable_entries(tmp_path, monkeypatch, capsys):
    """4. Test per il caso in cui non vi è alcun live_match: questionary non viene invocato."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")
    (config_dir / "outline.yaml").write_text("max_attempts: 1\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "custom_provider",
            "model": "unknown_model",
            "path": ("primary",),
            "used_input_per_million": 1.0,
            "used_output_per_million": 2.0,
            "live_match": None,
            "stale": False,
        }
    ]

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox") as patched_q:

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)
        patched_q.assert_not_called()

    captured = capsys.readouterr()
    assert "Nessun prezzo live disponibile da applicare." in captured.out


def test_prices_interactive_user_cancels(tmp_path, monkeypatch, capsys):
    """5. Test per il caso 'utente annulla' (ask() -> None): nessun file modificato, nessuna eccezione."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")
    orig_content = "max_attempts: 4\nprimary:\n  provider: 'deepseek'\n  model: 'deepseek-v4-flash'\n"
    (config_dir / "outline.yaml").write_text(orig_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {
                "key": "deepseek/deepseek-v4-flash",
                "input_per_million": 0.25,
                "output_per_million": 0.50,
            },
            "stale": True,
        }
    ]

    mock_checkbox = MagicMock()
    mock_checkbox.ask.return_value = None

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox", return_value=mock_checkbox):

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)

    captured = capsys.readouterr()
    assert "Annullato, nessuna modifica applicata." in captured.out
    assert (config_dir / "outline.yaml").read_text(encoding="utf-8") == orig_content


def test_prices_interactive_user_selects_empty(tmp_path, monkeypatch, capsys):
    """Test per il caso in cui l'utente conferma senza selezionare nulla (ask() -> [])."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")
    orig_content = "max_attempts: 4\nprimary:\n  provider: 'deepseek'\n  model: 'deepseek-v4-flash'\n"
    (config_dir / "outline.yaml").write_text(orig_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {
                "key": "deepseek/deepseek-v4-flash",
                "input_per_million": 0.25,
                "output_per_million": 0.50,
            },
            "stale": True,
        }
    ]

    mock_checkbox = MagicMock()
    mock_checkbox.ask.return_value = []

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox", return_value=mock_checkbox):

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)

    captured = capsys.readouterr()
    assert "Nessuna voce selezionata, nessuna modifica applicata." in captured.out
    assert (config_dir / "outline.yaml").read_text(encoding="utf-8") == orig_content


def test_prices_interactive_user_declines_final_confirmation(tmp_path, monkeypatch, capsys):
    """Selezionate delle voci nel checkbox, se l'utente rifiuta la conferma finale non scrive nulla."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("version: '2.0.0'\n", encoding="utf-8")
    orig_content = "max_attempts: 4\nprimary:\n  provider: 'deepseek'\n  model: 'deepseek-v4-flash'\n"
    (config_dir / "outline.yaml").write_text(orig_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {
                "key": "deepseek/deepseek-v4-flash",
                "input_per_million": 0.25,
                "output_per_million": 0.50,
            },
            "stale": True,
        }
    ]

    mock_checkbox = MagicMock()
    mock_checkbox.ask.return_value = [fake_report[0]]
    mock_confirm = MagicMock()
    mock_confirm.ask.return_value = False

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox", return_value=mock_checkbox), \
         patch("questionary.confirm", return_value=mock_confirm):

        args = argparse.Namespace(interactive=True)
        cmd_prices_check(args)

    captured = capsys.readouterr()
    assert "Annullato, nessuna modifica applicata." in captured.out
    assert (config_dir / "outline.yaml").read_text(encoding="utf-8") == orig_content


def test_prices_interactive_guard_no_config(tmp_path, monkeypatch):
    """6. Test per il guard _has_real_config_source(): senza cartella config/, solleva SystemExit(1)."""
    monkeypatch.chdir(tmp_path)
    # tmp_path has no config/ directory

    fake_report = [
        {
            "job": "outline",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "path": ("primary",),
            "used_input_per_million": 0.14,
            "used_output_per_million": 0.28,
            "live_match": {"key": "x", "input_per_million": 1.0, "output_per_million": 2.0},
        }
    ]

    with patch("rt.llm.pricing_sync.check_configured_pricing", return_value=fake_report), \
         patch("questionary.checkbox") as mock_q:
        args = argparse.Namespace(interactive=True)
        with pytest.raises(SystemExit) as exc_info:
            cmd_prices_check(args)
        assert exc_info.value.code == 1
        mock_q.assert_not_called()
