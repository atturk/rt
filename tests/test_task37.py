"""
Unit test per Task 37: inserimento chiavi API round-robin in batch separate da virgola.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from rt.pipeline.configure import _create_new_model_profile


def test_batch_api_keys_comma_separated(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")
    general_data = {"credentials": []}

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.side_effect = ["google", "round_robin", "manual"]
        with patch("questionary.text") as mock_txt:
            mock_txt.return_value.ask.return_value = ""
            with patch("questionary.confirm") as mock_conf:
                mock_conf.return_value.ask.return_value = True
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.side_effect = ["key1, key2,key3", ""]
                    with patch("questionary.autocomplete") as mock_auto:
                        mock_auto.return_value.ask.return_value = "gemini-2.5-flash"
                        with patch("rt.pipeline.configure._configure_pricing_section", return_value=None):
                            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data)

    creds = general_data.get("credentials", [])
    assert len(creds) == 3
    assert creds[0] == {"name": "google_1", "provider": "google", "env_var": "GOOGLE_API_KEY_1"}
    assert creds[1] == {"name": "google_2", "provider": "google", "env_var": "GOOGLE_API_KEY_2"}
    assert creds[2] == {"name": "google_3", "provider": "google", "env_var": "GOOGLE_API_KEY_3"}


def test_batch_api_keys_empty_commas(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")
    general_data = {"credentials": []}

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.side_effect = ["openrouter", "round_robin", "manual"]
        with patch("questionary.text") as mock_txt:
            mock_txt.return_value.ask.return_value = ""
            with patch("questionary.confirm") as mock_conf:
                mock_conf.return_value.ask.return_value = True
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.side_effect = ["key1,,key2,", ""]
                    with patch("questionary.autocomplete") as mock_auto:
                        mock_auto.return_value.ask.return_value = "openrouter/free"
                        with patch("rt.pipeline.configure._configure_pricing_section", return_value=None):
                            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data)

    creds = general_data.get("credentials", [])
    assert len(creds) == 2
    assert creds[0]["env_var"] == "OPENROUTER_API_KEY_1"
    assert creds[1]["env_var"] == "OPENROUTER_API_KEY_2"


def test_batch_api_keys_multiple_prompts_continuation(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")
    general_data = {"credentials": []}

    with patch("questionary.select") as mock_sel:
        mock_sel.return_value.ask.side_effect = ["openrouter", "round_robin", "manual"]
        with patch("questionary.text") as mock_txt:
            mock_txt.return_value.ask.return_value = ""
            with patch("questionary.confirm") as mock_conf:
                mock_conf.return_value.ask.return_value = True
                with patch("questionary.password") as mock_pass:
                    mock_pass.return_value.ask.side_effect = ["key1, key2", "key3", ""]
                    with patch("questionary.autocomplete") as mock_auto:
                        mock_auto.return_value.ask.return_value = "openrouter/free"
                        with patch("rt.pipeline.configure._configure_pricing_section", return_value=None):
                            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data)

    creds = general_data.get("credentials", [])
    assert len(creds) == 3
    assert creds[2]["env_var"] == "OPENROUTER_API_KEY_3"
    assert creds[2]["name"] == "openrouter_3"
