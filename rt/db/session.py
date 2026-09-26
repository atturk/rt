"""
rt.db.session
Transazioni brevi: un blocco `with session_scope(db) as s:` fa commit all'uscita e rollback
su eccezione.

joined_scope() riusa la sessione già aperta nello stesso thread per lo stesso DB (se c'è):
chi legge o scrive file di lezione nel DB (rt.storage.fs) mentre un chiamante tiene aperta
una transazione di scrittura non apre una seconda transazione, che su SQLite aspetterebbe
il lock della prima. read_scope() apre una transazione di sola lettura (BEGIN semplice
invece di BEGIN IMMEDIATE), che in WAL non blocca e non è bloccata dagli scrittori.
"""
import threading
from contextlib import contextmanager
from typing import Dict, Iterator, List

from sqlalchemy.orm import Session

from rt.db.engine import Database

_local = threading.local()


def _stack(db: Database) -> List[Session]:
    stacks: Dict[str, List[Session]] = getattr(_local, "stacks", None)
    if stacks is None:
        stacks = _local.stacks = {}
    return stacks.setdefault(db.url, [])


@contextmanager
def session_scope(db: Database) -> Iterator[Session]:
    session = db.sessions()
    stack = _stack(db)
    stack.append(session)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        stack.remove(session)
        session.close()


@contextmanager
def read_scope(db: Database) -> Iterator[Session]:
    """Sessione di sola lettura (niente lock di scrittura su SQLite)."""
    stack = _stack(db)
    if stack:
        yield stack[-1]
        return
    session = Session(bind=db.engine.execution_options(rt_read_only=True), expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@contextmanager
def joined_scope(db: Database) -> Iterator[Session]:
    """La sessione aperta in questo thread per questo DB, altrimenti una nuova session_scope."""
    stack = _stack(db)
    if stack:
        session = stack[-1]
        yield session
        session.flush()
        return
    with session_scope(db) as session:
        yield session
