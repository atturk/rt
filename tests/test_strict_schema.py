"""Lo schema strict inviato ai provider elenca tutte le proprietà in `required` (OpenAI lo esige)."""
import inspect

import pytest
from pydantic import BaseModel

import rt.llm.prompts as prompts
from rt.llm.prompts import StudyNoteVerificaResponse
from rt.llm.providers.openrouter import OpenRouterProvider
from rt.llm.strict_schema import strict_json_schema

MODELS = [c for c in vars(prompts).values()
          if inspect.isclass(c) and issubclass(c, BaseModel) and c is not BaseModel]


def _objects(node):
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _objects(item)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_object_requires_all_properties(model):
    schema = strict_json_schema(model)
    for obj in _objects(schema):
        assert obj["required"] == list(obj["properties"])
        assert obj["additionalProperties"] is False
    text = str(schema)
    assert "'default'" not in text and "minLength" not in text


def test_verifica_schema_requires_correzione_and_accepts_null():
    schema = strict_json_schema(StudyNoteVerificaResponse)
    assert schema["required"] == ["esito", "spiegazione", "correzione"]
    assert StudyNoteVerificaResponse.model_validate(
        {"esito": "corretto", "spiegazione": "ok", "correzione": None}).correzione is None
    payload = OpenRouterProvider().build_payload(model="openai/gpt-6-luna", messages=[],
                                                 response_json_schema=schema, stream=False)
    assert payload["response_format"]["json_schema"]["schema"]["required"][-1] == "correzione"


def test_pydantic_schema_is_not_mutated():
    strict_json_schema(StudyNoteVerificaResponse)
    assert "correzione" not in StudyNoteVerificaResponse.model_json_schema().get("required", [])
