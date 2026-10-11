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
