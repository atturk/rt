"""Decisioni umane: approvazione e revisione dell'outline, decisioni sulle issue, annullamento.
Le unità finite si possono decidere durante una verifica; le altre scritture attive
restano bloccate con 409. Ogni decisione conserva il canale e l'attore."""
from fastapi import APIRouter
from rt.core.lesson_lock import lesson_locked

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job, ensure_no_running_job, ensure_issue_decidable
from rt.storage import fs

router = APIRouter(tags=["decisioni"])


@router.post("/lessons/{lesson_id}/outline/approve", response_model=schemas.Outline,
             summary="Approva l'outline corrente (la pipeline in attesa riparte da sola)")
def approve_outline(lesson_id: int, lesson_dir: LessonDir, actor: Actor):
    import os
    from rt.pipeline.outline import get_outline_path
    from rt.services import outline_service
    ensure_no_running_job(lesson_dir)
    if not fs.isfile(get_outline_path(lesson_dir)):
        raise ApiError(404, "outline_not_found", "Outline non ancora generata.")
    outline_service.approve_outline(lesson_dir, actor=actor, channel="api")
    return outline_service.get_outline_review(lesson_dir)


@router.post("/lessons/{lesson_id}/outline/suspend", response_model=schemas.Outline,
             summary="Sospende il conto alla rovescia per l'approvazione automatica della scaletta")
def suspend_outline(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.outline import get_outline_path
    from rt.services import outline_service
    ensure_no_running_job(lesson_dir)
    if not fs.isfile(get_outline_path(lesson_dir)):
        raise ApiError(404, "outline_not_found", "Outline non ancora generata.")
    outline_service.suspend_outline_timer(lesson_dir)
    return outline_service.get_outline_review(lesson_dir)


@router.post("/lessons/{lesson_id}/outline/revise", response_model=schemas.JobAccepted, status_code=202,
             summary="Rigenera l'outline con un feedback (job)")
def revise_outline(lesson_id: int, body: schemas.OutlineRevision, lesson_dir: LessonDir, actor: Actor):
    ensure_no_running_job(lesson_dir)
    return enqueue_job("outline_revision", lesson_dir, {"feedback": body.feedback, "mock": body.mock, "actor": actor})


@router.post("/lessons/{lesson_id}/issues/{issue_id}/decision", response_model=schemas.Decision,
             summary="Decide un'issue: accepted, rejected o edited (con testo)")
@lesson_locked
def decide_issue(lesson_id: int, issue_id: str, body: schemas.DecisionRequest, lesson_dir: LessonDir, actor: Actor):
    from rt.services.review_service import (
        ReviewDecisionError, is_review_complete, mark_ready_to_build, record_review_decision,
    )
    ensure_issue_decidable(lesson_dir, issue_id)
    try:
        decision = record_review_decision(
            lesson_dir, issue_id, body.decision, body.text, channel="api", actor=actor,
            resolved_by="api", notes=body.notes, validate=True,
        )
    except ReviewDecisionError as exc:
        raise ApiError(409, exc.reason if exc.reason in {"claim_changed", "suggestion_only"} else "decision_rejected", str(exc))
    if is_review_complete(lesson_dir):
        mark_ready_to_build(lesson_dir)  # come a fine review da terminale o da Telegram
    return decision.model_dump(mode="json")


@router.post("/lessons/{lesson_id}/decisions/undo", response_model=schemas.Decision,
             summary="Annulla l'ultima decisione su un'issue")
@lesson_locked
def undo_decision(lesson_id: int, body: schemas.UndoRequest, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.review_service import ReviewDecisionError, undo_last_decision
    ensure_issue_decidable(lesson_dir, body.issue_id)
    try:
        return undo_last_decision(lesson_dir, body.issue_id).model_dump(mode="json")
    except ReviewDecisionError as exc:
        raise ApiError(409 if exc.reason != "missing" else 404, "undo_rejected", str(exc))


@router.get("/lessons/{lesson_id}/review/units", response_model=list[schemas.ReviewUnit],
            summary="Stato della verifica scientifica per ogni unità")
def get_review_units(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.review_service import review_units
    from rt.pipeline.rewrite import get_draft_path
    return review_units(lesson_dir) if fs.isfile(get_draft_path(lesson_dir)) else []
