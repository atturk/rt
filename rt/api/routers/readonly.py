"""
rt.api.routers.readonly
Router per l'API di sola lettura (AP1) per Open WebUI e strumenti locali.
Fornisce 4 operazioni:
1. cerca nel testo delle lezioni (SQLite FTS5, filtri materia e date)
2. elenco lezioni
3. scaletta di una lezione
4. testo di un'unità
Include /openapi.json dedicato per l'importazione diretta in Open WebUI.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field
from sqlalchemy import select

from rt.api.errors import ApiError
from rt.api.readonly_auth import require_readonly_auth
from rt.db.engine import get_database
from rt.db.models import Lesson
from rt.db.session import read_scope
from rt.pipeline.ledger import load_resolved_draft
from rt.services.fts_service import search_lessons_fts

router = APIRouter(
    prefix="/readonly",
    tags=["readonly"],
)


class LessonSearchResult(BaseModel):
    lesson_id: int = Field(..., description="ID della lezione")
    unit_id: str = Field(..., description="ID dell'unità")
    subject: str = Field(..., description="Materia")
    date: str = Field(..., description="Data della lezione (YYYY-MM-DD)")
    title: str = Field(..., description="Titolo dell'unità o della lezione")
    snippet: str = Field(..., description="Estratto con parole cercate evidenziate")


class ReadonlyLessonSummary(BaseModel):
    id: int = Field(..., description="ID della lezione")
    title: str = Field(..., description="Titolo della lezione")
    subject: str = Field(..., description="Materia")
    date: str = Field(..., description="Data della lezione")
    workflow_state: str = Field(..., description="Stato della lezione")
    created_at: Optional[str] = Field(None, description="Data di creazione")


class LessonOutlineUnit(BaseModel):
    unit_id: str = Field(..., description="Identificativo dell'unità")
    title: str = Field(..., description="Titolo dell'unità")
    order: int = Field(..., description="Ordine sequenziale")


class LessonOutline(BaseModel):
    lesson_id: int = Field(..., description="ID della lezione")
    title: str = Field(..., description="Titolo della lezione")
    subject: str = Field(..., description="Materia")
    units: List[LessonOutlineUnit] = Field(..., description="Elenco delle unità della lezione")


class LessonUnitText(BaseModel):
    lesson_id: int = Field(..., description="ID della lezione")
    unit_id: str = Field(..., description="Identificativo dell'unità")
    title: str = Field(..., description="Titolo dell'unità")
    content: str = Field(..., description="Testo completo dell'unità")


@router.get(
    "/lessons/search",
    response_model=List[LessonSearchResult],
    operation_id="searchLessons",
    summary="Cerca nel testo delle lezioni",
    description="Esegue una ricerca full-text nelle unità delle lezioni con filtri opzionali su materia e date.",
)
def search_lessons(
    q: str = Query(..., description="Testo o parole chiave da cercare"),
    subject: Optional[str] = Query(None, description="Filtra per materia (es. BIOCHIMICA)"),
    date_from: Optional[str] = Query(None, description="Data minima (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Data massima (YYYY-MM-DD)"),
    limit: int = Query(10, ge=1, le=50, description="Numero massimo di risultati"),
    _actor: str = Depends(require_readonly_auth),
) -> List[LessonSearchResult]:
    hits = search_lessons_fts(
        query=q,
        subject=subject,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return [LessonSearchResult(**h) for h in hits]


@router.get(
    "/lessons",
    response_model=List[ReadonlyLessonSummary],
    operation_id="listLessons",
    summary="Elenco lezioni",
    description="Restituisce l'elenco delle lezioni registrate, ordinabili con filtri per materia e date.",
)
def list_lessons(
    subject: Optional[str] = Query(None, description="Filtro per materia"),
    date_from: Optional[str] = Query(None, description="Data minima (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Data massima (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=100, description="Numero massimo di lezioni"),
    _actor: str = Depends(require_readonly_auth),
) -> List[ReadonlyLessonSummary]:
    db = get_database()
    if db is None:
        raise ApiError(503, "database_unavailable", "Database non disponibile.")

    query = select(Lesson).order_by(Lesson.data.desc(), Lesson.id.desc())
    if subject and subject.strip():
        query = query.where(Lesson.materia == subject.strip().upper())
    if date_from and date_from.strip():
        query = query.where(Lesson.data >= date_from.strip())
    if date_to and date_to.strip():
        query = query.where(Lesson.data <= date_to.strip())

    query = query.limit(limit)

    with read_scope(db) as session:
        lessons = session.scalars(query).all()
        results = []
        for l in lessons:
            created = l.created_at.isoformat() if l.created_at else None
            results.append(
                ReadonlyLessonSummary(
                    id=l.id,
                    title=l.titolo or l.folder_name,
                    subject=l.materia or "",
                    date=l.data or "",
                    workflow_state=l.workflow_state or "",
                    created_at=created,
                )
            )
        return results


@router.get(
    "/lessons/{lesson_id}/outline",
    response_model=LessonOutline,
    operation_id="getLessonOutline",
    summary="Scaletta di una lezione",
    description="Restituisce la scaletta e i titoli delle unità della lezione indicata.",
)
def get_lesson_outline(
    lesson_id: int = Path(..., description="ID univoco della lezione"),
    _actor: str = Depends(require_readonly_auth),
) -> LessonOutline:
    db = get_database()
    if db is None:
        raise ApiError(503, "database_unavailable", "Database non disponibile.")

    with read_scope(db) as session:
        lesson = session.scalar(select(Lesson).where(Lesson.id == lesson_id))
        if lesson is None:
            raise ApiError(404, "lesson_not_found", f"Lezione {lesson_id} non trovata.")

        try:
            draft = load_resolved_draft(lesson.path)
            units = [
                LessonOutlineUnit(unit_id=u.unit_id, title=u.title or "", order=idx + 1)
                for idx, u in enumerate(draft.units)
            ]
        except Exception:
            units = []

        return LessonOutline(
            lesson_id=lesson.id,
            title=lesson.titolo or lesson.folder_name,
            subject=lesson.materia or "",
            units=units,
        )


@router.get(
    "/lessons/{lesson_id}/units/{unit_id}",
    response_model=LessonUnitText,
    operation_id="getLessonUnit",
    summary="Testo di un'unità",
    description="Restituisce il contenuto testuale completo dell'unità richiesta.",
)
def get_lesson_unit(
    lesson_id: int = Path(..., description="ID univoco della lezione"),
    unit_id: str = Path(..., description="ID dell'unità (es. 1.1)"),
    _actor: str = Depends(require_readonly_auth),
) -> LessonUnitText:
    db = get_database()
    if db is None:
        raise ApiError(503, "database_unavailable", "Database non disponibile.")

    with read_scope(db) as session:
        lesson = session.scalar(select(Lesson).where(Lesson.id == lesson_id))
        if lesson is None:
            raise ApiError(404, "lesson_not_found", f"Lezione {lesson_id} non trovata.")

        try:
            draft = load_resolved_draft(lesson.path)
            unit = next((u for u in draft.units if u.unit_id == unit_id), None)
        except Exception as e:
            raise ApiError(500, "draft_load_failed", f"Impossibile leggere il documento: {e}")

        if unit is None:
            raise ApiError(404, "unit_not_found", f"Unità {unit_id} non trovata nella lezione {lesson_id}.")

        return LessonUnitText(
            lesson_id=lesson.id,
            unit_id=unit.unit_id,
            title=unit.title or "",
            content=unit.content or "",
        )


@router.get(
    "/openapi.json",
    include_in_schema=False,
)
def get_readonly_openapi(request: Request) -> Dict[str, Any]:
    """Restituisce lo schema OpenAPI 3.0 dedicato per configurare le Actions in Open WebUI."""
    # Crea una mini-app temporanea con solo le rotte di questo router
    from fastapi import FastAPI
    mini_app = FastAPI(
        title="RT Readonly API for Open WebUI",
        version="4.2.5",
        description="API di sola lettura su 127.0.0.1 per consultare lezioni, scalette e testo con Open WebUI.",
        servers=[{"url": f"{request.base_url.scheme}://{request.base_url.netloc}/api/v1/readonly"}],
    )
    # Aggiungi le rotte
    for route in router.routes:
        if route.path != "/openapi.json":
            mini_app.routes.append(route)
    return get_openapi(
        title=mini_app.title,
        version=mini_app.version,
        description=mini_app.description,
        routes=mini_app.routes,
        servers=mini_app.servers,
    )
