"""Router API per Verifica e Chiedi nello Studio (VC1)."""
from typing import List, Optional

from fastapi import APIRouter, Query, Response

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError

router = APIRouter(tags=["studio"])


@router.post(
    "/lessons/{lesson_id}/study-notes",
    response_model=schemas.JobAccepted,
    status_code=202,
    summary="Accoda un'analisi di Verifica o Chiedi nello Studio",
)
def create_study_note(
    lesson_id: int,
    body: schemas.StudyNoteCreate,
    lesson_dir: LessonDir,
    actor: Actor,
):
    from rt.api.jobs import enqueue_job
    from rt.pipeline.anchors import locate
    from rt.pipeline.ledger import load_resolved_draft

    draft = load_resolved_draft(lesson_dir)
    unit = next((u for u in draft.units if u.unit_id == body.unit_id), None)
    if unit is None:
        raise ApiError(404, "unit_not_found", f"Unità {body.unit_id} non trovata nella bozza.")

    loc = locate(body.anchor, unit.content)
    if not loc or " ".join(unit.content[loc.start:loc.end].split()) != " ".join(body.anchor.quote.split()):
        raise ApiError(422, "selection_changed", "Il testo selezionato è cambiato o non si ritrova.")

    return enqueue_job(
        "study_note",
        lesson_dir,
        {
            "lesson_id": lesson_id,
            "unit_id": body.unit_id,
            "kind": body.kind,
            "anchor": body.anchor.model_dump(),
            "request": body.request,
            "options": {"mock": body.mock},
        },
        actor=actor,
    )


@router.get(
    "/lessons/{lesson_id}/study-notes",
    response_model=List[schemas.StudyNoteView],
    summary="Elenco delle note dello Studio per la lezione",
)
def list_notes(
    lesson_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
    unit_id: Optional[str] = Query(None),
):
    from rt.services.study_notes_service import decorate_study_note, list_study_notes

    raw_notes = list_study_notes(lesson_id, unit_id=unit_id)
    return [decorate_study_note(n, lesson_dir, lesson_id) for n in raw_notes]


@router.get(
    "/lessons/{lesson_id}/study-notes/{note_id}",
    response_model=schemas.StudyNoteView,
    summary="Dettaglio di una nota dello Studio",
)
def get_note(
    lesson_id: int,
    note_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
):
    from rt.services.study_notes_service import decorate_study_note, get_study_note

    note = get_study_note(lesson_id, note_id)
    return decorate_study_note(note, lesson_dir, lesson_id)


@router.delete(
    "/lessons/{lesson_id}/study-notes/{note_id}",
    status_code=204,
    summary="Elimina una nota dello Studio (non tocca la correzione se applicata)",
)
def delete_note(
    lesson_id: int,
    note_id: int,
    _dir: LessonDir,
    _actor: Actor,
):
    from rt.services.study_notes_service import delete_study_note

    delete_study_note(lesson_id, note_id)
    return Response(status_code=204)


@router.post(
    "/lessons/{lesson_id}/study-notes/{note_id}/apply",
    response_model=schemas.StudyNoteApplyResponse,
    summary="Applica la correzione proposta registrando una decisione accettata",
)
def apply_note(
    lesson_id: int,
    note_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
):
    from rt.services.study_notes_service import apply_study_note

    return apply_study_note(lesson_dir, lesson_id, note_id)


@router.post(
    "/lessons/{lesson_id}/study-notes/{note_id}/undo",
    response_model=schemas.StudyNoteView,
    summary="Annulla la correzione applicata per questa nota",
)
def undo_note(
    lesson_id: int,
    note_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
):
    from rt.services.study_notes_service import undo_study_note

    return undo_study_note(lesson_dir, lesson_id, note_id)
