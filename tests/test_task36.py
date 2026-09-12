"""
Unit test per Task 36: bugfixes in rt/pipeline/configure.py.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.configure import (
    _is_placeholder_or_invalid_bot_token,
    _create_new_model_profile,
    _configure_telegram_section
)
from rt.pipeline.setup import clean_input_path


def test_is_placeholder_or_invalid_bot_token():
    # Placeholder da .env.example
    assert _is_placeholder_or_invalid_bot_token("123456:ABC-your-bot-token") is True
    # Stringa vuota o None
    assert _is_placeholder_or_invalid_bot_token("") is True
    assert _is_placeholder_or_invalid_bot_token("   ") is True
    # Token invalido corto
    assert _is_placeholder_or_invalid_bot_token("123:abc") is True
    # Token valido (formato numeroid:secret di almeno 30 alfanumerici)
    assert _is_placeholder_or_invalid_bot_token("123456789:AAHhqTGxHf9nqDTQGSKZ_abc1234567890") is False


def test_clean_input_path_lessons_root():
    quoted_path = '"/Users/test/RT Lezioni"'
    cleaned = clean_input_path(quoted_path)
    assert cleaned == "/Users/test/RT Lezioni"


def test_single_key_warning_printed(tmp_path, capsys):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")
    with open(env_path, "w") as f:
        f.write("OPENROUTER_API_KEY=sk-or-existing-key\n")

    general_data = {"credentials": []}

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-existing-key"}):
        with patch("questionary.select") as mock_sel:
            mock_sel.return_value.ask.side_effect = ["openrouter", "manual"]
            with patch("questionary.password") as mock_pass:
                mock_pass.return_value.ask.return_value = "sk-or-existing-key"
                with patch("questionary.text") as mock_txt:
                    mock_txt.return_value.ask.return_value = "openrouter/free"
                    with patch("questionary.confirm") as mock_conf:
                        mock_conf.return_value.ask.return_value = True
                        _create_new_model_profile(config_dir, env_path, general_data)

    captured = capsys.readouterr().out
    assert "Trovata una chiave già configurata per openrouter." in captured


def test_autocomplete_default_is_empty(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_data = {"credentials": []}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "model-a"}, {"id": "model-b"}]
    }

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}):
        with patch("requests.get", return_value=mock_resp):
            with patch("questionary.select") as mock_sel:
                mock_sel.return_value.ask.return_value = "openrouter"
                with patch("questionary.autocomplete") as mock_auto:
                    mock_auto.return_value.ask.return_value = "model-b"
                    with patch("questionary.confirm") as mock_conf:
                        mock_conf.return_value.ask.return_value = True
                        _create_new_model_profile(config_dir, env_path, general_data)

                    mock_auto.assert_called_once()
                    kwargs = mock_auto.call_args[1]
                    assert kwargs.get("default") == ""


def test_google_native_models_fetch_fallback(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_data = {"credentials": []}

    mock_google_resp = MagicMock()
    mock_google_resp.status_code = 200
    mock_google_resp.json.return_value = {
        "models": [
            {"name": "models/gemini-2.5-flash"},
            {"name": "models/gemini-2.5-pro"}
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "AIzaSyFakeKey"}):
        with patch("requests.get", return_value=mock_google_resp):
            with patch("questionary.select") as mock_sel:
                mock_sel.return_value.ask.return_value = "google"
                with patch("questionary.autocomplete") as mock_auto:
                    mock_auto.return_value.ask.return_value = "gemini-2.5-flash"
                    with patch("questionary.confirm") as mock_conf:
                        mock_conf.return_value.ask.return_value = True
                        _create_new_model_profile(config_dir, env_path, general_data)

                    mock_auto.assert_called_once()
                    choices = mock_auto.call_args[1].get("choices", [])
                    assert "gemini-2.5-flash" in choices
                    assert "gemini-2.5-pro" in choices


def test_fetch_models_diagnostic_error(tmp_path, capsys):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    general_data = {"credentials": []}

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}):
        with patch("requests.get", return_value=mock_resp):
            with patch("questionary.select") as mock_sel:
                mock_sel.return_value.ask.return_value = "openrouter"
                with patch("questionary.text") as mock_txt:
                    mock_txt.return_value.ask.return_value = "custom-model"
                    with patch("questionary.confirm") as mock_conf:
                        mock_conf.return_value.ask.return_value = True
                        _create_new_model_profile(config_dir, env_path, general_data)

    captured = capsys.readouterr().out
    assert "HTTP 404" in captured
