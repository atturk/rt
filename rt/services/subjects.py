"""Registro materie e vista unita con lezioni e calendario."""
from sqlalchemy import select

from rt.db.engine import get_database
from rt.db.models import Subject, SubjectTeacher, Lesson, CalendarTemplateEntry, CalendarOverride
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
    teachers = {}
    for teacher in session.scalars(select(SubjectTeacher)):
        teachers.setdefault(teacher.materia.casefold(), []).append(teacher.nome)
    return [{"nome": names[key], "lezioni": counts.get(key, 0),
             "docenti": sorted(teachers.get(key, []), key=str.casefold)} for key in sorted(names)]


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
    return {"nome": nome, "lezioni": 0, "docenti": []}


def delete_subject(nome, db=None):
    with session_scope(_database(db)) as session:
        match = next((row for row in _view(session) if row["nome"].casefold() == nome.casefold()), None)
        if match is None:
            raise NotFound("subject_not_found", "Materia inesistente.")
        if match["lezioni"]:
            raise Conflict("subject_in_use", "La materia ha lezioni.")
        # Una materia usata dal calendario resterebbe in elenco: niente 204 senza effetto.
        if any((value or "").strip().casefold() == nome.casefold()
               for model in (CalendarTemplateEntry, CalendarOverride)
               for value in session.scalars(select(model.materia))):
            raise Conflict("subject_in_calendar",
                           "La materia è usata nel calendario: cambiala o toglila dalle ore del calendario per eliminarla.")
        registered = next((row for row in session.scalars(select(Subject))
                           if row.nome.casefold() == nome.casefold()), None)
        if registered is not None:
            session.delete(registered)
        for teacher in session.scalars(select(SubjectTeacher)):
            if teacher.materia.casefold() == nome.casefold():
                session.delete(teacher)


def register_subject(session, nome):
    """Registrazione implicita nella stessa transazione della lezione o dell'ora."""
    nome = (nome or "").strip()
    if nome and not any(value.casefold() == nome.casefold()
                        for value in session.scalars(select(Subject.nome))):
        session.add(Subject(nome=nome))
        session.flush()


def register_teacher(session, materia, docente):
    materia, docente = (materia or "").strip(), (docente or "").strip()
    if not materia or not docente:
        return
    if len(materia) > 256 or len(docente) > 256:
        raise Invalid("invalid_teacher", "Indica un docente di massimo 256 caratteri.")
    register_subject(session, materia)
    canonical = next(name for name in session.scalars(select(Subject.nome)) if name.casefold() == materia.casefold())
    if not any(row.materia.casefold() == materia.casefold() and row.nome.casefold() == docente.casefold()
               for row in session.scalars(select(SubjectTeacher))):
        session.add(SubjectTeacher(materia=canonical, nome=docente))
        session.flush()


def add_teacher(materia, nome, db=None):
    nome = nome.strip()
    if not nome or len(nome) > 256:
        raise Invalid("invalid_teacher", "Indica un docente di massimo 256 caratteri.")
    with session_scope(_database(db)) as session:
        subject = next((row for row in _view(session) if row['nome'].casefold() == materia.casefold()), None)
        if subject is None:
            raise NotFound("subject_not_found", "Materia inesistente.")
        if any(teacher.casefold() == nome.casefold() for teacher in subject['docenti']):
            raise Conflict("teacher_exists", "Il docente esiste già.")
        register_teacher(session, subject['nome'], nome)
        return next(row for row in _view(session) if row['nome'] == subject['nome'])


def delete_teacher(materia, nome, db=None):
    with session_scope(_database(db)) as session:
        teacher = next((row for row in session.scalars(select(SubjectTeacher))
                        if row.materia.casefold() == materia.casefold() and row.nome.casefold() == nome.casefold()), None)
        if teacher is None:
            raise NotFound("teacher_not_found", "Docente inesistente.")
        session.delete(teacher)
