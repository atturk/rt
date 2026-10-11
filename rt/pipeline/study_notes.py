"""VC1: esecuzione dei job study_note (Verifica e Chiedi)."""
import hashlib
from typing import Any, Optional

from rt.core.models import Anchor
from rt.llm.client import LLMClient
from rt.llm.lesson_context import lesson_context_prompt
from rt.llm.prompts import (
    STUDY_NOTE_CHIEDI_SYSTEM_PROMPT,
    STUDY_NOTE_VERIFICA_SYSTEM_PROMPT,
    StudyNoteChiediResponse,
    StudyNoteVerificaResponse,
)
from rt.llm.telemetry import current_telemetry
from rt.pipeline.anchors import locate, make_anchor
from rt.pipeline.ledger import load_resolved_draft
from rt.services.study_notes_service import add_study_note


DEFAULT_VERIFICA_REQUEST = "Verifica la correttezza concettuale e scientifica di questo passaggio."
DEFAULT_CHIEDI_REQUEST = "Spiega questo passaggio in modo chiaro e comprensibile."


def run_study_note(
    lesson_dir: str,
    unit_id: str,
    kind: str,
    anchor: dict[str, Any],
    request: str = "",
    lesson_id: Optional[int] = None,
    force_mock: bool = False,
) -> dict[str, Any]:
    """Esegue una verifica o richiesta di spiegazione (Chiedi) su un passaggio selezionato."""
    if kind not in ("verifica", "chiedi"):
        raise ValueError(f"Tipo non riconosciuto: {kind}")

    draft = load_resolved_draft(lesson_dir)
    unit = next((u for u in draft.units if u.unit_id == unit_id), None)
    if unit is None:
        raise KeyError(f"Unità {unit_id} non trovata nella bozza.")

    anchor_obj = Anchor.model_validate(anchor)
    located = locate(anchor_obj, unit.content)
    if not located:
        raise ValueError("Il testo selezionato è cambiato o non si ritrova. Selezionalo di nuovo.")

    exact_anchor = make_anchor(unit.content, located.start, located.end)
    unit_fingerprint = hashlib.sha256(unit.content.encode("utf-8")).hexdigest()

    system_prompt = STUDY_NOTE_VERIFICA_SYSTEM_PROMPT if kind == "verifica" else STUDY_NOTE_CHIEDI_SYSTEM_PROMPT
    response_model = StudyNoteVerificaResponse if kind == "verifica" else StudyNoteChiediResponse
    prompt_prefix = lesson_context_prompt(lesson_dir)

    effective_request = request.strip() if request and request.strip() else (
        DEFAULT_VERIFICA_REQUEST if kind == "verifica" else DEFAULT_CHIEDI_REQUEST
    )

    user_prompt = (
        f"UNITÀ {unit.unit_id} - {unit.title}:\n{unit.content}\n\n"
        f"TESTO SELEZIONATO:\n{exact_anchor.quote}\n\n"
        f"RICHIESTA DELLO STUDENTE:\n{effective_request}"
    )

    client = LLMClient(force_mock=force_mock)
    response_obj = client.call_structured(
        prompt=user_prompt,
        system_prompt=system_prompt,
        prompt_prefix=prompt_prefix,
        response_model=response_model,
        job_name="review",
        unit_id=unit.unit_id,
        constrained_schema=True,
        lesson_dir=lesson_dir,
    )

    last_t = current_telemetry().get_last()
    model_name = last_t.model if last_t else None
    cost_usd = last_t.estimated_cost if last_t else 0.0

    if lesson_id is None:
        from sqlalchemy import select
        from rt.db.engine import get_database
        from rt.db.models import Lesson
        from rt.db.repositories import normalize_lesson_path
        from rt.db.session import read_scope
        with read_scope(get_database()) as session:
            row = session.scalar(select(Lesson).where(Lesson.path == normalize_lesson_path(lesson_dir)))
            if row:
                lesson_id = row.id

    if lesson_id is None:
        raise ValueError(f"Lezione non trovata nel database per il percorso: {lesson_dir}")

    saved = add_study_note(
        lesson_id=lesson_id,
        unit_id=unit.unit_id,
        kind=kind,
        anchor=exact_anchor.model_dump(),
        unit_fingerprint=unit_fingerprint,
        request=request.strip(),
        response=response_obj.model_dump(),
        model=model_name,
        cost=cost_usd,
    )
    return {"note_id": saved["id"], "note": saved}
