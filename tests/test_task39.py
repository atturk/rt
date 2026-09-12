"""
Unit test per Task 39: Telegram discovery retry, anonimizzazione link ed rt config --topics.
"""

import os
import yaml
import pytest
from unittest.mock import patch, MagicMock

from rt.pipeline.configure import (
    parse_telegram_topic_link,
    _configure_telegram_section,
    run_topics_management
)
from rt.cli import main


def test_link_example_anonymized():
    # Verifica che il vecchio ID di canale non sia presente nella docstring
    assert "4490473926" not in (parse_telegram_topic_link.__doc__ or "")
    # Verifica il corretto parsing del nuovo link anonimizzato
    res = parse_telegram_topic_link("https://t.me/c/1234567890/12/34")
    assert res == (-1001234567890, 12)


def test_discovery_live_retry_menu_on_no_messages(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(tmp_path, ".env")

    discovery_calls = 0

    def mock_requests_get(url, **kwargs):
        nonlocal discovery_calls, current_time
        discovery_calls += 1
        current_time += 200.0  # avanza di 200s ad ogni richiesta per far terminare il ciclo di listening
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"ok": True, "result": []}
        return m

    def mock_select(prompt, choices, **kwargs):
        m = MagicMock()
        if "Come vuoi configurare" in prompt:
            m.ask.return_value = "📡 Discovery live"
        elif "Come vuoi procedere" in prompt:
            if discovery_calls <= 1:
                m.ask.return_value = "🔄 Riprova discovery live"
            else:
                m.ask.return_value = "⏭ Annulla/salta questa parte"
        else:
            m.ask.return_value = choices[0] if choices else ""
        return m

    valid_token = "123456789:AAHhqTGxHf9nqDTQGSKZ_abc1234567890_valid"

    current_time = 1000.0

    def mock_monotonic():
        nonlocal current_time
        current_time += 1.0
        return current_time

    def mock_confirm(prompt, **kwargs):
        m = MagicMock()
        if "Vuoi modificarlo" in prompt:
            m.ask.return_value = False
        else:
            m.ask.return_value = True
        return m

    with patch.dict(os.environ, {"RT_TELEGRAM_BOT_TOKEN": valid_token}):
        with patch("questionary.confirm", side_effect=mock_confirm):
            with patch("questionary.select", side_effect=mock_select):
                with patch("questionary.text") as mock_txt:
                    mock_txt.return_value.ask.return_value = ""
                    with patch("time.monotonic", side_effect=mock_monotonic):
                        with patch("requests.get", side_effect=mock_requests_get):
                            _configure_telegram_section(config_dir, env_path)

    # Verifica che la discovery sia stata tentata almeno 2 volte grazie all'opzione Riprova
    assert discovery_calls >= 2


def test_run_topics_management_edit_rename_delete(tmp_path):
    config_dir = os.path.join(tmp_path, "config")
    os.makedirs(config_dir, exist_ok=True)
    general_yaml_path = os.path.join(config_dir, "general.yaml")

    initial_data = {
        "telegram": {
            "topics": {
                "ANATOMIA": {"chat_id": -1001234567890, "message_thread_id": 12},
                "FISIOLOGIA": {"chat_id": -1001234567890, "message_thread_id": 34}
            }
        }
    }
    with open(general_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_data, f)

    # Sequenza:
    # 1. Seleziona "✏️ Gestisci 'ANATOMIA'"
    # 2. Operazione su ANATOMIA: "✏️ Rinomina materia" -> nuovo nome: "ANATOMIA I"
    # 3. Seleziona "✏️ Gestisci 'FISIOLOGIA'"
    # 4. Operazione su FISIOLOGIA: "🗑️ Rimuovi mappatura" -> confirm True
    # 5. Seleziona "⏭ Esci"

    select_responses = [
        "✏️ Gestisci 'ANATOMIA'",
        "✏️ Rinomina materia",
        "✏️ Gestisci 'FISIOLOGIA'",
        "🗑️ Rimuovi mappatura",
        "⏭ Esci"
    ]

    def mock_select(prompt, choices, **kwargs):
        m = MagicMock()
        val = select_responses.pop(0) if select_responses else "⏭ Esci"
        m.ask.return_value = val
        return m

    with patch("rt.pipeline.configure._resolve_or_bootstrap_config_paths", return_value=(config_dir, os.path.join(tmp_path, ".env"))):
        with patch("questionary.select", side_effect=mock_select):
            with patch("questionary.text") as mock_txt:
                mock_txt.return_value.ask.return_value = "ANATOMIA I"
                with patch("questionary.confirm") as mock_conf:
                    mock_conf.return_value.ask.return_value = True
                    run_topics_management()

    with open(general_yaml_path, "r", encoding="utf-8") as f:
        saved_data = yaml.safe_load(f)

    topics = saved_data.get("telegram", {}).get("topics", {})
    assert "ANATOMIA I" in topics
    assert "ANATOMIA" not in topics
    assert "FISIOLOGIA" not in topics


def test_cli_topics_mutually_exclusive_flags():
    test_args = ["rt", "config", "--models", "--topics"]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2
