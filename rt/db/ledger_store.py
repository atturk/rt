"""
rt.db.ledger_store
Ledger delle decisioni con il DB come fonte di verità (RT4-B3).

Ogni modifica (nuova decisione, annullamento, purge per prefisso) avviene in una transazione:
prima si reimporta review_decisions.json se è cambiato fuori da RT (hash diverso da
Lesson.ledger_sha), poi si modifica il DB, poi si riesporta il file nello stesso formato di
sempre. Le decisioni annullate restano nel DB con reverted_at, non nel file.
"""
import hashlib
from typing import Any, Callable, Optional

from rt.db.engine import get_database
from rt.db.repositories import DecisionRepository, LessonRepository
from rt.db.session import session_scope
from rt.db import sync as db_sync

NO_DATABASE = object()


def mutate_ledger(lesson_dir: str, op: Callable[[DecisionRepository, Any], Any]) -> Any:
    """Esegue op(repo, lesson) sul DB e, se il risultato è vero (qualcosa è cambiato),
    riesporta il file. NO_DATABASE se il DB non c'è (il chiamante scrive il file come prima)."""
    db = get_database()
    if db is None:
        return NO_DATABASE
    from rt.core.models import DecisionLedger, ReviewDecision
    from rt.pipeline.ledger import get_ledger_path, write_ledger_file

    with db_sync.suspend_dual_write(), session_scope(db) as session:
        lesson = db_sync.sync_lesson(session, lesson_dir)
        if lesson is None:
            lesson = LessonRepository(session).get_or_create(lesson_dir)
            db_sync.import_ledger(session, lesson, lesson_dir)
        repo = DecisionRepository(session)
        result = op(repo, lesson)
        if not result:  # niente da annullare: il file resta com'è (o assente)
            return result
        ledger = DecisionLedger(schema_version="1.0", decisions=[
            ReviewDecision(**{k: getattr(row, k) for k in db_sync.DECISION_FIELDS if getattr(row, k) is not None})
            for row in repo.active(lesson)
        ])
        write_ledger_file(ledger, lesson_dir)
        with open(get_ledger_path(lesson_dir), "rb") as f:
            lesson.ledger_sha = hashlib.sha256(f.read()).hexdigest()
    return result


def append_decision(lesson_dir: str, fields: dict) -> Any:
    return mutate_ledger(lesson_dir, lambda repo, lesson: repo.append(lesson, fields))


def revert_last(lesson_dir: str, issue_id: str) -> Any:
    return mutate_ledger(lesson_dir, lambda repo, lesson: repo.revert_last(lesson, issue_id) is not None)


def revert_prefix(lesson_dir: str, prefix: str) -> Any:
    return mutate_ledger(lesson_dir, lambda repo, lesson: repo.revert_prefix(lesson, prefix))


def active_decision_count(lesson_dir: str) -> Optional[int]:
    db = get_database()
    if db is None:
        return None
    with session_scope(db) as session:
        lesson = LessonRepository(session).get_by_path(lesson_dir)
        return len(DecisionRepository(session).active(lesson)) if lesson else 0
