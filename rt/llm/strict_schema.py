"""
rt.llm.strict_schema
Adatta lo schema JSON di un modello Pydantic alla modalità `strict` di json_schema.

OpenAI (diretto o via OpenRouter, es. openai/gpt-*) rifiuta con HTTP 400 uno schema strict
in cui un oggetto non elenca TUTTE le sue proprietà in `required` o non chiude
`additionalProperties`. Pydantic invece lascia fuori da `required` i campi con default
(es. `correzione: Optional[str] = None` della Verifica) e aggiunge `default`.
Qui ogni campo diventa obbligatorio: i campi Optional restano nullable (anyOf con null),
quindi il modello risponde `null` dove prima ometteva il campo, e Pydantic lo accetta uguale.
`minLength`/`maxLength` non sono accettati dalla modalità strict di OpenAI: si tolgono dallo
schema inviato, ma restano nel modello Pydantic, che li controlla comunque sulla risposta.
"""

import copy
from typing import Any, Dict, Type

from pydantic import BaseModel


def _strictify(node: Any) -> None:
    if isinstance(node, dict):
        for key in ("default", "minLength", "maxLength"):
            node.pop(key, None)
        properties = node.get("properties")
        if isinstance(properties, dict) and (node.get("type") == "object" or "type" not in node):
            node["required"] = list(properties.keys())
            node["additionalProperties"] = False
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)


def strict_json_schema(response_model: Type[BaseModel]) -> Dict[str, Any]:
    """Schema del modello compatibile con `strict: true` (tutte le proprietà richieste, niente extra)."""
    schema = copy.deepcopy(response_model.model_json_schema())
    _strictify(schema)
    return schema
