"""Active recall di una lezione (come 'rt recall'): domande, risposte ai quiz, risposte
aperte valutate da un job, voti. La generazione di nuove domande è un job."""
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job

router = APIRouter(tags=["recall"])
VOICE_SUFFIXES = {".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".webm", ".aac", ".flac"}


def _refill_later(lesson_dir: str, question, mock: bool, actor: str) -> None:
    """Come il recall da terminale dopo ogni domanda mostrata: se la riserva del tipo è sotto
    soglia, un job ne genera altre (la risposta non aspetta l'LLM)."""
    from rt.services.recall_service import needs_refill
    if question is not None and needs_refill(lesson_dir, question.type):
        enqueue_job("recall_refill", lesson_dir, {"qtype": question.type.value, "mock": mock}, actor)


def _require_draft(lesson_dir: str) -> None:
    from rt.core.idempotency import PhaseStatus, check_phase_status
    status, reason = check_phase_status(lesson_dir, "rewrite")
    if status != PhaseStatus.VALID:
        raise ApiError(409, "draft_not_ready", f"La lezione non ha un draft valido ({reason}): esegui prima il rewrite.")


@router.get("/lessons/{lesson_id}/recall", response_model=schemas.RecallOverview, summary="Domande disponibili per tipo e stato")
def overview(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_service import recall_overview
    return recall_overview(lesson_dir)


@router.get("/lessons/{lesson_id}/recall/history", response_model=schemas.RecallHistory,
            summary="Domande (con soluzione se già poste) e risposte date, con valutazioni e voti")
def history(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_service import recall_history
    return recall_history(lesson_dir)


@router.post("/lessons/{lesson_id}/recall/generate", response_model=schemas.JobAccepted, status_code=202,
             summary="Genera domande: riserva iniziale (job recall_generate) o un tipo (job recall_batch)")
def generate(lesson_id: int, body: schemas.RecallGenerate, lesson_dir: LessonDir, actor: Actor):
    _require_draft(lesson_dir)
    if body.qtype:
        return enqueue_job("recall_batch", lesson_dir, body.model_dump(), actor)
    return enqueue_job("recall_generate", lesson_dir, {"force_mock": body.mock}, actor)


@router.post("/lessons/{lesson_id}/recall/next", response_model=schemas.RecallQuestion,
             summary="Prossima domanda del tipo scelto; sotto soglia accoda un job recall_refill (404 se la riserva è vuota: usa /recall/generate)")
def next_question(lesson_id: int, lesson_dir: LessonDir, actor: Actor,
                  qtype: Literal["quiz", "mirata", "vasta"] = Query("quiz"),
                  order: Literal["alternato", "sequenziale", "casuale"] = Query("alternato"),
                  exclude_id: Optional[str] = Query(None, description="Domanda appena saltata"),
                  mock: bool = Query(False, description="Rifornimento della riserva in mock")):
    from rt.core.models import RecallQuestionType
    from rt.services.recall_service import next_question_for, question_view
    _require_draft(lesson_dir)
    question = next_question_for(lesson_dir, RecallQuestionType(qtype), order=order, exclude_id=exclude_id)
    if question is None:
        raise ApiError(404, "no_questions", "Nessuna domanda pendente di questo tipo: generane altre.")
    _refill_later(lesson_dir, question, mock, actor)
    return question_view(question)


@router.post("/lessons/{lesson_id}/recall/answer", summary="Risponde: quiz subito, risposta scritta con un job di valutazione",
             response_model=schemas.QuizResult,
             responses={202: {"model": schemas.JobAccepted, "description": "Risposta aperta: valutazione in un job"}})
def answer(lesson_id: int, body: schemas.RecallAnswer, lesson_dir: LessonDir, actor: Actor):
    from fastapi.responses import JSONResponse
    from rt.core.models import RecallQuestionType
    from rt.services.recall_service import answer_quiz, find_question
    question = find_question(lesson_dir, body.question_id)
    if question is None:
        raise ApiError(404, "question_not_found", "Domanda inesistente.")
    if question.type == RecallQuestionType.QUIZ:
        if body.choice is None:
            raise ApiError(422, "validation_error", "Per un quiz indica l'opzione scelta (choice).")
        try:
            return answer_quiz(lesson_dir, body.question_id, body.choice)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc))
    if not (body.answer or "").strip():
        raise ApiError(422, "validation_error", "Scrivi una risposta.")
    accepted = enqueue_job("recall_evaluate", lesson_dir,
                           {"question_id": body.question_id, "answer": body.answer.strip(), "mock": body.mock}, actor)
    return JSONResponse(status_code=202, content=accepted)


@router.post("/lessons/{lesson_id}/recall/answer-voice", response_model=schemas.JobAccepted, status_code=202,
             summary="Risposta vocale a una domanda aperta: trascrizione e valutazione in un job")
def answer_voice(lesson_id: int, lesson_dir: LessonDir, actor: Actor,
                 question_id: str = Form(...), audio: UploadFile = File(...), mock: bool = Form(False)):
    from rt.api.routers.jobs import _save_uploads, _upload_dir, _with_upload_cleanup
    from rt.services.recall_service import find_question
    question = find_question(lesson_dir, question_id)
    if question is None or question.type.value == "quiz":
        raise ApiError(404, "question_not_found", "Domanda aperta inesistente.")
    target = _upload_dir()

    def _go():
        path = _save_uploads([audio], VOICE_SUFFIXES, target)[0]
        return enqueue_job("recall_evaluate", lesson_dir, {"question_id": question_id, "audio_path": path,
                                                           "mock": mock, "upload_dir": target}, actor)
    return _with_upload_cleanup(target, _go)


@router.post("/lessons/{lesson_id}/recall/vote", response_model=schemas.Message, summary="Voto su una domanda (👍 👎 ⚡)")
def vote(lesson_id: int, body: schemas.RecallVote, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_service import vote_question
    try:
        vote_question(lesson_dir, body.question_id, body.vote)
    except ValueError as exc:
        raise ApiError(404, "question_not_found", str(exc))
    return {"message": "Voto registrato."}


@router.post("/lessons/{lesson_id}/recall/skip", response_model=schemas.Message, summary="Salta una domanda (torna in coda)")
def skip(lesson_id: int, body: schemas.RecallSkip, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_service import skip_question
    skip_question(lesson_dir, body.question_id)
    return {"message": "Domanda rimessa in coda."}
