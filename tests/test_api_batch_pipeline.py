import pytest

from tests.api_support import isolated_workspace, make_lesson
from rt.services.lesson_service import lesson_id_for_dir


@pytest.fixture
def batch_lessons(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    dirs = [make_lesson(root, f'lezione-{i}') for i in range(3)]
    return [(lesson_id_for_dir(path), path) for path in dirs]


@pytest.mark.parametrize('mode', ['run', 'force'])
def test_batch_pipeline_jobs(api_client, batch_lessons, mode):
    from rt.api.jobs import queue
    ids = [item[0] for item in batch_lessons]
    response = api_client.post('/api/v1/lessons/batch/pipeline', json={
        'lesson_ids': ids + [ids[0]], 'mode': mode, 'with_review': True})
    assert response.status_code == 202, response.text
    data = response.json()
    assert data['skipped'] == []
    assert [job['lesson_id'] for job in data['queued']] == ids
    for accepted, (_, path) in zip(data['queued'], batch_lessons):
        job = queue().get(accepted['job_id'])
        assert job.type == 'run_pipeline'
        assert job.lesson_path == path
        assert job.payload['inputs'] == [path]
        assert job.payload['options']['force'] == (mode == 'force')
        assert job.payload['options']['with_review'] is True


def test_batch_skips_busy_and_missing(api_client, batch_lessons):
    from rt.api.jobs import queue
    first, second, _ = batch_lessons
    queue().enqueue('run_pipeline', first[1], {})
    response = api_client.post('/api/v1/lessons/batch/pipeline', json={'lesson_ids': [first[0], second[0], 999999]})
    assert response.status_code == 202, response.text
    assert [item['lesson_id'] for item in response.json()['queued']] == [second[0]]
    assert response.json()['skipped'] == [
        {'lesson_id': first[0], 'motivo': 'Lezione in lavorazione'},
        {'lesson_id': 999999, 'motivo': 'Lezione non trovata'}]


def test_batch_reingest_reuses_single_update(api_client, batch_lessons, monkeypatch):
    from rt.core.sources import add_source
    from rt.api.jobs import queue
    first, second, _ = batch_lessons
    # Una fonte valida: il controllo di disponibilità resta quello della rotta singola.
    add_source(first[1], 'appunti', 'appunti.txt', b'Appunti originali')
    monkeypatch.setattr('rt.api.routers.lesson_sources.reingest_availability',
                        lambda path: {'reingest_available': path == first[1], 'reingest_reason': 'Fonti mancanti'})
    response = api_client.post('/api/v1/lessons/batch/pipeline', json={
        'lesson_ids': [first[0], second[0]], 'mode': 'reingest', 'with_review': True})
    assert response.status_code == 202, response.text
    data = response.json()
    assert data['skipped'] == [{'lesson_id': second[0], 'motivo': 'Ripartenza da capo non disponibile'}]
    job = queue().get(data['queued'][0]['job_id'])
    assert job.type == 'update_lesson'
    assert job.payload == {'mode': 'rebuild', 'mock': False, 'reingest': True, 'with_review': True}


def test_batch_limit(api_client, batch_lessons):
    assert api_client.post('/api/v1/lessons/batch/pipeline', json={'lesson_ids': list(range(201))}).status_code == 422
