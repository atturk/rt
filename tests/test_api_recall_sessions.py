"""
tests/test_api_recall_sessions.py
RT4-FA7: sessioni di recall. "Termina sessione" nella web app salva il riepilogo.
"""

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.fixture
def lesson_id(api_client, ws, rt_db):
    run_mock_pipeline(make_lesson(ws))
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={"mock": True}).status_code == 202
    worker = Worker(DbJobQueue(rt_db), worker_id="w", mock=True)
    while worker.run_once() is not None:
        pass
    return lid


def _state(client, lid):
    res = client.get(f"/api/v1/lessons/{lid}/recall/session")
    assert res.status_code == 200, res.text
    return res.json()


def test_web_session_end_saves_summary(api_client, lesson_id):
    lid = lesson_id
    assert _state(api_client, lid)["web"] is None
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/session/end").status_code == 404

    quiz = api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "quiz"}).json()
    history = api_client.get(f"/api/v1/lessons/{lid}/recall/history").json()
    correct = next(q for q in history["questions"] if q["id"] == quiz["id"])
    # la soluzione non si vede prima di rispondere: si ricava dal quiz del bank
    from rt.pipeline.recall import load_recall_bank
    from rt.services.lesson_service import resolve_lesson_dir
    bank = load_recall_bank(resolve_lesson_dir(lid))
    right = next(q for q in bank.questions if q.id == correct["id"]).correct_index
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/answer",
                           json={"question_id": quiz["id"], "choice": right}).json()["correct"] is True
    api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "mirata"})

    web = _state(api_client, lid)["web"]
    assert web["state"] == "active" and web["channel"] == "web" and web["questions"] == 2

    res = api_client.post(f"/api/v1/lessons/{lid}/recall/session/end")
    assert res.status_code == 200, res.text
    ended = res.json()
    assert ended["state"] == "ended" and ended["ended_by"] == "web" and ended["ended_at"]
    assert ended["summary"] == {"questions": 2, "answered": 1, "quiz_answered": 1, "correct": 1}

    # stato salvato: la sessione resta chiusa e il riepilogo si rilegge
    state = _state(api_client, lid)
    assert state["web"] is None and state["last"]["id"] == ended["id"]
    assert state["last"]["summary"]["correct"] == 1
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/session/end").status_code == 404
    from rt.services.recall_service import load_recall_session_state
    assert load_recall_session_state(resolve_lesson_dir(lid))["current_question_id"] is None

    # Quiz e mirata sono consumati: la riserva vasta apre una nuova sessione.
    api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "vasta"})
    state = _state(api_client, lid)
    assert state["web"]["id"] != ended["id"] and state["web"]["questions"] == 1 and state["last"] is None


