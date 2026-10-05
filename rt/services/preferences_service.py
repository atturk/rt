"""Preferenze personali JSON nella tabella settings, separate dalla configurazione."""
from sqlalchemy import select

from rt.db.engine import get_database
from rt.db.models import Setting
from rt.db.repositories import SettingRepository
from rt.db.session import read_scope, session_scope

PREFIX = "pref:"


def list_preferences() -> dict:
    with read_scope(get_database()) as session:
        return {row.key[len(PREFIX):]: row.value
                for row in session.scalars(select(Setting).where(Setting.key.startswith(PREFIX)))}


def save_preference(name: str, value) -> None:
    with session_scope(get_database()) as session:
        SettingRepository(session).set(PREFIX + name, value)


def delete_preference(name: str) -> None:
    with session_scope(get_database()) as session:
        SettingRepository(session).delete(PREFIX + name)
