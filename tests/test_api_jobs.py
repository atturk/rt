"""
tests/test_api_jobs.py
RT4-E3: scritture, job ed eventi live via API. Il worker gira in processo (Worker.run_once),
come farebbe 'rt worker'.

End-to-end in mock: upload → job → attesa outline → approve → review → decisioni → build.
"""
import json
import os

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson
from tests.golden_support import AUDIO_FIXTURE


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="test-worker")


def drain(worker, limit=10):
    """Esegue i job in coda finché ce ne sono."""
    done = 0
    while worker.run_once() is not None:
        done += 1
        assert done <= limit
    return done


def job(client, job_id):
    return client.get(f"/api/v1/jobs/{job_id}").json()


def upload(client, run=False, mock=True):
    with open(AUDIO_FIXTURE, "rb") as f:
        return client.post("/api/v1/lessons", files={"audio": ("lezione.wav", f, "audio/wav")},
                           data={"date": "2026-09-05", "materia": "BIOCHIMICA", "argomenti": "Lipidi",
                                 "mock": str(mock).lower(), "run": str(run).lower()})


def test_end_to_end_upload_outline_review_decisions_build(api_client, ws, worker):
    res = upload(api_client)
    assert res.status_code == 202, res.text
    accepted = res.json()
    assert accepted["type"] == "ingest_audio" and accepted["worker_available"] is False
    drain(worker)
    ingest = job(api_client, accepted["job_id"])
    assert ingest["state"] == "succeeded", ingest
    lesson_id = ingest["lesson_id"]
    assert lesson_id is not None
    assert not os.listdir(os.path.join(ws, ".rt", "uploads"))  # upload temporaneo rimosso

    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "mock": True, "rename": False})
    assert res.status_code == 202
    run_id = res.json()["job_id"]
    drain(worker)
    waiting = job(api_client, run_id)
    assert waiting["state"] == "waiting_for_decision" and waiting["decision"]["kind"] == "outline_approval"

    assert api_client.post(f"/api/v1/lessons/{lesson_id}/outline/approve").json()["approved"] is True
    assert job(api_client, run_id)["state"] == "queued"  # la decisione ha ripreso il job
    drain(worker)
    waiting = job(api_client, run_id)
    assert waiting["state"] == "waiting_for_decision" and waiting["decision"]["kind"] == "science_issue"

    pending = api_client.get(f"/api/v1/lessons/{lesson_id}/issues").json()["items"]
    assert pending
    for item in pending:
        issue = item["issue"]
        asr = issue["type"].startswith("ERR_ASR") or issue["type"] == "ERR_REWRITE_DRIFT"
        decision = "accepted" if asr else "rejected"
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/issues/{issue['id']}/decision", json={"decision": decision})
        assert res.status_code == 200, res.text
        assert res.json()["channel"] == "api" and res.json()["actor"] == "api"
    assert job(api_client, run_id)["state"] == "queued"
    drain(worker)
    done = job(api_client, run_id)
    assert done["state"] == "succeeded", done
    detail = api_client.get(f"/api/v1/lessons/{lesson_id}").json()
    assert detail["phases"]["build"] == "VALID" and detail["pending_issues"] == 0
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()["final"] is True


def test_upload_with_run_runs_whole_pipeline(api_client, ws, worker):
    accepted = upload(api_client, run=True).json()
    assert accepted["type"] == "run_pipeline"
    drain(worker)
    waiting = job(api_client, accepted["job_id"])
    assert waiting["state"] == "waiting_for_decision" and waiting["decision"]["kind"] == "outline_approval"
    assert waiting["lesson_id"] is not None

    # Approvata la scaletta, lo stesso job riparte dalla lezione creata (non rifà il setup).
    assert api_client.post(f"/api/v1/lessons/{waiting['lesson_id']}/outline/approve").status_code == 200
    drain(worker)
    resumed = job(api_client, accepted["job_id"])
    assert resumed["state"] == "waiting_for_decision", resumed
    assert resumed["decision"]["kind"] == "science_issue"
    assert resumed["lesson_id"] == waiting["lesson_id"]


def test_upload_rejects_wrong_type_and_size(api_client, ws, monkeypatch):
    res = api_client.post("/api/v1/lessons", files={"audio": ("note.txt", b"ciao", "text/plain")},
                          data={"date": "2026-09-05", "materia": "X"})
    assert res.status_code == 415
    res = api_client.post("/api/v1/lessons", files={"audio": ("../../evil.m4a", b"", "audio/mp4")},
                          data={"date": "2026-09-05", "materia": "X"})
    assert res.status_code in (415, 422)
    monkeypatch.setenv("RT_API_MAX_UPLOAD_MB", "0.0001")
    with open(AUDIO_FIXTURE, "rb") as f:
        res = api_client.post("/api/v1/lessons", files={"audio": ("l.wav", f, "audio/wav")},
                              data={"date": "2026-09-05", "materia": "X"})
    assert res.status_code == 413
    assert os.listdir(os.path.join(ws, ".rt", "uploads")) == []  # niente file lasciati a metà


@pytest.fixture
def lesson(api_client, ws):
    lesson_dir = make_lesson(ws)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    return lesson_id, lesson_dir


def test_run_phase_jobs_and_events_sse(api_client, lesson, worker):
    lesson_id, _ = lesson
    ids = []
    for phase in ("prepare", "outline"):
        res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": phase, "mock": True})
        assert res.status_code == 202
        ids.append(res.json()["job_id"])
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase"}).status_code == 422
    drain(worker)
    assert [job(api_client, i)["state"] for i in ids] == ["succeeded", "succeeded"]
    assert api_client.get(f"/api/v1/lessons/{lesson_id}").json()["phases"]["outline"] == "VALID"

    with api_client.stream("GET", f"/api/v1/jobs/{ids[1]}/events") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(res.iter_text())
    blocks = [b for b in body.split("\n\n") if b.startswith("id:")]
    types = [b.split("\n")[1][len("event: "):] for b in blocks]
    assert types[0] == "job_queued" and "phase_started" in types and types[-1] == "job_finished"
    assert "event: end" in body
    # ripresa da Last-Event-ID: solo gli eventi successivi
    last_but_one = int(blocks[-2].split("\n")[0][len("id: "):])
    with api_client.stream("GET", f"/api/v1/jobs/{ids[1]}/events", headers={"Last-Event-ID": str(last_but_one)}) as res:
        resumed = [b for b in "".join(res.iter_text()).split("\n\n") if b.startswith("id:")]
    assert len(resumed) == 1 and json.loads(resumed[0].split("data: ", 1)[1])["type"] == "job_finished"


def test_cancel_queued_job(api_client, lesson):
    lesson_id, _ = lesson
    job_id = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"mock": True}).json()["job_id"]
    assert api_client.post(f"/api/v1/jobs/{job_id}/cancel").json()["state"] == "cancelled"
    assert api_client.get("/api/v1/jobs", params={"state": "cancelled"}).json()[0]["id"] == job_id
    assert api_client.get("/api/v1/jobs/nope").status_code == 404


def test_decisions_refused_while_job_runs(api_client, lesson, rt_db):
    lesson_id, lesson_dir = lesson
    q = DbJobQueue(rt_db)
    q.enqueue("run_pipeline", lesson_dir, {})
    assert q.claim("someone") is not None  # ora è running
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/outline/approve")
    assert res.status_code == 409 and res.json()["error"]["code"] == "lesson_busy"
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/issues/x/decision", json={"decision": "accepted"})
    assert res.status_code == 409
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/decisions/undo", json={"issue_id": "x"}).status_code == 409


def test_decision_undo_and_errors(api_client, lesson, worker):
    lesson_id, lesson_dir = lesson
    api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"mock": True, "rename": False})
    drain(worker)
    api_client.post(f"/api/v1/lessons/{lesson_id}/outline/approve")
    drain(worker)
    items = api_client.get(f"/api/v1/lessons/{lesson_id}/issues").json()["items"]
    concept = next(i["issue"] for i in items if i["issue"]["type"] == "ERR_CONCETTUALE")
    url = f"/api/v1/lessons/{lesson_id}/issues/{concept['id']}/decision"
    assert api_client.post(url, json={"decision": "edited"}).status_code == 409  # testo mancante
    assert api_client.post(url, json={"decision": "rejected"}).status_code == 200
    assert api_client.post(url, json={"decision": "rejected"}).status_code == 409  # già decisa
    undone = api_client.post(f"/api/v1/lessons/{lesson_id}/decisions/undo", json={"issue_id": concept["id"]})
    assert undone.status_code == 200 and undone.json()["decision"] == "rejected"
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/decisions/undo", json={"issue_id": concept["id"]}).status_code == 404
    pending_ids = [i["issue"]["id"] for i in api_client.get(f"/api/v1/lessons/{lesson_id}/issues").json()["items"]]
    assert concept["id"] in pending_ids


def test_outline_revision_job(api_client, lesson, worker):
    lesson_id, _ = lesson
    api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"mock": True})
    drain(worker)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/outline/revise", json={"feedback": "Dividi in due unità", "mock": True})
    assert res.status_code == 202
    drain(worker)
    done = job(api_client, res.json()["job_id"])
    assert done["state"] == "succeeded", done
    assert done["result"]["outline"]["approved"] is False


def test_recall_flow(api_client, lesson, worker):
    lesson_id, _ = lesson
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/recall/generate", json={"mock": True}).status_code == 409
    api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"mock": True, "auto_accept": True, "rename": False})
    drain(worker)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/generate", json={"mock": True})
    assert res.status_code == 202
    drain(worker)
    overview = api_client.get(f"/api/v1/lessons/{lesson_id}/recall").json()
    assert overview["questions"]["quiz"]["pending"] >= 1

    quiz = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/next", params={"qtype": "quiz"}).json()
    assert "correct_index" not in quiz or quiz["correct_index"] is None
    result = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/answer", json={"question_id": quiz["id"], "choice": 0}).json()
    assert result["question"]["status"] == "answered" and isinstance(result["correct"], bool)
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/recall/vote", json={"question_id": quiz["id"], "vote": "up"}).status_code == 200

    open_q = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/next", params={"qtype": "mirata"}).json()
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/answer",
                          json={"question_id": open_q["id"], "answer": "I lipidi sono nel tessuto adiposo", "mock": True})
    assert res.status_code == 202
    drain(worker)
    evaluated = job(api_client, res.json()["job_id"])
    assert evaluated["state"] == "succeeded" and evaluated["result"]["evaluation"]

    skipped = api_client.post(f"/api/v1/lessons/{lesson_id}/recall/next", params={"qtype": "vasta"}).json()
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/recall/skip", json={"question_id": skipped["id"]}).status_code == 200


def test_credential_test_job_mock(api_client, ws, worker):
    res = api_client.post("/api/v1/settings/test-credential", json={"credential": "x", "model": "m", "mock": True})
    assert res.status_code == 202
    drain(worker)
    assert job(api_client, res.json()["job_id"])["result"]["ok"] is True


def test_images_upload_validation(api_client, lesson):
    lesson_id, _ = lesson
    assert api_client.post(f"/api/v1/lessons/{lesson_id}/images").status_code == 422
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/images", files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert res.status_code == 415
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/images", files={"files": ("slide.png", b"\x89PNG....", "image/png")})
    assert res.status_code == 202 and res.json()["type"] == "add_images"


def test_workers_listed(api_client, ws, worker):
    worker.register()
    assert [w["id"] for w in api_client.get("/api/v1/workers").json()] == ["test-worker"]
