"""
rt.db.session
Transazioni brevi: un blocco `with session_scope(db) as s:` fa commit all'uscita e rollback
su eccezione.
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from rt.db.engine import Database


@contextmanager
def session_scope(db: Database) -> Iterator[Session]:
    session = db.sessions()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
