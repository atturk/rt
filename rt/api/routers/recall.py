"""Active recall di una lezione (come 'rt recall'): domande, risposte ai quiz, risposte
aperte valutate da un job, voti. La generazione di nuove domande è un job."""
from typing import List, Literal, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError, require_telegram
from rt.api.jobs import enqueue_job

router = APIRouter(tags=["recall"])
VOICE_SUFFIXES = {".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".webm", ".aac", ".flac"}


def _refill_later(lesson_dir: str, question, mock: bool, actor: str) -> None:
    """Come il recall da terminale dopo ogni domanda mostrata: se il pool del tipo è alla
    soglia, un job ne genera altre (la risposta non aspetta l'LLM)."""
    from rt.services.recall_service import needs_refill
    if question is not None and needs_refill(lesson_dir, question.type, force_mock=mock):
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
             summary="Genera domande: aggiunge al pool domande da tutte le unità selezionate (job recall_generate) o di un tipo (job recall_batch)")
def generate(lesson_id: int, body: schemas.RecallGenerate, lesson_dir: LessonDir, actor: Actor):
    _require_draft(lesson_dir)
    if body.unit_ids is not None:
        from rt.pipeline.ledger import load_resolved_draft
        present = {u.unit_id for u in load_resolved_draft(lesson_dir).units}
        units = [u for u in dict.fromkeys(body.unit_ids) if u in present]
        if not units:
            raise ApiError(422, "validation_error", "Nessuna delle unità indicate è nella lezione.")
        return enqueue_job("recall_generate", lesson_dir, {
            "force_mock": body.mock,
            "regenerate": True,
            "unit_ids": units,
            "qtypes": [body.qtype] if body.qtype else ["quiz", "mirata"],
            "instructions": body.instructions,
            "selection": body.selection,
            "count": body.count,
        }, actor)
    if body.qtype:
        return enqueue_job("recall_batch", lesson_dir, body.model_dump(), actor)
    return enqueue_job("recall_generate", lesson_dir, {
        "force_mock": body.mock,
        "regenerate": True,
        "instructions": body.instructions,
        "selection": body.selection,
        "count": body.count,
    }, actor)


@router.get("/lessons/{lesson_id}/study", response_model=schemas.StudyLesson,
            summary="Studio: le unità della lezione con testo, tratto d'audio e domande da porre su ciascuna")
def study(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.study_service import study_lesson
    return study_lesson(lesson_id, lesson_dir)


@router.get("/lessons/{lesson_id}/recall/questions", response_model=schemas.RecallQuestionList,
            summary="Tutte le domande della lezione per rivederle (soluzioni delle domande da porre solo con reveal)")
def questions(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
              reveal: bool = Query(False, description="Mostra anche le soluzioni delle domande ancora da porre")):
    from rt.services.recall_service import question_list
    return question_list(lesson_dir, reveal=reveal)


@router.post("/lessons/{lesson_id}/recall/questions/delete", response_model=schemas.RecallDeleted,
             summary="Elimina domande (e le loro risposte) dal pool; gli ID sconosciuti si ignorano")
def delete_questions(lesson_id: int, body: schemas.RecallQuestionDelete, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_service import delete_questions as delete
    return {"deleted": delete(lesson_dir, body.question_ids)}


@router.get("/lessons/{lesson_id}/recall/units", response_model=schemas.RecallUnits,
            summary="Unità della lezione per il recaller: giudizio del classificatore e selezione")
def recall_units(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_units import selection_view
    return selection_view(lesson_dir)


@router.put("/lessons/{lesson_id}/recall/units", response_model=schemas.RecallUnits,
            summary="Sceglie le unità da cui generare le domande (unit_ids null: solo le rilevanti, la scelta predefinita)")
def select_recall_units(lesson_id: int, body: schemas.RecallUnitSelection, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_units import selection_view, set_selection
    _require_draft(lesson_dir)
    set_selection(lesson_dir, body.unit_ids)
    return selection_view(lesson_dir)


@router.post("/lessons/{lesson_id}/recall/next", response_model=schemas.RecallQuestion,
             summary="Prossima domanda del tipo scelto; alla soglia accoda un job recall_refill (404 se il pool è vuoto: usa /recall/generate)")
def next_question(lesson_id: int, lesson_dir: LessonDir, actor: Actor,
                  qtype: schemas.NextQuestionType = Query("quiz", description="Tipo, oppure mista (tutti a turno)"),
                  order: Literal["alternato", "sequenziale", "casuale"] = Query("alternato"),
                  exclude_id: Optional[str] = Query(None, description="Domanda appena saltata"),
                  mock: bool = Query(False, description="Rifornimento del pool in mock"),
                  unit_id: Optional[str] = Query(None, description="Solo le domande di questa unità (Leggi e ripeti)")):
    from rt.services.recall_service import next_question_for, question_view
    from rt.services.recall_sessions import TELEGRAM, list_sessions
    _require_draft(lesson_dir)
    if list_sessions(channel=TELEGRAM, lesson_dir=lesson_dir):
        raise ApiError(409, "telegram_session_active",
                       "C'è una sessione in corso su Telegram per questa lezione: interrompila per continuare qui.")
    question = next_question_for(lesson_dir, qtype, order=order, exclude_id=exclude_id, unit_id=unit_id)
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


# ---------------------------------------------------------------- sessioni (web e Telegram)

def _session_error(exc) -> ApiError:
    status = 404 if exc.code in ("no_active_session", "session_not_found") else 409
    return ApiError(status, exc.code, str(exc))


@router.get("/lessons/{lesson_id}/recall/session", response_model=schemas.RecallSessionState,
            summary="Sessione in corso qui e su Telegram, ultimo riepilogo e ultima richiesta al bot")
def session_state(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_sessions import TELEGRAM, WEB, last_ended_web_session, latest_command, list_sessions
    web = list_sessions(channel=WEB, lesson_dir=lesson_dir)
    telegram = list_sessions(channel=TELEGRAM, lesson_dir=lesson_dir)
    return {"web": web[0] if web else None, "last": last_ended_web_session(lesson_dir),
            "telegram": telegram[0] if telegram else None, "command": latest_command(lesson_dir)}


@router.post("/lessons/{lesson_id}/recall/session/end", response_model=schemas.RecallSessionInfo,
             summary="Termina la sessione in corso nella web app e ne salva il riepilogo (404 se non ce n'è una)")
def end_session(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.recall_sessions import RecallSessionError, end_web_session
    try:
        return end_web_session(lesson_dir)
    except RecallSessionError as exc:
        raise _session_error(exc)


def _bot_state() -> dict:
    import os
    from rt.services.settings_service import secret_is_set
    from rt.telegram.daemon_status import is_daemon_running
    from rt.core.config import telegram_enabled
    configured = secret_is_set("RT_TELEGRAM_BOT_TOKEN") and bool((os.environ.get("RT_TELEGRAM_CHAT_ID") or "").strip())
    return {"enabled": telegram_enabled(), "configured": configured, "running": is_daemon_running()}


@router.get("/recall/telegram", response_model=schemas.TelegramRecallStatus,
            summary="Bot pronto per il recall (configurato e in esecuzione) e sessioni in corso su Telegram")
def telegram_status(_actor: Actor):
    from rt.services.recall_sessions import TELEGRAM, list_sessions
    return {**_bot_state(), "sessions": list_sessions(channel=TELEGRAM)}


@router.post("/lessons/{lesson_id}/recall/telegram/start", response_model=schemas.TelegramCommandInfo, status_code=202,
             summary="Chiede al bot di avviare il recall nel topic della materia (l'esito arriva in /recall/session)")
def telegram_start(lesson_id: int, body: schemas.TelegramRecallStart, lesson_dir: LessonDir, actor: Actor):
    from rt.services.recall_sessions import RecallSessionError, WEB, list_sessions, request_telegram_start
    _require_draft(lesson_dir)
    require_telegram()
    bot = _bot_state()
    if not bot["configured"]:
        raise ApiError(409, "telegram_not_configured", "Configura il bot Telegram in Impostazioni.")
    if not bot["running"]:
        raise ApiError(409, "telegram_not_running", "Il bot Telegram è fermo: avvialo prima.")
    if list_sessions(channel=WEB, lesson_dir=lesson_dir):
        raise ApiError(409, "web_session_active", "C'è una sessione in corso qui: terminala prima di passare a Telegram.")
    try:
        return request_telegram_start(lesson_dir, body.qtype, actor, mock=body.mock)
    except RecallSessionError as exc:
        raise _session_error(exc)


@router.post("/recall/telegram/sessions/{session_id}/stop", response_model=schemas.RecallSessionInfo,
             summary="Interrompe una sessione su Telegram: il bot la chiude e scrive nel topic che è stata interrotta dall'app")
def telegram_stop(session_id: int, actor: Actor):
    from rt.services.recall_sessions import RecallSessionError, interrupt_telegram_session
    try:
        return interrupt_telegram_session(session_id, actor)
    except RecallSessionError as exc:
        raise _session_error(exc)


# ---------------------------------------------------------------- recall per materia

def _subject_call(fn, *args, **kwargs):
    from rt.services.recall_sessions import RecallSessionError
    from rt.services.recall_subject import NO_SUBJECT
    try:
        return fn(*args, **kwargs)
    except RecallSessionError as exc:
        if exc.code == NO_SUBJECT:
            raise ApiError(422, "validation_error", str(exc))
        raise _session_error(exc)


@router.get("/recall/subjects", response_model=List[schemas.SubjectRecall],
            summary="Pool di domande di ogni lezione, per materia, e sessioni per materia in corso")
def subjects(_actor: Actor):
    from rt.services.recall_subject import recall_by_subject
    return recall_by_subject()


@router.get("/recall/subject", response_model=schemas.SubjectRecallState,
            summary="Lezioni di una materia con il loro pool, sessione per materia in corso e ultimo riepilogo")
def subject_state(_actor: Actor, materia: str = Query(..., description="Materia, come nelle lezioni, oppure GIORNO:<AAAA-MM-GG> per le lezioni di un giorno, "
                                                                 "o LEZIONI:<id>,<id> per una selezione")):
    from rt.services.recall_subject import subject_overview
    return _subject_call(subject_overview, materia)


@router.post("/recall/subject/next", response_model=schemas.SubjectQuestion,
             summary="Prossima domanda del tipo scelto fra tutte le lezioni della materia, a turno; alla soglia accoda "
                     "un job recall_refill per la lezione (404 se nessuna lezione ha domande: usa /recall/subject/generate)")
def subject_next(actor: Actor, materia: str = Query(...),
                 qtype: schemas.NextQuestionType = Query("quiz", description="Tipo, oppure mista (tutti a turno)"),
                 order: Literal["alternato", "sequenziale", "casuale"] = Query("alternato"),
                 exclude: Optional[str] = Query(None, description="Domanda appena saltata, come <id lezione>:<id domanda>"),
                 mock: bool = Query(False, description="Rifornimento del pool in mock")):
    from rt.services.recall_service import question_view
    from rt.services.recall_subject import next_subject_question
    picked = _subject_call(next_subject_question, materia, qtype, order=order, exclude=exclude)
    if picked is None:
        raise ApiError(404, "no_questions", "Nessuna domanda di questo tipo da porre nelle lezioni della materia: generane altre.")
    _refill_later(picked["lesson_dir"], picked["question"], mock, actor)
    return {"lesson_id": picked["lesson_id"], "question": question_view(picked["question"])}


@router.post("/recall/subject/end", response_model=schemas.RecallSessionInfo,
             summary="Termina la sessione per materia e ne salva il riepilogo (404 se non ce n'è una)")
def subject_end(_actor: Actor, materia: str = Query(...)):
    from rt.services.recall_subject import end_subject_session
    return _subject_call(end_subject_session, materia)


@router.post("/recall/subject/generate", response_model=schemas.SubjectGenerateAccepted, status_code=202,
             summary="Pool per le lezioni pronte della materia che non hanno ancora domande (un job per lezione)")
def subject_generate(actor: Actor, materia: str = Query(...), mock: bool = Query(False)):
    from rt.services.recall_subject import lessons_without_reserve
    lessons = _subject_call(lessons_without_reserve, materia)
    return {"jobs": [enqueue_job("recall_generate", s["path"], {"force_mock": mock}, actor) for s in lessons]}
