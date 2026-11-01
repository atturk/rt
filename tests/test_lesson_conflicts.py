import os

import pytest
from rt.services.notes_lesson_service import create_notes_lesson
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace


@pytest.mark.parametrize('extra', [{}, {'docente': 'Altro'}])
def test_conflict_before_queue(api_client, rt_db, tmp_path, monkeypatch, extra):
    root = isolated_workspace(tmp_path, monkeypatch)
    from rt.services.lesson_service import lessons_root
    lesson = create_notes_lesson('original', date='2026-10-21', materia='PATOLOGIA GENERALE', ora='09:00', dest_dir=lessons_root())
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-21', 'materia': 'patologia generale', 'ora': '09:00', 'appunti': 'nuovi', **extra})
    assert response.status_code == 409, response.text
    error = response.json()['error']
    assert error['code'] == 'lesson_exists'
    assert error['details']['lesson_id']
    assert error['details']['ora'] == '09:00'
    assert '21/10/2026 di PATOLOGIA GENERALE alle 09:00' in error['message']
    assert not DbJobQueue(rt_db).list()
    # Un'altra ora, o nessuna ora, è un'altra lezione.
    assert api_client.post('/api/v1/lessons', data={'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'ora': '11:00', 'appunti': 'nuovi'}).status_code == 202
    assert api_client.post('/api/v1/lessons', data={'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'appunti': 'nuovi'}).status_code == 202


def test_same_day_without_time_gets_a_number(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    data = {'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'appunti': 'testo'}
    assert api_client.post('/api/v1/lessons', data=data).status_code == 202
    assert api_client.post('/api/v1/lessons', data=data).status_code == 202
    worker = Worker(DbJobQueue(rt_db), job_types=['ingest_notes'], on_message=lambda *_: None)
    import os
    paths = [worker.run_once().lesson_path for _ in range(2)]
    assert [os.path.basename(p) for p in paths] == ['[2026-10-21] PATOLOGIA GENERALE', '[2026-10-21] PATOLOGIA GENERALE (2)']


def test_worker_conflict_and_corrected_metadata(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    data = {'date': '2026-10-21', 'materia': 'PATOLOGIA GENERALE', 'ora': '09:00', 'appunti': 'testo'}
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
    assert api_client.post(url, json={'date': data['date'], 'materia': data['materia'], 'ora': '09:00'}).status_code == 409
    assert api_client.post(url, json={'date': data['date'], 'materia': data['materia'], 'ora': '11:00'}).status_code == 202
    assert worker.run_once().state == 'succeeded'


def test_two_workers_reserve_the_same_name_once(rt_db, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from rt.services.lesson_conflicts import create_lesson_directory, LessonConflict
    root = isolated_workspace(tmp_path, monkeypatch)
    barrier = Barrier(2)
    def reserve(ora):
        barrier.wait(timeout=5)
        try:
            return create_lesson_directory('2026-10-21', 'TEST', ora, root)
        except LessonConflict as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve('09:00'), range(2)))
    assert sum(isinstance(item, LessonConflict) for item in results) == 1
    barrier.reset()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(''), range(2)))
    assert sorted(os.path.basename(path) for path in results) == ['[2026-10-21] TEST', '[2026-10-21] TEST (2)']
