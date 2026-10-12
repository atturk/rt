"""V4c: prefisso stabile, cache dei metadati e ordine dei messaggi."""
import json
from unittest.mock import MagicMock

from rt.core.lesson_paths import lesson_path
from rt.llm.client import LLMClient
from rt.llm.lesson_context import lesson_context_prompt
from rt.llm.prompts import ReviewFindingList
from rt.services.recall_context import lesson_context
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_context_contains_metadata_and_outline_without_changing_classifier_view(tmp_path, monkeypatch):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    info = lesson_path(lesson, "info.yaml")
    with open(info, "a") as file:
        file.write("docente: Rossi\n")
    original = lesson_context(lesson)
    assert set(original) == {"materia", "titolo_lezione", "argomenti_lezione"}
    block = lesson_context_prompt(lesson)
    context = json.loads(block.split("\n", 1)[1])
    assert context["titolo_lezione"] == "Lipidi"
    assert context["materia"] == "BIOCHIMICA"
    assert context["docente"] == "Rossi"
    assert context["argomenti_lezione"] == ["Lipidi"]
    assert [unit["id"] for unit in context["scaletta"]] == ["1.1", "1.2", "2.1"]
    # Le letture successive sono in cache e le copie restituite non la alterano.
    monkeypatch.setattr("rt.services.recall_context.fs.open", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("rilettura")))
    lesson_context(lesson, include_structure=True)["scaletta"].clear()
    assert lesson_context_prompt(lesson) == block
    assert lesson_context(lesson) == original


def test_context_invalidates_when_lesson_metadata_changes(tmp_path, monkeypatch):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    before = lesson_context_prompt(lesson)
    info = lesson_path(lesson, "info.yaml")
    with open(info, "a") as file:
        file.write("docente: Bianchi\n")
    assert lesson_context_prompt(lesson) != before
    assert "Bianchi" in lesson_context_prompt(lesson)


def test_gateway_orders_system_lesson_unit_and_user_extra(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"issues": []}'}, "finish_reason": "stop"}]}
        return response
    monkeypatch.setattr("requests.post", post)
    client = LLMClient()
    client.call_structured(prompt="UNITÀ\nsorelle\nextra utente", system_prompt="sistema", response_model=ReviewFindingList,
        job_name="review", override_provider="deepseek", override_model="deepseek-chat",
        prompt_prefix="lezione", stream=False, show_monitor=False, constrained_schema=True)
    messages = requests[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "user"]
    assert messages[0]["content"].startswith("sistema")
    assert messages[1]["content"] == "lezione"
    assert messages[2]["content"] == "UNITÀ\nsorelle\nextra utente"
