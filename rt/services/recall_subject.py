"""
rt.services.recall_subject
Recall per materia: una sessione che pesca le domande da tutte le lezioni di una materia, con la
stessa logica della sessione di una lezione (tipo scelto, ordine fra le unità, salto, rifornimento
del pool). Le lezioni si danno il turno: dopo una domanda di una lezione tocca alla
successiva (per data) che ha ancora domande di quel tipo da porre; con l'ordine casuale la
lezione si sceglie a caso.

Qui ci sono solo la scelta della domanda e il registro della sessione (tabella recall_sessions,
colonna subject, lesson_path vuoto, question_ids "<id lezione>:<id domanda>"). Risposte, voti e
salti restano quelli della lezione a cui appartiene la domanda (rt.services.recall_service).
Il modulo non dipende dal canale: la web app lo usa, il bot Telegram può riusarlo passando
channel=TELEGRAM.
"""
import logging
import random
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from rt.core.models import RecallQuestionType
from rt.db.engine import require_database
from rt.db.models import RecallSession
from rt.db.session import read_scope, session_scope
from rt.services.recall_sessions import (
    ACTIVE, ENDED, TELEGRAM, WEB, RecallSessionError, _now, _views, list_sessions, summarize,
)

LOG = logging.getLogger(__name__)

NO_SUBJECT = "no_subject"
# Recall del giorno: stessa sessione della materia, con le lezioni di una data al posto di
# quelle di una materia ("GIORNO:2026-09-30" nella colonna subject).
DAY_PREFIX = "GIORNO:"
_DAY = re.compile(r"^GIORNO:(\d{4}-\d{2}-\d{2})$")


def subject_day(subject: str) -> Optional[str]:
    """La data di una sessione del giorno ("GIORNO:2026-09-30" -> "2026-09-30"), se lo è."""
    match = _DAY.match(subject or "")
    return match.group(1) if match else None


def normalize_subject(materia: Optional[str]) -> str:
    """Le materie delle lezioni sono in maiuscolo (come GET /lessons?materia=)."""
    subject = (materia or "").strip().upper()
    if not subject:
        raise RecallSessionError(NO_SUBJECT, "Indica la materia.")
    return subject


def question_key(lesson_id: int, question_id: str) -> str:
    return f"{lesson_id}:{question_id}"


def split_question_key(key: str) -> Tuple[Optional[int], str]:
    lesson, _, question = key.partition(":")
    try:
        return int(lesson), question
    except ValueError:
        return None, key


# ---------------------------------------------------------------- lezioni e pool

def _ready(summary: Dict[str, Any]) -> bool:
    return summary.get("phases", {}).get("rewrite") == "VALID"


def subject_lessons(materia: str) -> List[Dict[str, Any]]:
    """Riepiloghi delle lezioni della materia (o del giorno), dalla più vecchia (l'ordine dei turni)."""
    from rt.services.lesson_service import list_lessons
    subject = normalize_subject(materia)
    day = subject_day(subject)
    items = [i for i in list_lessons() if i["data"] == day] if day else list_lessons(materia=subject)
    return sorted(items, key=lambda i: (i["data"] or "9999", i["folder_name"]))


def _telegram_busy() -> set:
    """Lezioni con una sessione in corso su Telegram: la web app non ne pone le domande."""
    return {s["lesson_id"] for s in list_sessions(channel=TELEGRAM) if s.get("lesson_id") is not None}


def _classifying() -> set:
    """Lezioni con un job del classificatore in coda o in corso (percorsi come nella coda)."""
    from rt.services.jobs import JobState, get_job_queue
    try:
        jobs = get_job_queue().list(state=[JobState.QUEUED.value, JobState.RUNNING.value],
                                    job_type="unit_relevance", limit=1000)
    except Exception:  # coda non disponibile: lo stato resta quello delle etichette salvate
        LOG.debug("Coda dei job non disponibile per lo stato del classificatore", exc_info=True)
        return set()
    return {j.lesson_path for j in jobs if j.lesson_path}


def lesson_stats(summary: Dict[str, Any], telegram_busy: Optional[set] = None,
                 classifying: Optional[set] = None) -> Dict[str, Any]:
    """Domande per tipo e stato e risposte date di una lezione, come GET /lessons/{id}/recall."""
    from rt.db.repositories import normalize_lesson_path
    from rt.services.recall_service import recall_overview
    from rt.services.unit_relevance import classification_status
    ready = _ready(summary)
    overview = recall_overview(summary["path"]) if ready else {"questions": {}, "answers": 0}
    classification = classification_status(summary["path"]) if ready else None
    if classification and classification["state"] != "disabled" \
            and normalize_lesson_path(summary["path"]) in (classifying or set()):
        classification = {**classification, "state": "running"}
    return {"lesson_id": summary["id"], "ready": ready, "questions": overview["questions"],
            "answers": overview["answers"], "telegram": summary["id"] in (telegram_busy or set()),
            "classification": classification}


def recall_by_subject() -> List[Dict[str, Any]]:
    """Per la pagina del recall: ogni materia con il pool delle sue lezioni e la sessione per
    materia in corso. Le lezioni senza materia stanno sotto materia vuota."""
    from rt.services.lesson_service import list_lessons
    busy, classifying = _telegram_busy(), _classifying()
    subjects: Dict[str, List[Dict[str, Any]]] = {}
    for summary in list_lessons():
        subjects.setdefault(summary["materia"] or "", []).append(lesson_stats(summary, busy, classifying))
    active = {s["subject"]: s for s in _subject_sessions(state=ACTIVE)}
    out = [{"materia": materia, "lessons": lessons, "session": active.get(materia) if materia else None}
           for materia, lessons in sorted(subjects.items())]
    # Sessioni del giorno in corso: senza lezioni proprie (sono già sotto le loro materie).
    return out + [{"materia": subject, "lessons": [], "session": session}
                  for subject, session in sorted(active.items()) if subject_day(subject)]


def subject_overview(materia: str) -> Dict[str, Any]:
    subject = normalize_subject(materia)
    busy, classifying = _telegram_busy(), _classifying()
    lessons = [lesson_stats(s, busy, classifying) for s in subject_lessons(subject)]
    return {"materia": subject, "lessons": lessons, "session": active_subject_session(subject),
            "last": last_ended_subject_session(subject)}


def lessons_without_reserve(materia: str) -> List[Dict[str, Any]]:
    """Lezioni pronte (rielaborazione valida) che non hanno ancora nessuna domanda."""
    from rt.pipeline.recall import load_recall_bank
    return [s for s in subject_lessons(materia) if _ready(s) and not load_recall_bank(s["path"]).questions]


# ---------------------------------------------------------------- registro

def _subject_sessions(subject: Optional[str] = None, channel: str = WEB,
                      state: Optional[str] = ACTIVE) -> List[Dict[str, Any]]:
    db = require_database()
    stmt = select(RecallSession).where(RecallSession.subject.is_not(None), RecallSession.channel == channel)
    if subject:
        stmt = stmt.where(RecallSession.subject == subject)
    if state:
        stmt = stmt.where(RecallSession.state == state)
    with read_scope(db) as session:
        return _views(session, list(session.scalars(stmt.order_by(RecallSession.id.desc()))))


def active_subject_session(materia: str, channel: str = WEB) -> Optional[Dict[str, Any]]:
    rows = _subject_sessions(normalize_subject(materia), channel=channel)
    return rows[0] if rows else None


def last_ended_subject_session(materia: str, channel: str = WEB) -> Optional[Dict[str, Any]]:
    """L'ultima sessione per materia chiusa, se è più recente dell'ultima aperta."""
    rows = _subject_sessions(normalize_subject(materia), channel=channel, state=None)
    return rows[0] if rows and rows[0]["state"] != ACTIVE else None


def _active_row(session, subject: str, channel: str) -> Optional[RecallSession]:
    return session.scalars(select(RecallSession).where(
        RecallSession.subject == subject, RecallSession.channel == channel,
        RecallSession.state == ACTIVE)).first()


def _last_lesson(subject: str, channel: str) -> Optional[int]:
    db = require_database()
    with read_scope(db) as session:
        row = _active_row(session, subject, channel)
        ids = list(row.question_ids or []) if row is not None else []
    return split_question_key(ids[-1])[0] if ids else None


def current_subject_question(materia: str, channel: str = WEB):
    """Last question in the active subject session, for reconnecting study clients."""
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    from rt.services.recall_service import find_question
    with read_scope(require_database()) as session:
        row = _active_row(session, normalize_subject(materia), channel)
        key = (row.question_ids or [])[-1] if row and row.question_ids else None
    if not key:
        return None
    lesson_id, question_id = split_question_key(key)
    if lesson_id is None:
        return None
    try:
        lesson_dir = resolve_lesson_dir(lesson_id)
    except LessonNotFound:
        return None
    question = find_question(lesson_dir, question_id)
    return {"lesson_id": lesson_id, "lesson_dir": lesson_dir, "question": question} if question else None


def record_subject_question(materia: str, lesson_id: int, question_id: str, qtype: str,
                            channel: str = WEB) -> Dict[str, Any]:
    """Domanda posta nella sessione per materia: la apre se non c'è e la annota."""
    subject = normalize_subject(materia)
    db = require_database()
    with session_scope(db) as session:
        row = _active_row(session, subject, channel)
        if row is None:
            row = RecallSession(lesson_path="", subject=subject, channel=channel, state=ACTIVE,
                                started_at=_now(), question_ids=[])
            session.add(row)
        key = question_key(lesson_id, question_id)
        ids = [k for k in (row.question_ids or []) if k != key]
        row.question_ids = [*ids, key]  # in fondo: l'ultima domanda decide il turno
        row.qtype = qtype
        session.flush()
        return _views(session, [row])[0]


def summarize_subject(question_keys: List[str]) -> Dict[str, int]:
    """Riepilogo come per una lezione, sommato sulle lezioni delle domande poste (le lezioni
    eliminate nel frattempo non contano)."""
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    by_lesson: Dict[int, List[str]] = {}
    for key in question_keys:
        lesson_id, question_id = split_question_key(key)
        if lesson_id is not None:
            by_lesson.setdefault(lesson_id, []).append(question_id)
    total = {"questions": 0, "answered": 0, "quiz_answered": 0, "correct": 0}
    for lesson_id, ids in by_lesson.items():
        try:
            lesson_dir = resolve_lesson_dir(lesson_id)
        except LessonNotFound:
            continue
        for k, v in summarize(lesson_dir, question_ids=ids).items():
            total[k] += v
    return total


def end_subject_session(materia: str, ended_by: str = "web", channel: str = WEB) -> Dict[str, Any]:
    """Chiude la sessione per materia attiva e ne salva il riepilogo. RecallSessionError se non c'è."""
    subject = normalize_subject(materia)
    db = require_database()
    with session_scope(db) as session:
        row = _active_row(session, subject, channel)
        if row is None:
            raise RecallSessionError("no_active_session", "Nessuna sessione in corso su questa materia.")
        keys = list(row.question_ids or [])
    summary = summarize_subject(keys)  # legge i recall_bank fuori dalla transazione
    with session_scope(db) as session:
        row = _active_row(session, subject, channel)
        if row is None:
            raise RecallSessionError("no_active_session", "Nessuna sessione in corso su questa materia.")
        row.state = ENDED
        row.ended_at = _now()
        row.ended_by = ended_by
        row.summary = summary
        session.flush()
        return _views(session, [row])[0]


# ---------------------------------------------------------------- prossima domanda

def _turn_order(candidates: List[Dict[str, Any]], all_ids: List[int], last: Optional[int],
                order: str) -> List[Dict[str, Any]]:
    """Le lezioni candidate nell'ordine in cui provarle: a caso, oppure a partire da quella
    che segue l'ultima usata (ricominciando dalla prima)."""
    if order == "casuale":
        return random.sample(candidates, len(candidates))
    if last is None or last not in all_ids:
        return candidates
    pos = all_ids.index(last)
    return sorted(candidates, key=lambda s: (all_ids.index(s["id"]) <= pos, all_ids.index(s["id"])))


def next_subject_question(materia: str, qtype: RecallQuestionType, order: str = "alternato",
                          exclude: Optional[str] = None, channel: str = WEB) -> Optional[Dict[str, Any]]:
    """Prossima domanda della materia (marcata come posta e annotata nella sessione per materia):
    {"lesson_id", "lesson_dir", "question"}, o None se nessuna lezione ha domande da porre di
    quel tipo. exclude è la domanda appena saltata ("<id lezione>:<id domanda>"): si passa alla
    lezione seguente e, se è l'unica con domande, non si ripropone subito la stessa."""
    from rt.pipeline.recall import get_reserve_count
    from rt.services.recall_service import pick_pending_question
    subject = normalize_subject(materia)
    lessons = [s for s in subject_lessons(subject) if _ready(s)]
    busy = _telegram_busy() if channel == WEB else set()
    candidates = [s for s in lessons if s["id"] not in busy and get_reserve_count(s["path"], qtype) > 0]
    skipped_lesson, skipped_id = split_question_key(exclude) if exclude else (None, None)
    last = _last_lesson(subject, channel)
    if skipped_lesson is not None:
        last = skipped_lesson
    for summary in _turn_order(candidates, [s["id"] for s in lessons], last, order):
        question = pick_pending_question(summary["path"], qtype, order=order, current=False,
                                         exclude_id=skipped_id if summary["id"] == skipped_lesson else None)
        if question is None:
            continue
        record_subject_question(subject, summary["id"], question.id, qtype.value, channel=channel)
        return {"lesson_id": summary["id"], "lesson_dir": summary["path"], "question": question}
    return None
