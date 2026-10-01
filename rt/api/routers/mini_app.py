"""Narrow study API. The Telegram credential never grants access to RT administration."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from rt.api import schemas
from rt.api.schemas import NextQuestionType, QuestionType
from rt.api.deps import LessonDir
from rt.api.errors import ApiError
from rt.api.mini_auth import StudyActor, issue_session, study_actor, verify_init_data
from rt.api.auth import bearer_scheme
from rt.api.routers import recall

router = APIRouter(prefix="/mini-app", tags=["Telegram Mini App"])


def _unit_html(content):
    from html import escape
    from rt.core.markdown_render import markdown_parser
    from rt.api.routers.images import _IMAGE_NAME
    md = markdown_parser()
    def image_rule(tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet("src") or ""
        name = src.removeprefix("assets/images/")
        alt = escape(token.content, quote=True)
        if src.startswith("assets/images/") and _IMAGE_NAME.fullmatch(name):
            return f'<img data-rt-image="{escape(name, quote=True)}" alt="{alt}" loading="lazy">'
        return alt
    md.renderer.rules["image"] = image_rule
    return md.render(content)


class Init(BaseModel):
    init_data: str = Field(default="", max_length=16384)


@router.post("/auth")
def authenticate(body: Init, request: Request, credentials=Depends(bearer_scheme)):
    if body.init_data:
        return issue_session(verify_init_data(body.init_data))
    # This endpoint also permits preview through a previously authenticated RT browser.
    study_actor(request, credentials)
    return {"token": None, "expires_at": None}


@router.get("/lessons")
def lessons(_actor: StudyActor):
    from rt.services.lesson_service import list_lessons
    from rt.services.recall_service import recall_overview
    out = []
    for row in list_lessons():
        ready = row["phases"].get("rewrite") == "VALID"
        out.append({k: row.get(k) for k in ("id", "data", "materia", "titolo", "argomenti")}
                   | {"ready": ready, "questions": recall_overview(row["path"])["questions"] if ready else {}})
    return out


@router.get("/lessons/{lesson_id}")
def lesson(lesson_id: int, lesson_dir: LessonDir, _actor: StudyActor):
    from rt.core.audio_clip import resolve_audio_path
    from rt.pipeline.ledger import load_resolved_draft
    from rt.services.lesson_service import document_sections, lesson_detail
    from rt.services.recall_service import recall_overview
    from rt.pipeline.document_edits import load_document_edits, unit_title
    detail = lesson_detail(lesson_id, lesson_dir)
    ready = detail["phases"].get("rewrite") == "VALID"
    units = []
    if ready:
        from rt.pipeline.recall import load_recall_bank, on_unit
        pending = [q for q in load_recall_bank(lesson_dir).questions if q.status.value == "pending"]
        draft = load_resolved_draft(lesson_dir)
        sections = {s["unit_id"]: s for s in document_sections(lesson_dir)}
        edits = load_document_edits(lesson_dir)
        for u in draft.units:
            s = sections.get(u.unit_id, {})
            content = u.content
            units.append({"id": u.unit_id, "title": unit_title(edits, u.unit_id, u.title),
                          "content": content, "html": _unit_html(content),
                          "start": s.get("start_seconds"), "end": s.get("end_seconds"),
                          # Domande di Leggi e ripeti per l'unità (vedi rt.pipeline.recall.on_unit).
                          "pending": _unit_pending(pending, u.unit_id, on_unit)})
    return {"id": lesson_id, "ready": ready, "has_audio": bool(resolve_audio_path(lesson_dir)),
            "units": units, "questions": recall_overview(lesson_dir)["questions"] if ready else {}}


def _unit_pending(pending, unit_id, on_unit):
    counts = {}
    for q in pending:
        if on_unit(q, unit_id):
            counts[q.type.value] = counts.get(q.type.value, 0) + 1
    return counts


def _matches(question, qtype, unit_id=None):
    """La domanda già posta vale ancora per la richiesta (stesso tipo, o mista, e stessa unità)."""
    from rt.pipeline.recall import on_unit
    return ((qtype == "mista" or question.type.value == qtype)
            and (unit_id is None or on_unit(question, unit_id)))


def _unit(lesson_dir, unit_id):
    recall._require_draft(lesson_dir)
    from rt.pipeline.ledger import load_resolved_draft
    unit = next((u for u in load_resolved_draft(lesson_dir).units if u.unit_id == unit_id), None)
    if unit is None:
        raise ApiError(404, "unit_not_found", "Unità non trovata.")
    return unit


@router.get("/lessons/{lesson_id}/units/{unit_id}/audio")
def audio(lesson_id: int, unit_id: str, lesson_dir: LessonDir, _actor: StudyActor):
    from rt.core.audio_clip import get_or_create_unit_clip
    from rt.core.lesson_paths import lesson_path
    from rt.core.segments import load_segments_json
    unit = _unit(lesson_dir, unit_id)
    segments = load_segments_json(lesson_path(lesson_dir, "segments.json")).segments
    clip = get_or_create_unit_clip(lesson_dir, unit, segments)
    if not clip:
        raise ApiError(404, "audio_not_found", "Audio non disponibile per questa unità.")
    return FileResponse(clip, headers={"Cache-Control": "private, no-store"})


@router.post("/lessons/{lesson_id}/units/{unit_id}/send-audio")
def send_audio(lesson_id: int, unit_id: str, lesson_dir: LessonDir, _actor: StudyActor):
    from types import SimpleNamespace
    from rt.core.config import load_config
    from rt.telegram.config import resolve_topic_id
    from rt.telegram.recall_channel import send_unit_audio
    _unit(lesson_dir, unit_id)
    cfg = load_config().telegram
    thread_id = resolve_topic_id(lesson_dir, cfg.topics, cfg.misc_topic_id)
    try:
        send_unit_audio(lesson_dir, SimpleNamespace(unit_ids=[unit_id]), message_thread_id=thread_id)
    except ValueError as exc:
        raise ApiError(409, "audio_unavailable", str(exc))
    return {"message": "Audio inviato nel topic della materia."}


@router.post("/lessons/{lesson_id}/next")
def next_question(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor,
                  qtype: NextQuestionType = "quiz", exclude_id: Optional[str] = None,
                  unit_id: Optional[str] = None):
    from rt.services.recall_sessions import TELEGRAM, WEB, list_sessions
    from rt.services.recall_service import find_question, load_recall_session_state, question_view
    recall._require_draft(lesson_dir)
    current_id = load_recall_session_state(lesson_dir).get("current_question_id")
    current = find_question(lesson_dir, current_id) if current_id else None
    if (list_sessions(channel=WEB, lesson_dir=lesson_dir) and not list_sessions(channel=TELEGRAM, lesson_dir=lesson_dir)
            and current and current.status.value == "asked" and _matches(current, qtype, unit_id)):
        return question_view(current)
    return recall.next_question(lesson_id, lesson_dir, actor, qtype=qtype, order="alternato", exclude_id=exclude_id,
                                mock=False, unit_id=unit_id)


def _answerable(lesson_dir, question_id):
    from rt.services.recall_service import find_question
    q = find_question(lesson_dir, question_id)
    if q is None:
        raise ApiError(404, "question_not_found", "Domanda non trovata.")
    if q.status.value != "asked":
        raise ApiError(409, "question_not_active", "Questa domanda non è in attesa di risposta.")
    from rt.api.jobs import queue
    from rt.services.jobs import ACTIVE_STATES
    if any(j.type == "recall_evaluate" and j.payload.get("question_id") == question_id
           for j in queue().list(state=list(ACTIVE_STATES), lesson_id=lesson_dir)):
        raise ApiError(409, "answer_pending", "La risposta è già in valutazione.")
    return q


class Answer(BaseModel):
    question_id: str = Field(max_length=200)
    choice: Optional[int] = Field(default=None, ge=0)
    answer: Optional[str] = Field(default=None, max_length=30000)
    dont_know: bool = False


@router.post("/lessons/{lesson_id}/answer")
def answer(lesson_id: int, body: Answer, lesson_dir: LessonDir, actor: StudyActor):
    q = _answerable(lesson_dir, body.question_id)
    if body.dont_know and q.type.value == "quiz":
        from rt.pipeline.recall import record_recall_answer
        from rt.services.recall_service import question_view
        record_recall_answer(lesson_dir, q.id, "[Non risposto]", False, q.pregenerated_material, None)
        return {"question": question_view(q, reveal=True), "correct": False, "dont_know": True}
    return recall.answer(lesson_id, schemas.RecallAnswer(question_id=body.question_id, choice=body.choice,
                         answer="[Non lo so]" if body.dont_know else body.answer, mock=False), lesson_dir, actor)


@router.post("/lessons/{lesson_id}/answer-voice", status_code=202)
def voice(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor,
          question_id: str = Form(...), audio: UploadFile = File(...)):
    _answerable(lesson_dir, question_id)
    return recall.answer_voice(lesson_id, lesson_dir, actor, question_id, audio, False)


@router.post("/lessons/{lesson_id}/generate", status_code=202)
def generate(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor,
             qtype: QuestionType = "quiz"):
    from rt.api.jobs import queue, job_accepted
    from rt.services.jobs import ACTIVE_STATES
    pending = next((j for j in queue().list(state=list(ACTIVE_STATES), lesson_id=lesson_dir)
                    if j.type == "recall_batch" and j.payload.get("qtype") == qtype and j.created_by == actor), None)
    if pending:
        return job_accepted(pending.id)
    return recall.generate(lesson_id, schemas.RecallGenerate(qtype=qtype, mock=False), lesson_dir, actor)


@router.post("/lessons/{lesson_id}/skip")
def skip(lesson_id: int, body: schemas.RecallSkip, lesson_dir: LessonDir, actor: StudyActor):
    _answerable(lesson_dir, body.question_id)
    return recall.skip(lesson_id, body, lesson_dir, actor)


@router.post("/lessons/{lesson_id}/vote")
def vote(lesson_id: int, body: schemas.RecallVote, lesson_dir: LessonDir, actor: StudyActor):
    return recall.vote(lesson_id, body, lesson_dir, actor)


@router.get("/lessons/{lesson_id}/session")
def session(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor):
    return recall.session_state(lesson_id, lesson_dir, actor)


@router.get("/lessons/{lesson_id}/resume")
def resume(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor, question_id: str,
           materia: Optional[str] = None):
    from rt.services.recall_service import find_question, question_view, recall_history, load_recall_session_state
    from rt.services.recall_sessions import WEB, list_sessions
    if materia:
        from rt.services.recall_subject import current_subject_question
        current = recall._subject_call(current_subject_question, materia)
        active = current and current["lesson_id"] == lesson_id and current["question"].id == question_id
    else:
        active = (list_sessions(channel=WEB, lesson_dir=lesson_dir)
                  and load_recall_session_state(lesson_dir).get("current_question_id") == question_id)
    q = find_question(lesson_dir, question_id)
    if not active or q is None or q.status.value == "pending":
        raise ApiError(404, "no_active_session", "Nessuna sessione da riprendere.")
    answers = recall_history(lesson_dir)["answers"]
    last = next((a for a in reversed(answers) if a["question_id"] == question_id), None) if q.status.value == "answered" else None
    from rt.api.jobs import queue, job_accepted
    from rt.services.jobs import ACTIVE_STATES
    pending = next((j for j in queue().list(state=list(ACTIVE_STATES), lesson_id=lesson_dir)
                    if j.type == "recall_evaluate" and j.payload.get("question_id") == question_id and j.created_by == actor), None)
    return {"question": question_view(q, reveal=q.status.value == "answered"), "answer": last,
            "pending_job": job_accepted(pending.id) if pending else None}


@router.post("/lessons/{lesson_id}/end")
def end(lesson_id: int, lesson_dir: LessonDir, actor: StudyActor):
    return recall.end_session(lesson_id, lesson_dir, actor)


@router.post("/subject/next")
def subject_next(actor: StudyActor, materia: str, qtype: NextQuestionType = "quiz",
                 exclude: Optional[str] = None):
    from rt.services.recall_subject import current_subject_question
    from rt.services.recall_service import question_view
    current = recall._subject_call(current_subject_question, materia)
    if current and current["question"].status.value == "asked" and _matches(current["question"], qtype):
        return {"lesson_id": current["lesson_id"], "question": question_view(current["question"])}
    return recall.subject_next(actor, materia, qtype=qtype, order="alternato", exclude=exclude, mock=False)


@router.post("/subject/end")
def subject_end(actor: StudyActor, materia: str):
    return recall.subject_end(actor, materia)


@router.post("/subject/generate", status_code=202)
def subject_generate(actor: StudyActor, materia: str):
    return recall.subject_generate(actor, materia, mock=False)


@router.get("/jobs/{job_id}")
def job(job_id: str, actor: StudyActor):
    from rt.api.jobs import queue, worker_available
    info = queue().get(job_id)
    if info is None or info.created_by != actor or info.type not in {"recall_generate", "recall_batch", "recall_evaluate", "recall_refill"}:
        raise ApiError(404, "job_not_found", "Operazione non trovata.")
    result = info.result or {}
    return {"id": info.id, "state": info.state, "progress": info.progress,
            "worker_available": worker_available(info.type, info.payload, info.lesson_path),
            "error": "Operazione non riuscita. Controlla RT e riprova." if info.error else None,
            "result": {k: result[k] for k in ("question_id", "answer", "evaluation") if k in result}
                      | ({"is_voice": bool(info.payload.get("audio_path"))} if "answer" in result else {})}


@router.get("/lessons/{lesson_id}/images/{name}")
def image(lesson_id: int, name: str, lesson_dir: LessonDir, actor: StudyActor):
    from rt.api.routers.images import get_image
    response = get_image(lesson_id, name, lesson_dir, actor)
    response.headers["Cache-Control"] = "private, no-store"
    return response
