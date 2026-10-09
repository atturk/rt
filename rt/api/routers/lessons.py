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


@router.patch("/lessons/{lesson_id}/metadata", response_model=schemas.LessonDetail,
              summary="Modifica i metadati e rinomina la cartella; 409 con un job attivo")
def patch_metadata(lesson_id: int, body: schemas.LessonMetadataUpdate, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.lesson_metadata_service import update_metadata
    return update_metadata(lesson_id, lesson_dir, body.model_dump(exclude_unset=True))


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
def get_unit_relevance(lesson_id: int, lesson_dir: LessonDir, _actor: Actor, view: Literal["draft", "resolved"] = "draft"):
    from rt.services.unit_relevance import list_units
    return list_units(lesson_dir, view=view)


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


@router.get("/lessons/{lesson_id}/sections", response_model=schemas.SectionLabels,
            summary="Etichette nascoste delle unità (macro-sezioni) per casi clinici ed esercizi")
def get_section_labels(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.section_labels import view
    return view(lesson_dir)


@router.put("/lessons/{lesson_id}/sections/{section_id}", response_model=schemas.SectionLabels,
            summary="Corregge o ripristina l'etichetta caso clinico o esercizio di un'unità")
def put_section_label(lesson_id: int, section_id: str, body: schemas.SectionLabelOverride,
                      lesson_dir: LessonDir, _actor: Actor):
    from rt.services.section_labels import set_override
    try:
        return set_override(lesson_dir, section_id, body.kind, body.value)
    except KeyError:
        raise ApiError(404, "section_not_found", "Unità non trovata nella scaletta.")
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc))


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


@router.get("/lessons/{lesson_id}/document/pipeline-version", response_model=schemas.DocumentPipelineVersion,
            summary="Versione della pipeline disponibile e conteggio delle unità modificate")
def get_pipeline_version(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.document_restore_service import pipeline_version
    return pipeline_version(lesson_dir)


@router.post("/lessons/{lesson_id}/document/restore-pipeline", response_model=schemas.DocumentRestoreResult,
             summary="Ripristina testo, titoli, timecode e immagini; mantiene le decisioni della revisione")
def restore_pipeline(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                     body: schemas.DocumentRestoreIn = schemas.DocumentRestoreIn()):
    from rt.services.document_restore_service import restore_pipeline_version
    return restore_pipeline_version(lesson_id, lesson_dir, body.lease_token)


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
    study: bool = Query(False, description="Include lo stato di studio nello ZIP completo"),
):
    from urllib.parse import quote
    from rt.storage.export import ExportError, export_zip_to_tempfile, final_markdown, zip_name
    try:
        if format == "markdown":
            filename, content = final_markdown(lesson_dir)
            media_type = "text/markdown; charset=utf-8"
        else:
            path = export_zip_to_tempfile(lesson_dir, scope, study=study)
            filename = zip_name(lesson_dir)
            disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
            return FileResponse(path, media_type="application/zip", filename=filename,
                                headers={"Content-Disposition": disposition},
                                background=BackgroundTask(os.unlink, path))
    except ExportError as exc:
        raise ApiError(404, "export_not_available", str(exc))
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get("/lesson-exports", summary="Scarica più lezioni in un solo ZIP (es. un gruppo dell'elenco)",
            responses={200: {"content": {"application/zip": {}}, "description": "Archivio ZIP"}})
def export_lessons(
    _actor: Actor,
    ids: List[int] = Query(..., description="Id delle lezioni"),
    format: Literal["markdown", "zip"] = Query("markdown", description="markdown: i documenti finali aggiornati; "
                                               "zip: l'archivio completo di ogni lezione"),
    name: str = Query("lezioni", max_length=120, description="Nome del file scaricato (senza estensione)"),
    study: bool = Query(False, description="Include lo stato di studio negli archivi completi"),
):
    from urllib.parse import quote
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    from rt.storage.export import ExportError, export_many_to_tempfile, many_export_filename
    try:
        dirs = [resolve_lesson_dir(i) for i in dict.fromkeys(ids)]
    except LessonNotFound as exc:
        raise ApiError(404, "lesson_not_found", str(exc))
    try:
        path, _count = export_many_to_tempfile(dirs, format, study=study)
    except ExportError as exc:
        raise ApiError(404, "export_not_available", str(exc))
    filename = many_export_filename(name, format)
    return FileResponse(path, media_type="application/zip", filename=filename,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
                        background=BackgroundTask(os.unlink, path))


@router.post("/lesson-exports", response_model=schemas.JobAccepted, status_code=202,
             summary="Esporta più lezioni come job con avanzamento per lezione")
def start_lesson_export(body: schemas.LessonExportRequest, actor: Actor):
    from rt.api.jobs import enqueue_job
    from rt.services.api_jobs import EXPORT_LESSONS
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    ids = list(dict.fromkeys(body.ids))
    try:
        for lesson_id in ids:
            resolve_lesson_dir(lesson_id)
    except LessonNotFound as exc:
        raise ApiError(404, "lesson_not_found", str(exc))
    return enqueue_job(EXPORT_LESSONS, None, {**body.model_dump(), "ids": ids}, actor)


@router.get("/lesson-exports/{job_id}/file", response_class=Response,
            summary="Scarica lo ZIP prodotto da un export di lezioni concluso",
            responses={200: {"content": {"application/zip": {}}}})
def download_lesson_export(job_id: str, _actor: Actor):
    from rt.api.jobs import queue
    from rt.services.api_jobs import EXPORT_LESSONS, job_export_path
    info = queue().get(job_id)
    if info is None or info.type != EXPORT_LESSONS or info.state != "succeeded":
        raise ApiError(404, "export_not_available", "Esportazione non disponibile.")
    filename = str((info.result or {}).get("file") or "")
    path = job_export_path(info.id, filename) if filename else ""
    if not path or not os.path.isfile(path):
        raise ApiError(404, "export_not_available", "L'archivio non è più disponibile: esporta di nuovo le lezioni.")
    return FileResponse(path, media_type="application/zip", filename=os.path.basename(path))


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
    from rt.pipeline.ledger import load_ledger, resolve_science_accept_text
    from rt.pipeline.review import load_science_issues
    from rt.services.review_service import issue_context, is_review_complete
    issues = load_science_issues(lesson_dir)
    decisions = {}
    for d in load_ledger(lesson_dir).decisions:
        decisions[d.issue_id] = d
    from rt.core.segments import load_segments_json
    from rt.core.lesson_paths import lesson_path
    from rt.pipeline.ledger import load_resolved_draft
    from rt.pipeline.rewrite import get_draft_path
    segments = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    draft = load_resolved_draft(lesson_dir) if fs.isfile(get_draft_path(lesson_dir)) else None
    items = []
    for issue in issues:
        decision = decisions.get(issue.id)
        if status == "pending" and decision is not None:
            continue
        items.append({
            "issue": issue.model_dump(mode="json"),
            "fix_text": resolve_science_accept_text(issue),
            "context": issue_context(lesson_dir, issue, segments=segments, draft=draft, loaded=True),
            "decision": decision.model_dump(mode="json") if decision else None,
        })
    pending = sum(1 for i in issues if i.id not in decisions)
    return {"pending": pending, "total": len(issues), "review_complete": pending == 0, "items": items}


@router.get("/lessons/{lesson_id}/decisions", response_model=List[schemas.Decision],
            summary="Ledger delle decisioni (review_decisions.json)")
def get_decisions(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.ledger import load_ledger
    return [d.model_dump(mode="json") for d in load_ledger(lesson_dir).decisions]


@router.get("/costs", response_model=schemas.CostSummary, summary="Riepilogo dei costi LLM di tutte le lezioni")
def get_costs(_actor: Actor):
    return lesson_service.costs_summary()
