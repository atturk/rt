"""Lezioni: elenco, dettaglio, stato delle fasi, documento, audio, outline, issue, costi."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.services import lesson_service

router = APIRouter(tags=["lezioni"])


def _lesson_id(lesson_dir: str) -> int:
    lesson_id = lesson_service.lesson_id_for_dir(lesson_dir)
    if lesson_id is None:
        raise ApiError(404, "lesson_not_found", "Lezione non trovata.")
    return lesson_id


@router.get("/lessons", response_model=List[schemas.LessonSummary], summary="Elenco delle lezioni (come la dashboard)")
def list_lessons(
    _actor: Actor,
    materia: Optional[str] = Query(None, description="Filtra per materia"),
    state: Optional[str] = Query(None, description="Filtra per stato del workflow (es. completato)"),
    q: Optional[str] = Query(None, description="Testo libero su cartella, titolo, argomenti"),
):
    return lesson_service.list_lessons(materia=materia, state=state, text=q)


@router.get("/lessons/{lesson_id}", response_model=schemas.LessonDetail,
            summary="Dettaglio di una lezione: fasi, costi, stato (come 'rt status' e 'rt cost')")
def get_lesson(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.lesson_detail(lesson_id, lesson_dir)


@router.get("/lessons/{lesson_id}/phases", response_model=schemas.PhaseReport,
            summary="Freschezza delle fasi e report di validazione di outline e draft")
def get_phases(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.phase_report(lesson_dir)


@router.get("/lessons/{lesson_id}/document", response_model=schemas.LessonDocument,
            summary="Documento Markdown finale (o anteprima) con HTML sanificato e timecode")
def get_document(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.lesson_document(lesson_dir)


@router.get("/lessons/{lesson_id}/audio", summary="Audio della lezione (supporta Range)",
            response_class=FileResponse, responses={200: {"content": {"audio/*": {}}}, 206: {"description": "Contenuto parziale"}})
def get_audio(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    path = lesson_service.lesson_audio_file(lesson_dir)
    if path is None:
        raise ApiError(404, "audio_not_found", "Nessun audio disponibile per questa lezione.")
    return FileResponse(path)


@router.get("/lessons/{lesson_id}/outline", response_model=schemas.Outline,
            summary="Outline ad albero con stato di approvazione")
def get_outline(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.outline import get_outline_path
    from rt.services.outline_service import get_outline_review
    import os
    if not os.path.isfile(get_outline_path(lesson_dir)):
        raise ApiError(404, "outline_not_found", "Outline non ancora generata.")
    return get_outline_review(lesson_dir)


@router.get("/lessons/{lesson_id}/issues", response_model=schemas.IssueList,
            summary="Issue della review con contesto (unità, timecode, finestra audio)")
def get_issues(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
               status: Literal["pending", "all"] = Query("pending", description="pending: solo da decidere")):
    from rt.pipeline.ledger import load_ledger
    from rt.pipeline.review import load_science_issues
    from rt.services.review_service import issue_context, is_review_complete
    issues = load_science_issues(lesson_dir)
    decisions = {}
    for d in load_ledger(lesson_dir).decisions:
        decisions[d.issue_id] = d
    items = []
    for issue in issues:
        decision = decisions.get(issue.id)
        if status == "pending" and decision is not None:
            continue
        items.append({
            "issue": issue.model_dump(mode="json"),
            "context": issue_context(lesson_dir, issue),
            "decision": decision.model_dump(mode="json") if decision else None,
        })
    pending = sum(1 for i in issues if i.id not in decisions)
    return {"pending": pending, "total": len(issues), "review_complete": is_review_complete(lesson_dir), "items": items}


@router.get("/lessons/{lesson_id}/decisions", response_model=List[schemas.Decision],
            summary="Ledger delle decisioni (review_decisions.json)")
def get_decisions(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.ledger import load_ledger
    return [d.model_dump(mode="json") for d in load_ledger(lesson_dir).decisions]


@router.get("/costs", response_model=schemas.CostSummary, summary="Riepilogo dei costi LLM di tutte le lezioni")
def get_costs(_actor: Actor):
    return lesson_service.costs_summary()
