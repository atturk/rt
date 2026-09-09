"""
tests/test_recall_lessons.py
Override esplicito per /recall da Telegram (rt.telegram.recall_lessons), letto da
config/telegram/recall_lessons.yaml. Facoltativo: nessuna entry -> None (il chiamante
ricade sul comportamento automatico esistente).
"""
import pytest

from rt.telegram.recall_lessons import get_lesson_override


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "config" / "telegram"
    d.mkdir(parents=True)
    return d


def test_returns_none_when_file_missing(config_dir):
    assert get_lesson_override("BIOCHIMICA") is None


def test_returns_none_when_materia_not_listed(config_dir):
    (config_dir / "recall_lessons.yaml").write_text('FISICA: "/tmp/fisica"\n', encoding="utf-8")
    assert get_lesson_override("BIOCHIMICA") is None


def test_returns_configured_path(config_dir):
    (config_dir / "recall_lessons.yaml").write_text('BIOCHIMICA: "/tmp/lezione_bio"\n', encoding="utf-8")
    assert get_lesson_override("BIOCHIMICA") == "/tmp/lezione_bio"


def test_lookup_is_case_insensitive(config_dir):
    (config_dir / "recall_lessons.yaml").write_text('Biochimica: "/tmp/lezione_bio"\n', encoding="utf-8")
    assert get_lesson_override("BIOCHIMICA") == "/tmp/lezione_bio"
    assert get_lesson_override("biochimica") == "/tmp/lezione_bio"


def test_malformed_yaml_returns_none_instead_of_raising(config_dir):
    (config_dir / "recall_lessons.yaml").write_text("not: [valid: yaml: at all", encoding="utf-8")
    assert get_lesson_override("BIOCHIMICA") is None


def test_non_dict_yaml_returns_none(config_dir):
    (config_dir / "recall_lessons.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    assert get_lesson_override("BIOCHIMICA") is None
