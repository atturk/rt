"""Decisioni umane: approvazione e revisione dell'outline, decisioni sulle issue, annullamento.
Ogni decisione registra channel=api e l'attore; con un job mutante in corso sulla lezione la
scrittura è rifiutata con 409."""
from fastapi import APIRouter

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job, ensure_no_running_job

router = APIRouter(tags=["decisioni"])


@router.post("/lessons/{lesson_id}/outline/approve", response_model=schemas.Outline,
             summary="Approva l'outline corrente (la pipeline in attesa riparte da sola)")
def approve_outline(lesson_id: int, lesson_dir: LessonDir, actor: Actor):
    import os
    from rt.pipeline.outline import get_outline_path
    from rt.services import outline_service
    ensure_no_running_job(lesson_dir)
    if not os.path.isfile(get_outline_path(lesson_dir)):
        raise ApiError(404, "outline_not_found", "Outline non ancora generata.")
    outline_service.approve_outline(lesson_dir, actor=actor, channel="api")
    return outline_service.get_outline_review(lesson_dir)


@router.post("/lessons/{lesson_id}/outline/revise", response_model=schemas.JobAccepted, status_code=202,
             summary="Rigenera l'outline con un feedback (job)")
def revise_outline(lesson_id: int, body: schemas.OutlineRevision, lesson_dir: LessonDir, actor: Actor):
    ensure_no_running_job(lesson_dir)
    return enqueue_job("outline_revision", lesson_dir, {"feedback": body.feedback, "mock": body.mock, "actor": actor})


@router.post("/lessons/{lesson_id}/issues/{issue_id}/decision", response_model=schemas.Decision,
             summary="Decide un'issue: accepted, rejected o edited (con testo)")
def decide_issue(lesson_id: int, issue_id: str, body: schemas.DecisionRequest, lesson_dir: LessonDir, actor: Actor):
    from rt.services.review_service import ReviewDecisionError, record_review_decision
    ensure_no_running_job(lesson_dir)
    try:
        decision = record_review_decision(
            lesson_dir, issue_id, body.decision, body.text, channel="api", actor=actor,
            resolved_by="api", notes=body.notes, validate=True,
        )
    except ReviewDecisionError as exc:
        raise ApiError(409, "decision_rejected", str(exc))
    return decision.model_dump(mode="json")


@router.post("/lessons/{lesson_id}/decisions/undo", response_model=schemas.Decision,
             summary="Annulla l'ultima decisione su un'issue")
def undo_decision(lesson_id: int, body: schemas.UndoRequest, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.review_service import ReviewDecisionError, undo_last_decision
    ensure_no_running_job(lesson_dir)
    try:
        return undo_last_decision(lesson_dir, body.issue_id).model_dump(mode="json")
    except ReviewDecisionError as exc:
        raise ApiError(409 if exc.reason != "missing" else 404, "undo_rejected", str(exc))
