"""Lezioni: elenco, dettaglio, stato delle fasi, documento, audio, export, outline, issue, costi."""
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

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
    from rt.services.lesson_delete_service import recover_pending_deletions
    recover_pending_deletions()
    return lesson_service.list_lessons(materia=materia, state=state, text=q)


@router.delete("/lessons/{lesson_id}", status_code=204, summary="Elimina una lezione e i suoi media")
def delete_lesson(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.lesson_delete_service import delete_lesson as delete
    delete(lesson_id, lesson_dir)


@router.get("/lessons/{lesson_id}", response_model=schemas.LessonDetail,
            summary="Dettaglio di una lezione: fasi, costi, stato (come 'rt status' e 'rt cost')")
def get_lesson(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.lesson_detail(lesson_id, lesson_dir)


@router.get("/lessons/{lesson_id}/phases", response_model=schemas.PhaseReport,
            summary="Freschezza delle fasi e report di validazione di outline e draft")
def get_phases(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.phase_report(lesson_dir)


@router.post("/lessons/{lesson_id}/phases/{phase}/validate", response_model=schemas.PhaseValidationResult,
             summary="Valida a mano una fase senza rieseguirla (come 'rt validate-phase')",
             description="Registra la fase come VALID per gli input attuali (per esempio dopo una modifica "
                         "voluta ai suoi file). 409 phase_not_validatable se l'artefatto manca o non è "
                         "valido, se una fase a monte non è valida o se la fase è incompleta; 409 "
                         "lesson_busy con un job in coda o in esecuzione sulla lezione.")
def validate_phase(lesson_id: int, phase: Literal["prepare", "outline", "rewrite", "review", "build"],
                   lesson_dir: LessonDir, actor: Actor):
    from rt.services.phase_validation_service import validate_phase as validate
    return validate(lesson_dir, phase, lesson_id=lesson_id, actor=str(actor), channel="api")


@router.get("/lessons/{lesson_id}/document", response_model=schemas.LessonDocument,
            summary="Documento Markdown finale (o anteprima) con HTML sanificato e timecode")
def get_document(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    return lesson_service.lesson_document(lesson_dir)


@router.get("/lessons/{lesson_id}/relevance", response_model=schemas.UnitRelevanceOverview,
            summary="Classificazioni del classificatore, correzioni per ogni unità e riepilogo")
def get_unit_relevance(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.unit_relevance import list_units
    return list_units(lesson_dir)


@router.post("/lessons/{lesson_id}/relevance/run", response_model=schemas.JobAccepted, status_code=202,
             summary="Accoda l'attribuzione delle etichette del classificatore alle unità (come 'rt relevance'); 409 relevance_disabled se il classificatore è spento")
def run_unit_relevance(lesson_id: int, body: schemas.UnitRelevanceRun, lesson_dir: LessonDir, actor: Actor):
    from rt.api.jobs import enqueue_job
    from rt.services.unit_relevance import ensure_can_run
    ensure_can_run()
    return enqueue_job("unit_relevance", lesson_dir, {"force": body.force, "mock": body.mock}, actor)


@router.put("/lessons/{lesson_id}/relevance/{unit_id}", response_model=schemas.UnitRelevanceOverview,
            summary="Corregge o ripristina la classificazione di un'unità")
def put_unit_relevance(lesson_id: int, unit_id: str, body: schemas.UnitRelevanceOverride,
                       lesson_dir: LessonDir, actor: Actor):
    from rt.services.unit_relevance import set_override
    try:
        return set_override(lesson_dir, unit_id, body.category, actor=str(actor))
    except KeyError:
        raise ApiError(404, "unit_not_found", "Unità non trovata nella bozza.")


@router.post("/lessons/{lesson_id}/document/check", response_model=schemas.DocumentEditCheck,
             summary="Anteprima e controllo del Markdown modificato, senza salvare (funzione beta)")
def check_document(lesson_id: int, body: schemas.DocumentEditIn, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.document_edit_service import check_document_edit
    return check_document_edit(lesson_dir, body.markdown)


@router.post("/lessons/{lesson_id}/document/lease", response_model=schemas.DocumentEditLease)
def acquire_document_lease(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                           token: Optional[str] = None, recover: bool = False):
    from rt.services.document_edit_lease import acquire
    return acquire(lesson_id, token, recover=recover)


@router.delete("/lessons/{lesson_id}/document/lease", status_code=204)
def release_document_lease(lesson_id: int, lesson_dir: LessonDir, _actor: Actor, token: str):
    from rt.services.document_edit_lease import release
    release(lesson_id, token)


@router.put("/lessons/{lesson_id}/document/draft", response_model=schemas.DocumentEditResult,
            summary="Salva l'anteprima modificata nella bozza: testo, titoli, timecode, immagini (funzione beta)")
def put_document_draft(lesson_id: int, body: schemas.DocumentEditIn, lesson_dir: LessonDir, _actor: Actor):
    from rt.api.jobs import ensure_no_running_job
    from rt.services.document_edit_lease import assert_editable
    from rt.services.document_edit_service import DocumentEditError, save_document_edit
    ensure_no_running_job(lesson_dir)
    assert_editable(lesson_id, body.lease_token)
    try:
        return save_document_edit(lesson_dir, body.markdown)
    except DocumentEditError as exc:
        raise ApiError(422, "document_invalid", "L'anteprima modificata non si può salvare: " + str(exc),
                       {"errors": exc.errors})


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
    from rt.storage.export import ExportError, export_zip_to_tempfile, final_markdown, zip_name
    try:
        if format == "markdown":
            filename, content = final_markdown(lesson_dir)
            media_type = "text/markdown; charset=utf-8"
        else:
            path = export_zip_to_tempfile(lesson_dir, scope)
            filename = zip_name(lesson_dir)
            disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
            return FileResponse(path, media_type="application/zip", filename=filename,
                                headers={"Content-Disposition": disposition},
                                background=BackgroundTask(os.unlink, path))
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
