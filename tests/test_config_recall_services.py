"""
tests/test_config_recall_services.py
RT4-A6: config_service (scrittura atomica, segreti) e recall_service (logica senza UI).
"""
import os
import stat

import pytest

from rt.services import config_service, recall_service


def test_set_env_var_preserves_lines_and_export(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# commento\nexport RT_A=1\nRT_B=2\n", encoding="utf-8")
    monkeypatch.delenv("RT_A", raising=False)
    config_service.set_env_var(env, "RT_A", "nuovo")
    config_service.set_env_var(env, "RT_C", "3")
    assert env.read_text(encoding="utf-8") == "# commento\nexport RT_A=nuovo\nRT_B=2\nRT_C=3\n"
    assert os.environ["RT_A"] == "nuovo"
    if os.name == "posix":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_set_secret_quotes_and_validates(tmp_path):
    env = tmp_path / ".env"
    config_service.set_secret("RT_TEST_API_KEY", 'sk-"x"', path=env)
    assert env.read_text(encoding="utf-8") == 'RT_TEST_API_KEY="sk-\\"x\\""\n'
    with pytest.raises(ValueError):
        config_service.set_secret("RT_TEST_API_KEY", "a\nb", path=env)


def test_yaml_roundtrip_and_validation(tmp_path, monkeypatch):
    path = tmp_path / "config" / "general.yaml"
    config_service.write_yaml_atomic(path, {"telegram": {"default_channel": "terminal"}})
    assert config_service.read_yaml(path) == {"telegram": {"default_channel": "terminal"}}
    monkeypatch.chdir(tmp_path)
    assert config_service.general_config_path() == path
    assert config_service.validate_config() == []
    path.write_text("telegram: [1, 2]\n", encoding="utf-8")
    assert config_service.validate_config()


def test_recall_state_and_stale_detection(tmp_path):
    lesson = str(tmp_path)
    assert recall_service.load_recall_session_state(lesson)["order"] == "alternato"
    recall_service.save_recall_session_state(lesson, {"order": "casuale", "unit_cursor": "1.1",
                                                      "current_question_id": None, "force_mock": True})
    state = recall_service.load_recall_session_state(lesson)
    assert state["order"] == "casuale" and state["force_mock"] is True
    assert recall_service.find_stale_questions(lesson) == []
