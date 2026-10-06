"""Stato di studio e letture delle unità."""
from typing import Annotated

from fastapi import APIRouter, Path, Response

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.services import study_progress_service

router = APIRouter(tags=["studio"])
UnitId = Annotated[str, Path(min_length=1, max_length=64)]


@router.put("/lessons/{lesson_id}/study/units/{unit_id}", response_model=schemas.StudyProgress,
            summary="Cambia lo stato di studio di un'unità")
def set_status(lesson_id: int, unit_id: UnitId, body: schemas.StudyStatusUpdate, _dir: LessonDir, _actor: Actor):
    return study_progress_service.set_status(lesson_id, _dir, unit_id, body.status)


@router.post("/lessons/{lesson_id}/study/units/{unit_id}/read", status_code=204,
             summary="Segna l'ultima lettura di un'unità")
def mark_read(lesson_id: int, unit_id: UnitId, _dir: LessonDir, _actor: Actor):
    study_progress_service.mark_read(lesson_id, _dir, unit_id)
    return Response(status_code=204)
