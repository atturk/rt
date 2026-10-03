"""Metadati 4.2: rinomina, ID stabile, collisioni, blocchi e ora."""
import os
import pytest
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from rt.core.lesson_paths import lesson_path
from rt.core.state import read_info_yaml
from rt.storage import fs

@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    return make_lesson(isolated_workspace(tmp_path, monkeypatch))


def ident(client):
    return client.get('/api/v1/lessons').json()[0]['id']

@pytest.mark.parametrize('storage', ['folder', 'db'])
def test_metadata_rename_keeps_id_and_history(api_client, lesson, rt_db, storage):
    from rt.db.models import Job, Lesson
    from rt.db.session import session_scope
    from rt.services.jobs import DbJobQueue
    from rt.db.repositories import LessonRepository
    lesson_id = ident(api_client)
    if storage == 'db':
        from rt.storage.migrate import migrate_storage
        assert not migrate_storage(os.path.dirname(lesson)).errors
    job_id = DbJobQueue(rt_db).enqueue('run_phase', lesson, {'phase': 'build'})
    with session_scope(rt_db) as s:
        s.get(Job, job_id).state = 'succeeded'
    res = api_client.patch(f'/api/v1/lessons/{lesson_id}/metadata', json={
        'titolo': "L'acidosi", 'materia': 'fisiologia', 'data': '2026-10-03', 'ora': '09:30', 'docente': "D'Amico"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['id'] == lesson_id and body['ora'] == '09:30'
    assert body['folder_name'] == "[2026-10-03] FISIOLOGIA - L'acidosi"
    assert body['docente'] == "D'Amico" and body['titolo'] == "L'acidosi"
    assert not fs.exists(lesson)
    assert fs.isfile(lesson_path(body['path'], 'trascritto grezzo.md'))
    with session_scope(rt_db) as s:
        assert s.get(Job, job_id).lesson_path == body['path']
        assert LessonRepository(s).get_by_path(body['path']).id == lesson_id
    assert api_client.get(f'/api/v1/lessons/{lesson_id}').status_code == 200

@pytest.mark.parametrize('state', ['queued', 'running', 'waiting_for_decision'])
def test_metadata_busy(api_client, lesson, rt_db, state):
    from rt.db.models import Job
    from rt.db.session import session_scope
    from rt.services.jobs import DbJobQueue
    lesson_id = ident(api_client)
    job_id = DbJobQueue(rt_db).enqueue('run_phase', lesson, {})
    with session_scope(rt_db) as s: s.get(Job, job_id).state = state
    res = api_client.patch(f'/api/v1/lessons/{lesson_id}/metadata', json={'titolo': 'Nuovo'})
    assert res.status_code == 409 and res.json()['error']['code'] == 'lesson_busy'
    assert os.path.isdir(lesson)

@pytest.mark.parametrize('body', [{'ora': '24:00'}, {'data': '2026-02-30'}, {'titolo': '  '}, {'docente': 'A\nB'}, {'ora': None}])
def test_metadata_validation(api_client, lesson, body):
    assert api_client.patch(f'/api/v1/lessons/{ident(api_client)}/metadata', json=body).status_code == 422


def test_collision_does_not_change_info(api_client, lesson):
    from rt.core.state import update_info_yaml
    update_info_yaml(lesson_path(lesson, 'info.yaml'), {'titolo': 'Originale'})
    lesson_id = ident(api_client)
    info = read_info_yaml(lesson_path(lesson, 'info.yaml'))
    target = os.path.join(os.path.dirname(lesson), f"[{info['data']}] {info['materia']} - Nuovo")
    os.mkdir(target)
    res = api_client.patch(f'/api/v1/lessons/{lesson_id}/metadata', json={'titolo': 'Nuovo'})
    assert res.status_code == 409
    assert read_info_yaml(lesson_path(lesson, 'info.yaml')) == info


def test_cli_lock_and_editor_lease_block_metadata(api_client, lesson):
    from rt.core.process_lock import lesson_work_lock
    lesson_id = ident(api_client)
    url = f'/api/v1/lessons/{lesson_id}/metadata'
    with lesson_work_lock(lesson):
        assert api_client.patch(url, json={'ora': '10:00'}).status_code == 409
    assert api_client.post(f'/api/v1/lessons/{lesson_id}/document/lease').status_code == 200
    assert api_client.patch(url, json={'ora': '10:00'}).status_code == 409


def test_order_by_hour_and_custom_title_after_build(api_client, lesson):
    from rt.core.state import update_info_yaml
    from rt.pipeline.build import run_build
    assert run_mock_pipeline(lesson).status.value == 'completed'
    lesson_id = ident(api_client)
    res = api_client.patch(f'/api/v1/lessons/{lesson_id}/metadata', json={'titolo': 'Titolo scelto', 'ora': '09:00'})
    assert res.status_code == 200
    current = res.json()['path']
    assert res.json()['phases']['build'] == 'STALE'
    run_build(current, force=True)
    assert read_info_yaml(lesson_path(current, 'info.yaml'))['titolo'] == 'Titolo scelto'
    from rt.pipeline.build import render_lesson_documents
    assert 'Titolo scelto' in render_lesson_documents(current)['rielaborato']
    other = make_lesson(os.path.dirname(current), name='a')
    info = read_info_yaml(lesson_path(current, 'info.yaml'))
    update_info_yaml(lesson_path(other, 'info.yaml'), {'data': info['data'], 'ora': '15:00'})
    rows = api_client.get('/api/v1/lessons').json()
    assert [r['ora'] for r in rows] == ['15:00', '09:00']
