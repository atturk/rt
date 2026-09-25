"""Connessioni web: chiavi multiple, modelli per fase e compatibilità legacy."""
import subprocess
import sys

import yaml

from rt.core.config import load_config
from rt.telegram.daemon_status import get_daemon_pid, remove_daemon_pid, write_daemon_pid
from rt.web.connections import (add_model, assign_phase, connection_names,
                                model_names, phase_selection, save_connection)


def test_connection_round_robin_and_phase_selection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "general.yaml").write_text("credentials: []\n", encoding="utf-8")
    (config / "outline.yaml").write_text("primary: {}\n", encoding="utf-8")

    save_connection(tmp_path, "Studio", "google", "", ["key-one", "key-two"])
    assert connection_names(tmp_path) == ["Studio"]
    assert "key-one" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert "key-two" in (tmp_path / ".env").read_text(encoding="utf-8")
    add_model(tmp_path, "Studio", "gemini-test")
    assert model_names(tmp_path, "Studio") == ["gemini-test"]
    assign_phase(tmp_path, "outline", "Studio", "gemini-test")

    route = yaml.safe_load((config / "outline.yaml").read_text(encoding="utf-8"))
    assert route["round_robin"] is True
    assert [item["credential"] for item in route["primary_routes"]] == ["web_studio_1", "web_studio_2"]
    assert phase_selection(tmp_path, "outline") == ("Studio", "gemini-test")
    assert load_config().jobs["outline"].primary.model == "gemini-test"


def test_recall_route_migrates_legacy_file_without_changing_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    (config / "telegram").mkdir(parents=True)
    (config / "general.yaml").write_text(
        "credentials:\n  - name: old\n    provider: openrouter\n    env_var: OLD_KEY\n", encoding="utf-8")
    old = config / "telegram" / "recall_quiz.yaml"
    old.write_text("primary:\n  provider: openrouter\n  credential: old\n  model: former-model\n",
                   encoding="utf-8")
    before = old.read_text(encoding="utf-8")
    assert load_config().jobs["recall"].primary.model == "former-model"
    assert phase_selection(tmp_path, "recall") == ("old", "former-model")

    add_model(tmp_path, "old", "new-model")
    assign_phase(tmp_path, "recall", "old", "new-model")
    assert load_config().jobs["recall"].primary.model == "new-model"
    assert old.read_text(encoding="utf-8") == before
    assert (config / "telegram" / "recall.yaml").exists()


def test_recall_legacy_prefers_configured_route_over_empty_quiz(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config" / "telegram"
    config.mkdir(parents=True)
    (tmp_path / "config" / "general.yaml").write_text(
        "credentials:\n  - name: old\n    provider: openrouter\n    env_var: OLD_KEY\n",
        encoding="utf-8")
    (config / "recall_quiz.yaml").write_text("primary: {}\n", encoding="utf-8")
    (config / "recall_mirata.yaml").write_text(
        "primary:\n  provider: openrouter\n  credential: old\n  model: working-model\n",
        encoding="utf-8")
    assert load_config().jobs["recall"].primary.model == "working-model"
    assert phase_selection(tmp_path, "recall") == ("old", "working-model")


def test_daemon_pid_is_exclusive_across_processes(tmp_path):
    path = str(tmp_path / "telegram.pid")
    write_daemon_pid(path)
    try:
        assert get_daemon_pid(path) is not None
        attempt = subprocess.run(
            [sys.executable, "-c",
             "from rt.telegram.daemon_status import write_daemon_pid; "
             "write_daemon_pid(__import__('sys').argv[1])", path],
            capture_output=True, text=True, check=False)
        assert attempt.returncode != 0
        assert "già in esecuzione" in attempt.stderr
    finally:
        remove_daemon_pid(path)
    assert get_daemon_pid(path) is None


def test_model_offered_by_legacy_route_stays_selectable_after_reassignment(tmp_path, monkeypatch):
    """I modelli ricavati dai vecchi file YAML non devono sparire quando nessuna fase li usa
    più: la pagina li mostra ancora e sceglierli deve salvare l'assegnazione."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "general.yaml").write_text(
        "credentials:\n  - name: old\n    provider: openrouter\n    env_var: OLD_KEY\n", encoding="utf-8")
    for job, model in (("outline", "model-a"), ("rewrite", "model-b")):
        (config / f"{job}.yaml").write_text(
            f"primary:\n  provider: openrouter\n  credential: old\n  model: {model}\n", encoding="utf-8")
    offered = model_names(tmp_path, "old")
    assert offered == ["model-a", "model-b"]

    assign_phase(tmp_path, "rewrite", "old", "model-a")
    assign_phase(tmp_path, "outline", "old", "model-b")

    assert phase_selection(tmp_path, "outline") == ("old", "model-b")
    assert phase_selection(tmp_path, "rewrite") == ("old", "model-a")
    assert model_names(tmp_path, "old") == offered


def test_assign_phase_requires_a_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "general.yaml").write_text("credentials: []\n", encoding="utf-8")
    (config / "outline.yaml").write_text("primary: {}\n", encoding="utf-8")
    save_connection(tmp_path, "Studio", "google", "", ["key-one"])
    import pytest
    for empty in (None, "", "  "):
        with pytest.raises(ValueError):
            assign_phase(tmp_path, "outline", "Studio", empty)
