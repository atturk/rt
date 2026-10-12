"""Registro materie e vista unita con lezioni e calendario."""
from sqlalchemy import select

from rt.db.engine import get_database
from rt.db.models import Subject, Lesson, CalendarTemplateEntry, CalendarOverride
from rt.db.session import read_scope, session_scope
from rt.services.errors import Conflict, Invalid, NotFound, Unavailable


def _database(db=None):
    database = db or get_database()
    if database is None:
        raise Unavailable("database_unavailable", "Database non disponibile.")
    return database


def _view(session):
    names = {}
    counts = {}
    for name in session.scalars(select(Subject.nome).order_by(Subject.nome)):
        names[name.casefold()] = name
    for model in (Lesson, CalendarTemplateEntry, CalendarOverride):
        for value in session.scalars(select(model.materia)):
            name = (value or "").strip()
            if not name:
                continue
            key = name.casefold()
            names.setdefault(key, name)
            if model is Lesson:
                counts[key] = counts.get(key, 0) + 1
    return [{"nome": names[key], "lezioni": counts.get(key, 0)} for key in sorted(names)]


def list_subjects(db=None):
    with read_scope(_database(db)) as session:
        return _view(session)


def create_subject(nome, db=None):
    nome = nome.strip()
    if not nome or len(nome) > 256:
        raise Invalid("invalid_subject", "Indica una materia di massimo 256 caratteri.")
    with session_scope(_database(db)) as session:
        if any(row["nome"].casefold() == nome.casefold() for row in _view(session)):
            raise Conflict("subject_exists", "La materia esiste già.")
        session.add(Subject(nome=nome))
    return {"nome": nome, "lezioni": 0}


def delete_subject(nome, db=None):
    with session_scope(_database(db)) as session:
        match = next((row for row in _view(session) if row["nome"].casefold() == nome.casefold()), None)
        if match is None:
            raise NotFound("subject_not_found", "Materia inesistente.")
        if match["lezioni"]:
            raise Conflict("subject_in_use", "La materia ha lezioni.")
        registered = next((row for row in session.scalars(select(Subject))
                           if row.nome.casefold() == nome.casefold()), None)
        if registered is not None:
            session.delete(registered)
