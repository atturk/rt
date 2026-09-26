"""Lezioni: elenco, dettaglio, stato delle fasi, documento, audio, export, outline, issue, costi."""
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.services import lesson_service
from rt.storage import fs

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
    from rt.services.audio_service import playable_audio
    return FileResponse(playable_audio(_audio_path(lesson_dir)))


def _audio_path(lesson_dir: str) -> str:
    path = lesson_service.lesson_audio_file(lesson_dir)
    if path is None:
        raise ApiError(404, "audio_not_found", "Nessun audio disponibile per questa lezione.")
    return path


@router.get("/lessons/{lesson_id}/audio/waveform", response_model=schemas.Waveform,
            summary="Forma d'onda dell'audio per il player (ready=false mentre si calcola)")
def get_waveform(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.audio_service import waveform
    peaks = waveform(_audio_path(lesson_dir))
    return {"ready": peaks is not None, "peaks": peaks or []}


@router.get("/lessons/{lesson_id}/export",
            summary="Scarica il Markdown finale (o l'anteprima dalla bozza) o un archivio con i dati della lezione",
            description="Usa il documento finale se esiste ed è aggiornato; altrimenti, con la bozza pronta, "
                        "l'anteprima che il build produrrebbe ora: il nome dei file contiene \"(anteprima)\" e "
                        "lo zip ha un LEGGIMI che lo spiega.",
            response_class=Response,
            responses={200: {"content": {"text/markdown": {}, "application/zip": {}},
                             "description": "File da salvare (Content-Disposition: attachment)"}})
def export_lesson(
    lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
    format: Literal["markdown", "zip"] = Query("markdown", description="markdown: solo il documento finale; "
                                               "zip: archivio con i file scelti da scope"),
    scope: Literal["final", "all"] = Query("final", description="final: Markdown finale, errori concettuali e "
                                           "immagini richiamate; all: tutti i file della lezione, audio compreso"),
):
    from urllib.parse import quote
    from rt.storage.export import ExportError, export_zip, final_markdown, zip_name
    try:
        if format == "markdown":
            filename, content = final_markdown(lesson_dir)
            media_type = "text/markdown; charset=utf-8"
        else:
            content = export_zip(lesson_dir, scope)
            filename = zip_name(lesson_dir)
            media_type = "application/zip"
    except ExportError as exc:
        raise ApiError(404, "export_not_available", str(exc))
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get("/lessons/{lesson_id}/outline", response_model=schemas.Outline,
            summary="Outline ad albero con stato di approvazione")
def get_outline(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.outline import get_outline_path
    from rt.services.outline_service import get_outline_review
    import os
    if not fs.isfile(get_outline_path(lesson_dir)):
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
