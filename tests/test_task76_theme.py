"""
tests/test_task76_theme.py
Test per il supporto dei temi nativi Textual e rt config --theme (Task 76).
"""

import os
import json
import argparse
import pytest
import yaml
from unittest.mock import patch, MagicMock

from rt.core.config import RTConfig, UiConfig, load_config, _load_config_dir
from rt.core.ui_theme import (
    resolve_textual_theme,
    get_configured_textual_theme,
    apply_saved_theme,
)
from rt.tui.configure import (
    configure_config_parser,
    run_theme_selection,
    _maybe_prompt_theme_first_time,
)
from rt.cli import cmd_config


# ---------------------------------------------------------------------------
# 1. Test Config & Schemas
# ---------------------------------------------------------------------------

def test_rtconfig_ui_theme_default():
    """Verifica che RTConfig abbia default ui.theme='dark'."""
    cfg = RTConfig()
    assert hasattr(cfg, "ui")
    assert cfg.ui.theme == "dark"


def test_rtconfig_ui_theme_custom():
    """Verifica la validazione di ui.theme='light' o 'dark'."""
    cfg_light = RTConfig.model_validate({"ui": {"theme": "light"}})
    assert cfg_light.ui.theme == "light"

    cfg_dark = RTConfig.model_validate({"ui": {"theme": "dark"}})
    assert cfg_dark.ui.theme == "dark"

    # ui assente nei dati
    cfg_empty = RTConfig.model_validate({"version": "2.0.0"})
    assert cfg_empty.ui.theme == "dark"


def test_load_config_dir_with_ui_theme(tmp_path):
    """Verifica il caricamento di ui.theme da general.yaml."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    gen_file = cfg_dir / "general.yaml"
    gen_file.write_text("version: '2.0.0'\nui:\n  theme: light\n", encoding="utf-8")

    cfg = _load_config_dir(str(cfg_dir))
    assert cfg.ui.theme == "light"


def test_load_config_dir_without_ui_theme(tmp_path):
    """Verifica il fallback a dark quando ui non è in general.yaml."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    gen_file = cfg_dir / "general.yaml"
    gen_file.write_text("version: '2.0.0'\n", encoding="utf-8")

    cfg = _load_config_dir(str(cfg_dir))
    assert cfg.ui.theme == "dark"


# ---------------------------------------------------------------------------
# 2. Test ui_theme helper module
# ---------------------------------------------------------------------------

def test_resolve_textual_theme():
    """Verifica la risoluzione delle stringhe dark/light nei temi Textual."""
    assert resolve_textual_theme("dark") == "textual-dark"
    assert resolve_textual_theme("light") == "textual-light"
    assert resolve_textual_theme(None) == "textual-dark"
    assert resolve_textual_theme("") == "textual-dark"
    assert resolve_textual_theme("unknown") == "textual-dark"


def test_get_configured_textual_theme():
    """Verifica il recupero del tema Textual dalla configurazione."""
    cfg_dark = RTConfig(ui=UiConfig(theme="dark"))
    assert get_configured_textual_theme(cfg_dark) == "textual-dark"

    cfg_light = RTConfig(ui=UiConfig(theme="light"))
    assert get_configured_textual_theme(cfg_light) == "textual-light"


def test_apply_saved_theme():
    """Verifica l'applicazione del tema su un'app fittizia."""
    app = MagicMock()
    cfg_light = RTConfig(ui=UiConfig(theme="light"))
    apply_saved_theme(app, cfg_light)
    assert app.theme == "textual-light"

    cfg_dark = RTConfig(ui=UiConfig(theme="dark"))
    apply_saved_theme(app, cfg_dark)
    assert app.theme == "textual-dark"


# ---------------------------------------------------------------------------
# 3. Test 4 Textual Apps apply theme on init
# ---------------------------------------------------------------------------

def test_outline_review_app_theme(tmp_path):
    """Verifica che OutlineReviewApp applichi il tema salvato."""
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)
    outline_json = os.path.join(lesson_dir, "outline.json")
    with open(outline_json, "w", encoding="utf-8") as f:
        json.dump({
            "lesson_title": "Test Title",
            "macro_sections": [
                {
                    "id": "1",
                    "title": "Macro 1",
                    "units": [
                        {
                            "id": "1.1",
                            "title": "Unit 1",
                            "start_segment_id": "seg_000001",
                            "end_segment_id": "seg_000002",
                        }
                    ],
                }
            ],
        }, f)

    from rt.tui.outline_review import OutlineReviewApp

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-light"):
        app = OutlineReviewApp(lesson_dir)
        assert app.theme == "textual-light"

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-dark"):
        app = OutlineReviewApp(lesson_dir)
        assert app.theme == "textual-dark"


def test_issue_review_app_theme(tmp_path):
    """Verifica che IssueReviewApp applichi il tema salvato."""
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    from rt.tui.issue_review import IssueReviewApp

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-light"):
        app = IssueReviewApp(lesson_dir, to_review=[])
        assert app.theme == "textual-light"

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-dark"):
        app = IssueReviewApp(lesson_dir, to_review=[])
        assert app.theme == "textual-dark"


def test_configure_phase_roles_app_theme():
    """Verifica che ConfigurePhaseRolesApp applichi il tema salvato."""
    from rt.tui.configure import ConfigurePhaseRolesApp

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-light"):
        app = ConfigurePhaseRolesApp(
            config_dir="",
            env_path="",
            general_data={},
            general_yaml_path="",
            profiles={},
            job_paths={},
            grouped_jobs=[],
            group_info={},
            pending_selections={},
        )
        assert app.theme == "textual-light"

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-dark"):
        app = ConfigurePhaseRolesApp(
            config_dir="",
            env_path="",
            general_data={},
            general_yaml_path="",
            profiles={},
            job_paths={},
            grouped_jobs=[],
            group_info={},
            pending_selections={},
        )
        assert app.theme == "textual-dark"


def test_stale_recall_app_theme(tmp_path):
    """Verifica che StaleRecallApp applichi il tema salvato."""
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(lesson_dir, exist_ok=True)

    from rt.tui.recall import StaleRecallApp

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-light"):
        app = StaleRecallApp(lesson_dir, stale_questions=[])
        assert app.theme == "textual-light"

    with patch("rt.core.ui_theme.get_configured_textual_theme", return_value="textual-dark"):
        app = StaleRecallApp(lesson_dir, stale_questions=[])
        assert app.theme == "textual-dark"


# ---------------------------------------------------------------------------
# 4. Test rt config --theme and CLI integration
# ---------------------------------------------------------------------------

def test_configure_config_parser_theme_flag():
    """Verifica che --theme sia presente e mutuamente esclusivo con gli altri flag."""
    parser = argparse.ArgumentParser()
    configure_config_parser(parser)

    args = parser.parse_args(["--theme"])
    assert args.theme is True
    assert args.models is False
    assert args.telegram is False
    assert args.topics is False

    with pytest.raises(SystemExit):
        parser.parse_args(["--theme", "--models"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--theme", "--telegram"])


def test_cmd_config_dispatches_theme():
    """Verifica che cmd_config invochi run_theme_selection quando args.theme=True."""
    args = argparse.Namespace(models=False, telegram=False, topics=False, theme=True)
    with patch("rt.tui.configure.run_theme_selection") as mock_theme:
        cmd_config(args)
        mock_theme.assert_called_once()


def test_run_theme_selection_light(tmp_path):
    """Verifica che run_theme_selection salvi 'light' in general.yaml."""
    cfg_dir = str(tmp_path / "config")
    os.makedirs(cfg_dir, exist_ok=True)
    gen_file = os.path.join(cfg_dir, "general.yaml")
    with open(gen_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)

    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = "🌕 Chiaro"
        res = run_theme_selection(config_dir=cfg_dir)

    assert res == "light"
    with open(gen_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data.get("ui", {}).get("theme") == "light"


def test_run_theme_selection_dark(tmp_path):
    """Verifica che run_theme_selection salvi 'dark' in general.yaml."""
    cfg_dir = str(tmp_path / "config")
    os.makedirs(cfg_dir, exist_ok=True)
    gen_file = os.path.join(cfg_dir, "general.yaml")
    with open(gen_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0", "ui": {"theme": "light"}}, f)

    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = "🌑 Scuro"
        res = run_theme_selection(config_dir=cfg_dir)

    assert res == "dark"
    with open(gen_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data.get("ui", {}).get("theme") == "dark"


def test_run_theme_selection_cancelled(tmp_path):
    """Verifica il comportamento in caso di cancellazione dell'utente."""
    cfg_dir = str(tmp_path / "config")
    os.makedirs(cfg_dir, exist_ok=True)

    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = None
        res = run_theme_selection(config_dir=cfg_dir)

    assert res is None


def test_maybe_prompt_theme_first_time(tmp_path):
    """Verifica che _maybe_prompt_theme_first_time chieda il tema solo se non presente."""
    cfg_dir = str(tmp_path / "config")
    os.makedirs(cfg_dir, exist_ok=True)
    gen_file = os.path.join(cfg_dir, "general.yaml")

    # 1. Nessun ui.theme configurato -> chiama run_theme_selection
    with open(gen_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0"}, f)

    with patch("rt.tui.configure.run_theme_selection") as mock_sel:
        _maybe_prompt_theme_first_time(cfg_dir)
        mock_sel.assert_called_once_with(config_dir=cfg_dir)

    # 2. ui.theme già configurato -> non chiama run_theme_selection
    with open(gen_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2.0.0", "ui": {"theme": "dark"}}, f)

    with patch("rt.tui.configure.run_theme_selection") as mock_sel:
        _maybe_prompt_theme_first_time(cfg_dir)
        mock_sel.assert_not_called()
