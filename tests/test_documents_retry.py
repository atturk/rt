"""Il job derivato di V5 non blocca Riprova, ma l'esecuzione resta seriale."""
import pytest
from rt.services.jobs import DbJobQueue
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


@pytest.mark.parametrize('running', [False, True])
def test_retry_queues_behind_automatic_documents(tmp_path, monkeypatch, rt_db, api_client, running):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    queue = DbJobQueue(rt_db)
    first = queue.enqueue('run_phase', lesson, {'phase': 'prepare', 'options': {'mock': True}})
    assert queue.claim('first').id == first
    queue.finish(first, 'first', 'failed', error='Fase fallita')
    documents = queue.enqueue('documents', lesson, {})
    if running:
        assert queue.claim('documents').id == documents
    response = api_client.post(f'/api/v1/jobs/{first}/retry')
    assert response.status_code == 202, response.text
    retry = response.json()['job_id']
    assert queue.get(retry).retry_of == first
    assert queue.get(documents).state == ('running' if running else 'queued')
    if running:
        assert queue.claim('second', job_types=['run_phase']) is None
        queue.finish(documents, 'documents', 'succeeded', result={})
    assert queue.claim('second', job_types=['run_phase']).id == retry
