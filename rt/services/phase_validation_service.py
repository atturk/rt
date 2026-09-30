"""
rt.services.phase_validation_service
Validazione manuale di una fase ('rt validate-phase', POST /lessons/{id}/phases/{fase}/validate):
una fase STALE per una modifica voluta ai suoi file (o per un file toccato da un bug) torna
VALID con gli input attuali senza rieseguirla. Il checkpoint lo scrive
rt.core.idempotency.record_manual_validation; qui i controlli comuni a CLI e API: nessun job in
coda o in esecuzione sulla lezione e nessun editor del documento aperto.
"""
import logging
from typing import Any, Dict, Optional

from rt.services.errors import Conflict, Invalid

LOG = logging.getLogger(__name__)

VALIDATABLE_PHASES = ("prepare", "outline", "rewrite", "review", "build")


def _ensure_lesson_free(lesson_dir: str, lesson_id: Optional[int]) -> None:
    """Conflict se un job sta per scrivere sulla lezione o il documento è aperto nell'editor.
    Senza database (CLI senza DB) non c'è coda né lease da controllare."""
    from rt.db.engine import get_database
    db = get_database()
    if db is None:
        return
    from sqlalchemy import select
    from rt.db.models import Job
    from rt.db.repositories import normalize_lesson_path
    from rt.db.session import session_scope
    from rt.services.jobs import JobState
    with session_scope(db) as session:
        busy = session.scalar(select(Job).where(
            Job.lesson_path == normalize_lesson_path(lesson_dir),
            Job.state.in_([JobState.QUEUED.value, JobState.RUNNING.value])).limit(1))
        if busy is not None:
            raise Conflict("lesson_busy", "Un job sta lavorando su questa lezione: riprova quando ha finito.",
                           {"job_id": busy.id, "type": busy.type})
    if lesson_id is not None:
        from rt.services.document_edit_lease import assert_editable
        assert_editable(lesson_id)


def validate_phase(lesson_dir: str, phase: str, *, lesson_id: Optional[int] = None,
                   actor: str = "user", channel: str = "cli") -> Dict[str, Any]:
    """Segna la fase VALID per gli input attuali senza rieseguirla. Invalid per una fase
    sconosciuta; Conflict (phase_not_validatable) se l'artefatto manca o non è valido, se una
    fase a monte non è valida o se la fase è incompleta; Conflict (lesson_busy,
    document_edit_busy) se la lezione è occupata."""
    from rt.core.idempotency import ManualValidationRefused, record_manual_validation
    if phase not in VALIDATABLE_PHASES:
        raise Invalid("validation_error", f"Fase sconosciuta: {phase}. Fasi: {', '.join(VALIDATABLE_PHASES)}.")
    _ensure_lesson_free(lesson_dir, lesson_id)
    try:
        result = record_manual_validation(lesson_dir, phase, actor=actor, channel=channel)
    except ManualValidationRefused as exc:
        raise Conflict("phase_not_validatable", str(exc),
                       {"phase": phase, "status": exc.status.value if exc.status else None, "reason": exc.reason})
    if result["changed"]:
        LOG.info("Fase %s validata manualmente in %s da %s (%s); prima era %s: %s", phase, lesson_dir,
                 actor, channel, result["previous_status"], result["previous_reason"])
    return result
