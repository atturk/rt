"""V2c: API reale e worker lento, decisioni/annullamenti solo sulle unità finite."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from rt.db.ledger_store import active_decision_count
from rt.pipeline.anchors import make_anchor
from rt.pipeline import review
from rt.pipeline.ledger import load_resolved_draft, load_ledger
from rt.pipeline.rewrite import load_draft
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.test_review_parallel import setup_six, finding
from tests.test_review_anchor_application import issue


def test_decide_finished_unit_while_another_is_running(tmp_path, monkeypatch, api_client, rt_db):
    lesson, cfg = setup_six(tmp_path, monkeypatch, 2)
    entered = threading.Event()
    finish = threading.Event()
    def slow(client, unit, *args, **kwargs):
        if unit.unit_id == '1.2':
            entered.set()
            assert finish.wait(timeout=15)
        result = finding(client, unit)
        for item in result:
            item.suggested_fix = 'Passaggio corretto.'
        return result
    monkeypatch.setattr(review, '_validated_review_issues', slow)
    original = load_draft(lesson).units[1]
    old = issue('sci_000001', '1.2', make_anchor(original.content, 0, len(original.content)))
    old.suggested_fix = 'Passaggio corretto.'
    review.save_science_issues([old], lesson)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    queue = DbJobQueue(rt_db)
    job_id = queue.enqueue('run_phase', lesson, {'phase': 'review', 'options': {'mock': True, 'force': True}})
    worker = Worker(queue, worker_id='review-decisions', mock=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(worker.run_once)
        try:
            assert entered.wait(timeout=10)
            deadline = time.monotonic() + 10
            while True:
                done = [e for e in queue.events(job_id) if e.type == 'review_unit_done' and e.payload.get('unit_id') == '1.1']
                if done:
                    break
                assert time.monotonic() < deadline
                threading.Event().wait(.02)
            assert queue.get(job_id).state == 'running'
            items = api_client.get(f'/api/v1/lessons/{lid}/issues?status=all').json()['items']
            first = next(item['issue']['id'] for item in items if item['issue']['unit_id'] == '1.1')
            path = f'/api/v1/lessons/{lid}/issues/{first}/decision'
            response = api_client.post(path, json={'decision': 'accepted'})
            assert response.status_code == 200, response.text
            assert load_resolved_draft(lesson).units[0].content == 'Passaggio corretto.'
            undo = f'/api/v1/lessons/{lid}/decisions/undo'
            assert api_client.post(undo, json={'issue_id': first}).status_code == 200
            assert api_client.post(path, json={'decision': 'accepted'}).status_code == 200
            blocked = api_client.post(f'/api/v1/lessons/{lid}/issues/{old.id}/decision', json={'decision': 'accepted'})
            assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'unit_in_review'
            blocked = api_client.post(undo, json={'issue_id': old.id})
            assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'unit_in_review'
        finally:
            finish.set()
        job.result(timeout=15)
    assert len(load_ledger(lesson).decisions) == active_decision_count(lesson) == 1
    assert load_ledger(lesson).decisions[0].issue_id == first
    assert load_resolved_draft(lesson).units[0].content == 'Passaggio corretto.'
    assert len([e for e in queue.events(job_id) if e.type == 'review_unit_done']) == 6
