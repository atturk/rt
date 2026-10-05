"""Evidenziazioni dello Studio: si vedono solo nello Studio, non toccano il documento."""
from typing import Any, List

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor, LessonDir
from rt.services import highlights_service

router = APIRouter(tags=["studio"])
UnitId = Query(min_length=1, max_length=64, description="Unità, es. 1.3")


class HighlightIn(BaseModel):
    unit_id: str = Field(min_length=1, max_length=64)
    color: int = Field(ge=0, le=4, description="Indice del colore: giallo, verde, azzurro, rosa, arancio")
    source: dict[str, Any] = Field(description="Serializzazione di web-highlighter (startMeta, endMeta, text, id)")


class Highlight(HighlightIn):
    id: int


@router.get("/lessons/{lesson_id}/highlights", response_model=List[Highlight], summary="Evidenziazioni di un'unità")
def list_highlights(lesson_id: int, _dir: LessonDir, _actor: Actor, unit: str = UnitId):
    return highlights_service.list_highlights(lesson_id, unit)


@router.post("/lessons/{lesson_id}/highlights", response_model=Highlight, status_code=201,
             summary="Aggiunge un'evidenziazione")
def add_highlight(lesson_id: int, body: HighlightIn, _dir: LessonDir, _actor: Actor):
    return highlights_service.add_highlight(lesson_id, body.unit_id, body.color, body.source)


@router.delete("/lessons/{lesson_id}/highlights/{highlight_id}", status_code=204, summary="Toglie un'evidenziazione")
def delete_highlight(lesson_id: int, highlight_id: int, _dir: LessonDir, _actor: Actor):
    highlights_service.delete_highlight(lesson_id, highlight_id)
    return Response(status_code=204)


@router.delete("/lessons/{lesson_id}/highlights", status_code=204, summary="Toglie tutte le evidenziazioni di un'unità")
def clear_highlights(lesson_id: int, _dir: LessonDir, _actor: Actor, unit: str = UnitId):
    highlights_service.clear_unit(lesson_id, unit)
    return Response(status_code=204)
