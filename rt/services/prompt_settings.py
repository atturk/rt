"""Editable instructions, stored separately from the schema enforced by LLMClient."""

import hashlib
import json
import os

from rt.db.engine import get_database
from rt.db.models import Setting
from rt.db.session import session_scope

PROMPT_NAMES = ("outline", "rewrite", "review", "image_description", "recall")


def _read(key: str) -> str:
    db = get_database()
    if db is None:
        return ""
    with session_scope(db) as session:
        row = session.get(Setting, key)
        return str(row.value or "") if row else ""


def _write(key: str, value: str) -> None:
    with session_scope(get_database()) as session:
        row = session.get(Setting, key)
        if value:
            if row: row.value = value
            else: session.add(Setting(key=key, value=value))
        elif row:
            session.delete(row)


def global_instruction(phase: str) -> str:
    return _read(f"prompt_override:{phase}") if phase in PROMPT_NAMES else ""


def set_global_instruction(phase: str, value: str) -> None:
    if phase not in PROMPT_NAMES or len(value) > 20_000:
        raise ValueError("Nome del prompt o lunghezza non validi.")
    _write(f"prompt_override:{phase}", value.strip())


def extra_for(lesson_dir: str, phase: str) -> str:
    return _read(_extra_key(lesson_dir, phase))


def _extra_key(lesson_dir: str, phase: str) -> str:
    return f"prompt_extra:{phase}:{hashlib.sha256(os.path.realpath(lesson_dir).encode()).hexdigest()}"


def set_extra(lesson_dir: str, phase: str, text: str) -> None:
    if phase not in ("outline", "rewrite", "review") or len(text) > 10_000:
        raise ValueError("Istruzione della fase non valida.")
    _write(_extra_key(lesson_dir, phase), text.strip())


def effective_system(phase: str, default: str) -> str:
    instruction = global_instruction(phase)
    return default + ("\n\nIstruzioni personalizzate:\n" + instruction if instruction else "")


def append_extra(lesson_dir: str, phase: str, prompt: str) -> str:
    instruction = extra_for(lesson_dir, phase)
    return prompt + ("\n\nIstruzioni per questa esecuzione:\n" + instruction if instruction else "")


def settings_hash(lesson_dir: str, phase: str) -> str:
    from rt.core.config import load_config
    cfg = load_config()
    route = cfg.jobs.get(phase)
    inputs = {"global": global_instruction(phase), "extra": extra_for(lesson_dir, phase),
              "route": route.model_dump(mode="json") if route else None}
    if phase == "review":
        inputs["decision_model"] = cfg.jev.model_dump(mode="json")
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
