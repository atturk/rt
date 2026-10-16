"""
rt.services.recall_sessions
Registro delle sessioni di Active Recall (tabella recall_sessions).

Una sessione web si apre con la prima domanda chiesta dalla web app e si chiude con "Termina
sessione", che salva il riepilogo (domande poste, risposte date, quiz giusti). Le righe con
canale "telegram" vengono dalle versioni con il recall in chat: restano leggibili nello storico.
"""
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select

from rt.db.engine import get_database, require_database
from rt.db.models import Lesson, RecallSession
from rt.db.repositories import normalize_lesson_path
from rt.db.session import read_scope, session_scope

WEB = "web"
TELEGRAM = "telegram"
ACTIVE = "active"
ENDED = "ended"
INTERRUPTED = "interrupted"



class RecallSessionError(RuntimeError):
    """Operazione non valida sul registro (sessione già attiva, inesistente...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now().isoformat()


# ---------------------------------------------------------------- riepilogo

def summarize(lesson_dir: str, question_ids: Optional[Iterable[str]] = None,
              since: Optional[str] = None, until: Optional[str] = None) -> Dict[str, int]:
    """Riepilogo di una sessione dal recall_bank: domande poste, risposte date e quiz giusti.
    Per la web le domande sono quelle chieste nella sessione; per Telegram (dove le domande
    passano dal bot) quelle a cui si è risposto fra since e until."""
    from rt.core.models import RecallQuestionType
    from rt.pipeline.recall import load_recall_bank
    bank = load_recall_bank(lesson_dir)
    by_id = {q.id: q for q in bank.questions}
    if question_ids is not None:
        asked = list(dict.fromkeys(question_ids))
        answers = [a for a in bank.answers if a.question_id in set(asked)]
    else:
        answers = [a for a in bank.answers
                   if (since is None or a.answered_at >= since) and (until is None or a.answered_at <= until)]
        asked = [a.question_id for a in answers]
    answers = [a for a in answers if a.answer_text.strip()]
    quiz = correct = 0
    for a in answers:
        q = by_id.get(a.question_id)
        if q is None or q.type != RecallQuestionType.QUIZ:
            continue
        quiz += 1
        if a.outcome == 'corretta' or (a.outcome is None and not a.dont_know and q.options
                and q.correct_index is not None and 0 <= q.correct_index < len(q.options)
                and a.answer_text == q.options[q.correct_index]):
            correct += 1
    return {"questions": len(asked), "answered": len(answers), "quiz_answered": quiz, "correct": correct}


# ---------------------------------------------------------------- vista

def _lesson_refs(session, paths: Iterable[str]) -> Dict[str, Lesson]:
    paths = list(set(paths))
    if not paths:
        return {}
    return {l.path: l for l in session.scalars(select(Lesson).where(Lesson.path.in_(paths)))}


def _view(row: RecallSession, lesson: Optional[Lesson]) -> Dict[str, Any]:
    title = ""
    if lesson is not None:
        title = " · ".join(p for p in (lesson.materia, lesson.titolo or lesson.argomenti, lesson.data) if p)
    return {
        "id": row.id, "lesson_id": lesson.id if lesson is not None else None, "lesson_title": title,
        "subject": row.subject,
        "channel": row.channel, "state": row.state, "qtype": row.qtype,
        "started_at": row.started_at, "ended_at": row.ended_at, "ended_by": row.ended_by,
        "questions": len(row.question_ids or []), "summary": row.summary,
    }


def _views(session, rows: List[RecallSession]) -> List[Dict[str, Any]]:
    lessons = _lesson_refs(session, (r.lesson_path for r in rows))
    return [_view(r, lessons.get(r.lesson_path)) for r in rows]


def list_sessions(channel: Optional[str] = None, lesson_dir: Optional[str] = None,
                  state: Optional[str] = ACTIVE) -> List[Dict[str, Any]]:
    db = get_database()
    if db is None:
        return []
    stmt = select(RecallSession).order_by(RecallSession.id.desc())
    if channel:
        stmt = stmt.where(RecallSession.channel == channel)
    if state:
        stmt = stmt.where(RecallSession.state == state)
    if lesson_dir:
        stmt = stmt.where(RecallSession.lesson_path == normalize_lesson_path(lesson_dir))
    with read_scope(db) as session:
        return _views(session, list(session.scalars(stmt)))


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    db = require_database()
    with read_scope(db) as session:
        row = session.get(RecallSession, session_id)
        return _views(session, [row])[0] if row is not None else None


def last_ended_web_session(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """L'ultima sessione web chiusa, se è più recente dell'ultima aperta (il riepilogo resta
    visibile finché non ne parte un'altra)."""
    db = require_database()
    path = normalize_lesson_path(lesson_dir)
    with read_scope(db) as session:
        row = session.scalars(select(RecallSession).where(RecallSession.lesson_path == path,
                                                          RecallSession.channel == WEB)
                              .order_by(RecallSession.id.desc()).limit(1)).first()
        if row is None or row.state == ACTIVE:
            return None
        return _views(session, [row])[0]


# ---------------------------------------------------------------- sessione web

def record_web_question(lesson_dir: str, question_id: str, qtype: str) -> Dict[str, Any]:
    """Domanda posta dalla web app: apre la sessione web della lezione se non c'è e la annota."""
    db = require_database()
    path = normalize_lesson_path(lesson_dir)
    with session_scope(db) as session:
        row = session.scalars(select(RecallSession).where(
            RecallSession.lesson_path == path, RecallSession.channel == WEB,
            RecallSession.state == ACTIVE)).first()
        if row is None:
            row = RecallSession(lesson_path=path, channel=WEB, state=ACTIVE, started_at=_now(), question_ids=[])
            session.add(row)
        ids = list(row.question_ids or [])
        if question_id not in ids:
            ids.append(question_id)
        row.question_ids = ids
        row.qtype = qtype
        session.flush()
        return _views(session, [row])[0]


def end_web_session(lesson_dir: str, ended_by: str = "web") -> Dict[str, Any]:
    """Chiude la sessione web attiva e ne salva il riepilogo. RecallSessionError se non c'è."""
    from rt.services.recall_service import load_recall_session_state, save_recall_session_state
    db = require_database()
    path = normalize_lesson_path(lesson_dir)
    with session_scope(db) as session:
        row = session.scalars(select(RecallSession).where(
            RecallSession.lesson_path == path, RecallSession.channel == WEB,
            RecallSession.state == ACTIVE)).first()
        if row is None:
            raise RecallSessionError("no_active_session", "Nessuna sessione in corso su questa lezione.")
        row.state = ENDED
        row.ended_at = _now()
        row.ended_by = ended_by
        row.summary = summarize(lesson_dir, question_ids=row.question_ids or [])
        session.flush()
        view = _views(session, [row])[0]
    state = load_recall_session_state(lesson_dir)
    if state.get("current_question_id"):
        state["current_question_id"] = None
        save_recall_session_state(lesson_dir, state)
    return view
