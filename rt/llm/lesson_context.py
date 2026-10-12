"""Prefisso deterministico condiviso dagli strumenti che esaminano una lezione."""
import json

from rt.services.recall_context import lesson_context


def lesson_context_prompt(lesson_dir: str) -> str:
    """Stesso blocco per tutte le unità, separato da testo selezionato e richieste."""
    context = lesson_context(lesson_dir, include_structure=True)
    return "CONTESTO DELLA LEZIONE:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2)
