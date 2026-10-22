import pytest
from rt.services.notes_lesson_service import create_notes_lesson
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace


@pytest.mark.parametrize('extra', [{}, {'docente': 'Altro', 'ora': '13:00'}])
def test_conflict_before_queue(api_client, rt_db, tmp_path, monkeypatch, extra):
    root = isolated_workspace(tmp_path, monkeypatch)
    from rt.services.lesson_service import lessons_root
    lesson = create_notes_lesson('original', date='2026-10-21', materia='PATOLOGIA GENERALE', argomenti='Cellule', dest_dir=lessons_root())
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-21', 'materia': 'patologia generale', 'argomenti': 'Cellule', 'appunti': 'nuovi', **extra})
    assert response.status_code == 409, response.text
    error = response.json()['error']
    assert error['code'] == 'lesson_exists'
    assert error['details']['lesson_id']
    assert error['details']['argomenti'] == 'Cellule'
    assert '21/10/2026 di PATOLOGIA GENERALE' in error['message']
    assert not DbJobQueue(rt_db).list()
    assert api_client.post('/api/v1/lessons', data={'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'argomenti': 'Altri', 'appunti': 'nuovi'}).status_code == 202


def test_worker_conflict_and_corrected_metadata(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    data = {'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'appunti': 'testo'}
    first = api_client.post('/api/v1/lessons', data=data)
    second = api_client.post('/api/v1/lessons', data=data)
    assert first.status_code == second.status_code == 202
    worker = Worker(DbJobQueue(rt_db), job_types=['ingest_notes'], on_message=lambda *_: None)
    assert worker.run_once().state == 'succeeded'
    failed = worker.run_once()
    assert failed.state == 'failed'
    assert failed.result['code'] == 'lesson_exists'
    assert failed.result['details']['lesson_id']
    url = f'/api/v1/jobs/{failed.id}/recreate-lesson'
    assert api_client.post(url, json={'date': data['date'], 'materia': data['materia']}).status_code == 409
    assert api_client.post(url, json={'date': data['date'], 'materia': data['materia'], 'argomenti': 'Nuovi'}).status_code == 202
    assert worker.run_once().state == 'succeeded'
