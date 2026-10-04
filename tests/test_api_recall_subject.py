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

    # Il test della rotazione richiede almeno due domande per lezione, a prescindere
    # da quante ne genera una singola unità nel protocollo a cardinalità variabile.
    from rt.pipeline.recall import load_recall_bank, save_recall_bank
    from rt.services.lesson_service import resolve_lesson_dir
    for lesson_id in lessons:
        directory = resolve_lesson_dir(lesson_id)
        bank = load_recall_bank(directory)
        quiz = next(q for q in bank.questions if q.type.value == "quiz")
        bank.questions.append(quiz.model_copy(update={
            "id": f"rotation_extra_{lesson_id}", "question_text": f"Seconda domanda di rotazione {lesson_id}?"}))
        save_recall_bank(bank, directory)

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


def test_day_session_uses_the_lessons_of_that_day(api_client, lessons, rt_db):
    items = api_client.get("/api/v1/lessons").json()
    day = items[0]["data"]
    same_day = sorted(i["id"] for i in items if i["data"] == day)
    subject = f"GIORNO:{day}"
    state = api_client.get("/api/v1/recall/subject", params={"materia": subject}).json()
    assert state["materia"] == subject and sorted(l["lesson_id"] for l in state["lessons"]) == same_day
    assert all(l["classification"]["state"] in ("disabled", "never", "done", "partial", "stale") for l in state["lessons"])

    api_client.post("/api/v1/recall/subject/generate", params={"materia": subject, "mock": True})
    _drain(rt_db)
    res = api_client.post("/api/v1/recall/subject/next", params={"materia": subject, "qtype": "quiz", "mock": True})
    assert res.status_code == 200, res.text
    assert res.json()["lesson_id"] in same_day
    # la sessione del giorno in corso compare nell'elenco della pagina del recall, senza lezioni sue
    subjects = {s["materia"]: s for s in api_client.get("/api/v1/recall/subjects").json()}
    assert subjects[subject]["session"] is not None and subjects[subject]["lessons"] == []
    assert api_client.post("/api/v1/recall/subject/end", params={"materia": subject}).status_code == 200
    assert subject not in {s["materia"] for s in api_client.get("/api/v1/recall/subjects").json()}


def test_queued_classifier_shows_running_until_the_job_ends(api_client, lessons, rt_db, monkeypatch):
    """Con un job del classificatore in coda o in corso la lezione è "in classificazione"."""
    from rt.services import unit_relevance
    monkeypatch.setattr(unit_relevance, "classification_status", lambda path: {"state": "stale", "classified": 0, "total": 2})
    monkeypatch.setattr(unit_relevance, "ensure_can_run", lambda: None)

    def states():
        subject = api_client.get("/api/v1/recall/subjects").json()[0]
        return {l["lesson_id"]: l["classification"]["state"] for l in subject["lessons"]}

    assert set(states().values()) == {"stale"}
    res = api_client.post(f"/api/v1/lessons/{lessons[0]}/relevance/run", json={"force": False, "mock": True})
    assert res.status_code == 202, res.text
    assert states() == {lessons[0]: "running", lessons[1]: "stale"}
    _drain(rt_db)
    assert set(states().values()) == {"stale"}


def test_selection_session_uses_the_chosen_lessons(api_client, lessons, rt_db):
    """Recall sulla selezione della pagina Lezioni: LEZIONI:<id>,<id>, in qualsiasi ordine."""
    items = api_client.get("/api/v1/lessons").json()
    chosen = sorted(i["id"] for i in items)[:2]
    subject = "LEZIONI:" + ",".join(str(i) for i in chosen)
    state = api_client.get("/api/v1/recall/subject", params={"materia": f"LEZIONI:{chosen[1]},{chosen[0]},{chosen[1]}"}).json()
    assert state["materia"] == subject and sorted(l["lesson_id"] for l in state["lessons"]) == chosen

    api_client.post("/api/v1/recall/subject/generate", params={"materia": subject, "mock": True})
    _drain(rt_db)
    res = api_client.post("/api/v1/recall/subject/next", params={"materia": subject, "qtype": "quiz", "mock": True})
    assert res.status_code == 200, res.text
    assert res.json()["lesson_id"] in chosen
    subjects = {s["materia"]: s for s in api_client.get("/api/v1/recall/subjects").json()}
    assert subjects[subject]["session"] is not None and subjects[subject]["lessons"] == []
    assert api_client.post("/api/v1/recall/subject/end", params={"materia": subject}).status_code == 200

    bad = api_client.get("/api/v1/recall/subject", params={"materia": "LEZIONI:"})
    assert bad.status_code == 422
