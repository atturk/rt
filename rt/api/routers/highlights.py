"""
rt.api.routers.highlights
Router per le evidenziazioni dello Studio (web-highlighter).
"""
from typing import List, Optional

from fastapi import APIRouter, Query, Response, status

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.services import highlights_service

router = APIRouter(tags=["evidenziatore"])


@router.get("/lessons/{lesson_id}/highlights", response_model=List[schemas.HighlightOut],
            summary="Elenco delle evidenziazioni di una lezione (o filtrate per unità)")
def list_highlights(lesson_id: int, _lesson_dir: LessonDir, _actor: Actor,
                    unit: Optional[str] = Query(None, description="Filtra per unità (es. '1.3')")):
    return highlights_service.list_highlights(lesson_id=lesson_id, unit_id=unit)


@router.post("/lessons/{lesson_id}/highlights", response_model=schemas.HighlightOut,
             status_code=status.HTTP_201_CREATED,
             summary="Crea una nuova evidenziazione")
def create_highlight(lesson_id: int, body: schemas.HighlightCreate, _lesson_dir: LessonDir, _actor: Actor):
    return highlights_service.create_highlight(
        lesson_id=lesson_id,
        unit_id=body.unit_id,
        color=body.color,
        source=body.source,
    )


@router.delete("/lessons/{lesson_id}/highlights/{hid}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Elimina una singola evidenziazione")
def delete_highlight(lesson_id: int, hid: int, _lesson_dir: LessonDir, _actor: Actor):
    highlights_service.delete_highlight(lesson_id=lesson_id, highlight_id=hid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/lessons/{lesson_id}/highlights", status_code=status.HTTP_204_NO_CONTENT,
               summary="Elimina tutte le evidenziazioni di un'unità")
def delete_unit_highlights(lesson_id: int, _lesson_dir: LessonDir, _actor: Actor,
                           unit: str = Query(..., description="Id dell'unità da ripulire")):
    highlights_service.delete_unit_highlights(lesson_id=lesson_id, unit_id=unit)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
