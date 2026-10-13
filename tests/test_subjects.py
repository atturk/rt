from alembic import command
from sqlalchemy import inspect, text

from rt.db.engine import alembic_config, create_db_engine, upgrade_database
from rt.db.models import CalendarTemplateEntry, Lesson
from rt.db.session import session_scope


def test_subject_contract(api_client, rt_db, tmp_path):
    client = api_client
    assert client.post('/api/v1/subjects', json={'nome': 'Biologia'}).json() == {'nome': 'Biologia', 'lezioni': 0}
    with session_scope(rt_db) as s:
        s.add(Lesson(path=str(tmp_path / 'lesson'), folder_name='lesson', materia='BIOLOGIA'))
        s.add(CalendarTemplateEntry(day_of_week=0, start_time='09:00', end_time='10:00', materia='biologia'))
        s.add(CalendarTemplateEntry(day_of_week=0, start_time='10:00', end_time='11:00', materia='Anatomia'))
    assert client.get('/api/v1/subjects').json() == [
        {'nome': 'Anatomia', 'lezioni': 0}, {'nome': 'Biologia', 'lezioni': 1}]
    response = client.post('/api/v1/subjects', json={'nome': 'bIOLOGIA'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'subject_exists'
    response = client.delete('/api/v1/subjects/BIOLOGIA')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'subject_in_use'
    response = client.delete('/api/v1/subjects/Anatomia')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'subject_in_calendar'
    assert client.post('/api/v1/subjects', json={'nome': 'Chimica'}).status_code == 201
    assert client.delete('/api/v1/subjects/chimica').status_code == 204


def test_subject_migration_keeps_existing_table(tmp_path):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    engine = create_db_engine(url)
    command.upgrade(alembic_config(url, engine), '0017')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE subjects (nome VARCHAR(256) PRIMARY KEY, creata_il DATETIME NOT NULL)'))
        connection.execute(text("INSERT INTO subjects VALUES ('Biologia', '2026-10-12')"))
    upgrade_database(url, engine)
    assert inspect(engine).has_table('subjects')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT nome FROM subjects')).scalar() == 'Biologia'
    engine.dispose()


def test_subject_registration_survives_lesson_and_calendar_deletion(rt_db, tmp_path):
    from rt.api.schemas import CalendarTemplateEntryCreate
    from rt.db.models import Subject
    from rt.db.repositories import LessonRepository
    from rt.services.calendar_service import create_template_entry, delete_template_entry
    from rt.services.subjects import list_subjects
    from rt.services.custom_question_settings import view
    from rt.services.telegram_topics import known_materie
    with session_scope(rt_db) as s:
        repo = LessonRepository(s)
        lesson = repo.get_or_create(str(tmp_path / 'lesson'))
        repo.update_fields(lesson, {'materia': 'Biologia'})
        s.delete(lesson)
    entry = create_template_entry(CalendarTemplateEntryCreate(
        day_of_week=0, start_time='09:00', end_time='10:00', materia='Anatomia'))
    delete_template_entry(entry.id)
    assert list_subjects() == [{'nome': 'Anatomia', 'lezioni': 0}, {'nome': 'Biologia', 'lezioni': 0}]
    assert view()['materie'] == ['Anatomia', 'Biologia']
    assert {'ANATOMIA', 'BIOLOGIA'} <= set(known_materie())
