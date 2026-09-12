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

    def mock_select(prompt, choices, **kwargs):
        m = MagicMock()
        if "Provider" in prompt:
            m.ask.return_value = "openrouter"
        elif "URL base" in prompt:
            m.ask.return_value = "https://openrouter.ai/api/v1"
        else:
            m.ask.return_value = choices[0] if choices else ""
        return m

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-existing-key"}):
        with patch("questionary.select", side_effect=mock_select):
            with patch("questionary.password") as mock_pass:
                mock_pass.return_value.ask.return_value = "sk-or-existing-key"
                with patch("questionary.text") as mock_txt:
                    mock_txt.return_value.ask.return_value = "openrouter/free"
                    with patch("questionary.autocomplete") as mock_auto:
                        mock_auto.return_value.ask.return_value = "openrouter/free"
                        with patch("questionary.confirm", side_effect=_mock_confirm_helper):
                            with patch("requests.get") as mock_http:
                                mock_http.return_value.status_code = 200
                                mock_http.return_value.json.return_value = {"data": []}
                                _create_new_model_profile(config_dir, env_path, general_data)

    captured = capsys.readouterr().out
    assert "Trovata una chiave già configurata per openrouter." in captured


def _mock_confirm_helper(prompt, **kwargs):
    m = MagicMock()
    if "più chiavi API" in prompt or "listino prezzi" in prompt:
        m.ask.return_value = False
    else:
        m.ask.return_value = True
    return m


def _make_mock_select(provider_name):
    def mock_sel(prompt, choices=None, **kwargs):
        m = MagicMock()
        choices = choices or []
        p_lower = prompt.lower()
        if "round-robin" in p_lower or "chiavi" in p_lower:
            for c in choices:
                if c.startswith("⏭"):
                    m.ask.return_value = c
                    return m
            m.ask.return_value = choices[0] if choices else ""
        elif "provider" in p_lower:
            m.ask.return_value = provider_name
        elif "url" in p_lower:
            m.ask.return_value = choices[0] if choices else ""
        else:
            m.ask.return_value = choices[0] if choices else ""
        return m
    return mock_sel


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
            with patch("questionary.select", side_effect=_make_mock_select("openrouter")):
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.return_value = "sk-test"
                    with patch("questionary.text") as mock_txt:
                        mock_txt.return_value.ask.return_value = ""
                        with patch("questionary.autocomplete") as mock_auto:
                            mock_auto.return_value.ask.return_value = "model-b"
                            with patch("questionary.confirm", side_effect=_mock_confirm_helper):
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
            with patch("questionary.select", side_effect=_make_mock_select("google")):
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.return_value = "AIzaSyFakeKey"
                    with patch("questionary.text") as mock_txt:
                        mock_txt.return_value.ask.return_value = ""
                        with patch("questionary.autocomplete") as mock_auto:
                            mock_auto.return_value.ask.return_value = "gemini-2.5-flash"
                            with patch("questionary.confirm", side_effect=_mock_confirm_helper):
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
            with patch("questionary.select", side_effect=_make_mock_select("openrouter")):
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.return_value = "sk-test"
                    with patch("questionary.text") as mock_txt:
                        mock_txt.return_value.ask.return_value = "custom-model"
                        with patch("questionary.confirm", side_effect=_mock_confirm_helper):
                            _create_new_model_profile(config_dir, env_path, general_data)

    captured = capsys.readouterr().out
    assert "HTTP 404" in captured
