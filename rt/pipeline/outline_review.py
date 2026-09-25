"""
rt.pipeline.outline_review
Regola di gating della conferma outline, senza interfaccia. La UI da terminale
(confirm_or_revise_outline, OutlineReviewApp) è in rt.tui.outline_review; approvazione e
revisione come servizio sono in rt.services.outline_service.
"""
from rt.core.idempotency import check_phase_status, PhaseStatus


def outline_needs_approval(lesson_dir: str, force: bool = False) -> bool:
    """Si chiede conferma dell'outline solo se il rewrite non è già VALID, oppure con force.
    Nessuna conferma per singola unità: approvata l'outline, la pipeline procede da sola."""
    if force:
        return True
    phase_status, _ = check_phase_status(lesson_dir, "rewrite")
    return phase_status != PhaseStatus.VALID
