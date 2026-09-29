"""
tests/test_api_recall_subject.py
Recall per materia: riserva delle lezioni per materia, sessione che pesca le domande da tutte le
lezioni della materia a turno, risposte con gli endpoint della lezione, riepilogo alla chiusura.
"""
import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


def _drain(rt_db):
    worker = Worker(DbJobQueue(rt_db), worker_id="w", mock=True)
    while worker.run_once() is not None:
        pass


@pytest.fixture
def lessons(api_client, tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    run_mock_pipeline(make_lesson(root))
    run_mock_pipeline(make_lesson(root, name="2025-01-02 BIOCHIMICA seconda"))
    items = api_client.get("/api/v1/lessons").json()
    assert {i["materia"] for i in items} == {"BIOCHIMICA"}
    return sorted(i["id"] for i in items)


def _correct_index(lesson_id, question_id):
    from rt.pipeline.recall import load_recall_bank
    from rt.services.lesson_service import resolve_lesson_dir
    bank = load_recall_bank(resolve_lesson_dir(lesson_id))
    return next(q for q in bank.questions if q.id == question_id).correct_index


def test_subject_session_rotates_lessons_and_saves_summary(api_client, lessons, rt_db):
    subjects = api_client.get("/api/v1/recall/subjects").json()
    assert [s["materia"] for s in subjects] == ["BIOCHIMICA"]
    assert all(l["ready"] and l["questions"] == {} for l in subjects[0]["lessons"])
    assert api_client.post("/api/v1/recall/subject/next", params={"materia": "BIOCHIMICA"}).status_code == 404

    res = api_client.post("/api/v1/recall/subject/generate", params={"materia": "biochimica", "mock": True})
    assert res.status_code == 202, res.text
    assert sorted(j["lesson_id"] for j in res.json()["jobs"]) == lessons
    _drain(rt_db)
    assert api_client.post("/api/v1/recall/subject/generate", params={"materia": "BIOCHIMICA"}).json()["jobs"] == []

    state = api_client.get("/api/v1/recall/subject", params={"materia": "Biochimica"}).json()
    assert state["materia"] == "BIOCHIMICA" and state["session"] is None and state["last"] is None
    assert all(l["questions"]["quiz"]["pending"] > 0 for l in state["lessons"])

    first = api_client.post("/api/v1/recall/subject/next", params={"materia": "BIOCHIMICA", "qtype": "quiz"}).json()
    second = api_client.post("/api/v1/recall/subject/next", params={"materia": "BIOCHIMICA", "qtype": "quiz"}).json()
    assert {first["lesson_id"], second["lesson_id"]} == set(lessons)  # le lezioni si danno il turno
    assert first["question"]["type"] == "quiz" and first["question"]["correct_index"] is None

    # la risposta passa dagli endpoint della lezione della domanda
    lid, qid = first["lesson_id"], first["question"]["id"]
    res = api_client.post(f"/api/v1/lessons/{lid}/recall/answer",
                          json={"question_id": qid, "choice": _correct_index(lid, qid)})
    assert res.json()["correct"] is True

    # la domanda saltata torna in coda e si passa all'altra lezione
    skipped = second
    api_client.post(f"/api/v1/lessons/{skipped['lesson_id']}/recall/skip", json={"question_id": skipped["question"]["id"]})
    after = api_client.post("/api/v1/recall/subject/next", params={
        "materia": "BIOCHIMICA", "qtype": "quiz",
        "exclude": f"{skipped['lesson_id']}:{skipped['question']['id']}"}).json()
    assert after["lesson_id"] != skipped["lesson_id"]

    session = api_client.get("/api/v1/recall/subject", params={"materia": "BIOCHIMICA"}).json()["session"]
    assert session["subject"] == "BIOCHIMICA" and session["state"] == "active" and session["questions"] == 3
    # la sessione per materia non è la sessione web della lezione
    assert api_client.get(f"/api/v1/lessons/{lid}/recall/session").json()["web"] is None
    assert api_client.get("/api/v1/recall/subjects").json()[0]["session"]["id"] == session["id"]

    res = api_client.post("/api/v1/recall/subject/end", params={"materia": "BIOCHIMICA"})
    assert res.status_code == 200, res.text
    assert res.json()["summary"] == {"questions": 3, "answered": 1, "quiz_answered": 1, "correct": 1}
    state = api_client.get("/api/v1/recall/subject", params={"materia": "BIOCHIMICA"}).json()
    assert state["session"] is None and state["last"]["id"] == session["id"]
    assert api_client.post("/api/v1/recall/subject/end", params={"materia": "BIOCHIMICA"}).status_code == 404


def test_subject_requires_a_name(api_client, lessons):
    res = api_client.get("/api/v1/recall/subject", params={"materia": "  "})
    assert res.status_code == 422
    res = api_client.post("/api/v1/recall/subject/next", params={"materia": "ANATOMIA"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "no_questions"
