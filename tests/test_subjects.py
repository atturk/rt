from alembic import command
from sqlalchemy import inspect, text

from rt.db.engine import alembic_config, create_db_engine, upgrade_database
from rt.db.models import CalendarTemplateEntry, Lesson
from rt.db.session import session_scope


def test_subject_contract(api_client, rt_db, tmp_path):
    client = api_client
    assert client.post('/api/v1/subjects', json={'nome': 'Biologia'}).json() == {'nome': 'Biologia', 'lezioni': 0, 'docenti': []}
    with session_scope(rt_db) as s:
        s.add(Lesson(path=str(tmp_path / 'lesson'), folder_name='lesson', materia='BIOLOGIA'))
        s.add(CalendarTemplateEntry(day_of_week=0, start_time='09:00', end_time='10:00', materia='biologia'))
        s.add(CalendarTemplateEntry(day_of_week=0, start_time='10:00', end_time='11:00', materia='Anatomia'))
    assert client.get('/api/v1/subjects').json() == [
        {'nome': 'Anatomia', 'lezioni': 0, 'docenti': []}, {'nome': 'Biologia', 'lezioni': 1, 'docenti': []}]
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
    with session_scope(rt_db) as s:
        repo = LessonRepository(s)
        lesson = repo.get_or_create(str(tmp_path / 'lesson'))
        repo.update_fields(lesson, {'materia': 'Biologia'})
        s.delete(lesson)
    entry = create_template_entry(CalendarTemplateEntryCreate(
        day_of_week=0, start_time='09:00', end_time='10:00', materia='Anatomia'))
    delete_template_entry(entry.id)
    assert list_subjects() == [{'nome': 'Anatomia', 'lezioni': 0, 'docenti': []}, {'nome': 'Biologia', 'lezioni': 0, 'docenti': []}]
    assert view()['materie'] == ['Anatomia', 'Biologia']


def test_teachers_api_registration_and_deletion(api_client, rt_db, tmp_path):
    from rt.api.schemas import CalendarTemplateEntryCreate, CalendarOverrideCreate
    from rt.db.repositories import LessonRepository
    from rt.services.calendar_service import create_template_entry, create_override
    from rt.services.subjects import list_subjects
    c = api_client
    assert c.post('/api/v1/subjects/Missing/teachers', json={'nome': 'Rossi'}).status_code == 404
    c.post('/api/v1/subjects', json={'nome': 'Biologia'})
    url = '/api/v1/subjects/biologia/teachers'
    assert c.post(url, json={'nome': 'Rossi'}).json()['docenti'] == ['Rossi']
    assert c.post(url, json={'nome': 'ROSSI'}).status_code == 409
    assert c.post(url, json={'nome': 'ROSSI'}).json()['error']['code'] == 'teacher_exists'
    with session_scope(rt_db) as s:
        repo = LessonRepository(s)
        lesson = repo.get_or_create(str(tmp_path / 'new'))
        repo.update_fields(lesson, {'materia': 'BIOLOGIA', 'docente': 'Verdi'})
        lesson_id = lesson.id
    create_template_entry(CalendarTemplateEntryCreate(day_of_week=0, start_time='09:00', end_time='10:00',
                                                     materia='Biologia', docente='Bianchi'))
    create_override(CalendarOverrideCreate(date='2026-10-12', action='added', start_time='10:00', end_time='11:00',
                                           materia='BIOLOGIA', docente='Neri'))
    assert list_subjects()[0]['docenti'] == ['Bianchi', 'Neri', 'Rossi', 'Verdi']
    assert c.delete(url + '/verdi').status_code == 204
    with session_scope(rt_db) as s:
        assert s.get(Lesson, lesson_id).docente == 'Verdi'
    assert 'Verdi' not in list_subjects()[0]['docenti']
    c.post('/api/v1/subjects', json={'nome': 'Chimica'})
    c.post('/api/v1/subjects/Chimica/teachers', json={'nome': 'Rossi'})
    assert c.delete('/api/v1/subjects/Chimica').status_code == 204
    from rt.db.models import SubjectTeacher
    from sqlalchemy import select
    with session_scope(rt_db) as s:
        assert not list(s.scalars(select(SubjectTeacher).where(SubjectTeacher.materia == 'Chimica')))


def test_teacher_migration_populates_existing_lessons_and_calendar(tmp_path):
    from rt.db.models import CalendarOverride, LessonFile
    from sqlalchemy.orm import Session
    url = f"sqlite:///{tmp_path / 'teachers.db'}"
    engine = create_db_engine(url)
    command.upgrade(alembic_config(url, engine), '0018')
    # Le lezioni storiche non hanno ancora la colonna docente.
    with engine.begin() as c:
        c.execute(text("INSERT INTO lessons (id,path,folder_name,data,materia,titolo,argomenti,workflow_state,storage,created_at,updated_at) VALUES (1,:path,'lesson','','Biologia','','','','db',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {'path': str(tmp_path / 'lesson')})
        c.execute(text("INSERT INTO lesson_files (lesson_id,name,content,size,sha256,mtime) VALUES (1,'info.yaml',:content,0,'',0)"), {'content': b'materia: Biologia\ndocente: Rossi\n'})
        c.execute(text("INSERT INTO calendar_template_entries (day_of_week,start_time,end_time,materia,docente,valid_from,created_at,updated_at) VALUES (0,'09:00','10:00','BIOLOGIA','ROSSI','2026-01-01',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO calendar_overrides (date,action,start_time,end_time,materia,docente,created_at,updated_at) VALUES ('2026-10-12','added','10:00','11:00','biologia','Verdi',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    upgrade_database(url, engine)
    with engine.connect() as c:
        assert c.execute(text('SELECT docente FROM lessons')).scalar() == 'Rossi'
        assert c.execute(text('SELECT materia,nome FROM subject_teachers ORDER BY nome')).all() == [('Biologia', 'Rossi'), ('Biologia', 'Verdi')]
    engine.dispose()
