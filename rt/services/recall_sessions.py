"""
rt.services.recall_sessions
Registro delle sessioni di Active Recall (tabella recall_sessions) e richieste dell'app al bot
Telegram (tabella telegram_commands).

- Sessione web: si apre con la prima domanda chiesta dalla web app e si chiude con "Termina
  sessione", che salva il riepilogo (domande poste, risposte date, quiz giusti).
- Sessione Telegram: il daemon la registra quando parte e la chiude quando finisce (/quit,
  riserva esaurita, interruzione dall'app). L'API la legge da qui.
- Comandi: l'API chiede al daemon di avviare o interrompere una sessione Telegram con una riga
  in telegram_commands; il daemon la esegue e ne scrive l'esito.

Senza database (CLI con il DB disattivato) le funzioni chiamate dal daemon non fanno nulla.
Questo modulo non importa rt.telegram: il daemon chiama il servizio, mai il contrario.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select, update

from rt.db.engine import get_database, require_database
from rt.db.models import Lesson, RecallSession, TelegramCommand, utcnow
from rt.db.repositories import normalize_lesson_path
from rt.db.session import read_scope, session_scope

WEB = "web"
TELEGRAM = "telegram"
ACTIVE = "active"
ENDED = "ended"
INTERRUPTED = "interrupted"

START_RECALL = "start_recall"
STOP_RECALL = "stop_recall"
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

INTERRUPTED_MESSAGE = "⏹ Sessione interrotta dall'app."


class RecallSessionError(RuntimeError):
    """Operazione non valida sul registro (sessione già attiva, inesistente...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Command:
    id: int
    kind: str
    lesson_path: Optional[str]
    payload: Dict[str, Any]


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
    quiz = correct = 0
    for a in answers:
        q = by_id.get(a.question_id)
        if q is None or q.type != RecallQuestionType.QUIZ:
            continue
        quiz += 1
        if q.options and q.correct_index is not None and 0 <= q.correct_index < len(q.options) \
                and a.answer_text == q.options[q.correct_index]:
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


# ---------------------------------------------------------------- sessione Telegram (daemon)

def telegram_session_started(lesson_dir: str, chat_id: Any, thread_id: Any, qtype: Optional[str] = None) -> None:
    """Chiamata dal daemon quando una sessione di recall parte in un topic."""
    db = get_database()
    if db is None:
        return
    path = normalize_lesson_path(lesson_dir)
    with session_scope(db) as session:
        existing = session.scalars(select(RecallSession).where(
            RecallSession.lesson_path == path, RecallSession.channel == TELEGRAM,
            RecallSession.state == ACTIVE)).first()
        if existing is not None:
            existing.chat_id = str(chat_id)
            existing.thread_id = None if thread_id is None else str(thread_id)
            return
        session.add(RecallSession(lesson_path=path, channel=TELEGRAM, state=ACTIVE, qtype=qtype,
                                  chat_id=str(chat_id), thread_id=None if thread_id is None else str(thread_id),
                                  started_at=_now(), question_ids=[]))


def _close(row: RecallSession, state: str, ended_by: str) -> None:
    row.state = state
    row.ended_at = _now()
    row.ended_by = ended_by
    try:
        row.summary = summarize(row.lesson_path, since=row.started_at, until=row.ended_at)
    except Exception:
        row.summary = None


def telegram_session_ended(chat_id: Any, thread_id: Any, lesson_dir: Optional[str] = None,
                           ended_by: str = "telegram") -> None:
    """Chiamata dal daemon quando la sessione di recall di un topic si chiude."""
    db = get_database()
    if db is None:
        return
    thread = None if thread_id is None else str(thread_id)
    stmt = select(RecallSession).where(RecallSession.channel == TELEGRAM, RecallSession.state == ACTIVE,
                                       RecallSession.chat_id == str(chat_id))
    stmt = stmt.where(RecallSession.thread_id.is_(None) if thread is None else RecallSession.thread_id == thread)
    if lesson_dir:
        stmt = stmt.where(RecallSession.lesson_path == normalize_lesson_path(lesson_dir))
    with session_scope(db) as session:
        for row in session.scalars(stmt):
            _close(row, ENDED, ended_by)


def interrupt_telegram_session(session_id: int, actor: str) -> Dict[str, Any]:
    """Interrompe dall'app una sessione su Telegram: il registro la chiude subito e il daemon,
    con il comando stop_recall, libera il topic e lo scrive nel topic."""
    db = require_database()
    with session_scope(db) as session:
        row = session.get(RecallSession, session_id)
        if row is None or row.channel != TELEGRAM:
            raise RecallSessionError("session_not_found", "Sessione Telegram inesistente.")
        if row.state != ACTIVE:
            raise RecallSessionError("session_not_active", "La sessione su Telegram è già chiusa.")
        _close(row, INTERRUPTED, "app")
        session.add(TelegramCommand(kind=STOP_RECALL, lesson_path=row.lesson_path, state=PENDING, created_by=actor,
                                    payload={"session_id": row.id, "chat_id": row.chat_id, "thread_id": row.thread_id}))
        session.flush()
        return _views(session, [row])[0]


# ---------------------------------------------------------------- comandi per il daemon

def _command_view(row: TelegramCommand) -> Dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "state": row.state, "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "processed_at": row.processed_at.isoformat() if row.processed_at else None}


def request_telegram_start(lesson_dir: str, qtype: str, actor: str, mock: bool = False) -> Dict[str, Any]:
    """Chiede al daemon di avviare il recall della lezione nel topic della materia."""
    db = require_database()
    path = normalize_lesson_path(lesson_dir)
    with session_scope(db) as session:
        active = session.scalars(select(RecallSession).where(
            RecallSession.lesson_path == path, RecallSession.channel == TELEGRAM,
            RecallSession.state == ACTIVE)).first()
        if active is not None:
            raise RecallSessionError("telegram_session_active", "C'è già una sessione su Telegram per questa lezione.")
        pending = session.scalars(select(TelegramCommand).where(
            TelegramCommand.lesson_path == path, TelegramCommand.kind == START_RECALL,
            TelegramCommand.state.in_((PENDING, RUNNING)))).first()
        if pending is not None:
            return _command_view(pending)
        row = TelegramCommand(kind=START_RECALL, lesson_path=path, state=PENDING, created_by=actor,
                              payload={"qtype": qtype, "mock": bool(mock)})
        session.add(row)
        session.flush()
        return _command_view(row)


def latest_command(lesson_dir: str) -> Optional[Dict[str, Any]]:
    db = require_database()
    with read_scope(db) as session:
        row = session.scalars(select(TelegramCommand).where(
            TelegramCommand.lesson_path == normalize_lesson_path(lesson_dir))
            .order_by(TelegramCommand.id.desc()).limit(1)).first()
        return _command_view(row) if row is not None else None


def claim_next_command() -> Optional[Command]:
    """Il prossimo comando in attesa, marcato come in esecuzione (None se non ce ne sono)."""
    db = get_database()
    if db is None:
        return None
    with session_scope(db) as session:
        row = session.scalars(select(TelegramCommand).where(TelegramCommand.state == PENDING)
                              .order_by(TelegramCommand.id).limit(1)).first()
        if row is None:
            return None
        claimed = session.execute(update(TelegramCommand).where(
            TelegramCommand.id == row.id, TelegramCommand.state == PENDING).values(state=RUNNING)).rowcount
        if not claimed:
            return None
        return Command(id=row.id, kind=row.kind, lesson_path=row.lesson_path, payload=dict(row.payload or {}))


def finish_command(command_id: int, error: Optional[str] = None) -> None:
    db = get_database()
    if db is None:
        return
    with session_scope(db) as session:
        row = session.get(TelegramCommand, command_id)
        if row is not None:
            row.state = FAILED if error else DONE
            row.error = error
            row.processed_at = utcnow()


def requeue_running_commands() -> None:
    """All'avvio del daemon: i comandi rimasti 'running' (daemon fermato a metà) si ripetono."""
    db = get_database()
    if db is None:
        return
    with session_scope(db) as session:
        session.execute(update(TelegramCommand).where(TelegramCommand.state == RUNNING).values(state=PENDING))
