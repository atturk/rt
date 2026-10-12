"""Registro dei tipi personalizzati, filtrato per materia della lezione."""
import json
from pathlib import Path

from rt.core.config import load_config

BASE_TYPES = ('quiz', 'mirata', 'vasta')


def templates():
    path = Path(__file__).resolve().parents[1] / 'recall' / 'question_type_templates.json'
    return [{k: v for k, v in t.items() if k != 'originali'} for t in json.loads(path.read_text())]


def active_types(*, lesson_dir=None, materia=None, cfg=None):
    if lesson_dir is not None:
        from rt.services.recall_context import lesson_context
        materia = lesson_context(lesson_dir).get('materia', '')
    subject = str(materia or '').strip().casefold()
    return [t for t in (cfg or load_config()).recall.custom_types
            if subject and subject in {m.strip().casefold() for m in t.materie}]


def find_type(identifier, *, cfg=None):
    return next((t for t in (cfg or load_config()).recall.custom_types if t.id == identifier), None)


def question_key(question):
    return question.custom_type if question.type.value == 'personalizzata' else question.type.value


def type_key(value):
    return value.value if hasattr(value, 'value') else str(value)


def resolve_type(value):
    from rt.core.models import RecallQuestionType
    identifier = type_key(value)
    if identifier in BASE_TYPES:
        return RecallQuestionType(identifier)
    if find_type(identifier) is None:
        raise ValueError("Tipo di domanda non valido")
    return identifier


def lesson_types(lesson_dir):
    return [*BASE_TYPES, *[t.id for t in active_types(lesson_dir=lesson_dir)]]


def supports_comment(question):
    if question.type.value in ("quiz", "vasta"):
        return True
    definition = find_type(question.custom_type)
    return question.type.value == "personalizzata" and bool(
        definition and definition.correzione == "soluzione" or definition is None and question.pregenerated_material)
