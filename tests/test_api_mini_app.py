"""Study-only Telegram API: real RT storage, recall banks and worker; no paid calls."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from rt.api.app import create_app
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline

TOKEN = "123:test-token"
UID = 12345
BASE = "/api/v1/mini-app"


def init_data(uid=UID, age=0):
    fields = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": uid, "first_name": "Student"}), "query_id": "example"}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def client(monkeypatch, tmp_path, rt_db):
    isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("RT_TELEGRAM_MINI_APP_USER_IDS", str(UID))
    return TestClient(create_app(serve_spa=False))


def login(client):
    r = client.post(BASE + "/auth", json={"init_data": init_data()})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = "Bearer " + r.json()["token"]


def test_signed_identity_is_scoped_and_revocable(client, monkeypatch):
    assert client.get(BASE + "/lessons").status_code == 401
    login(client)
    assert client.get(BASE + "/lessons").status_code == 200
    assert client.get("/api/v1/lessons").status_code == 401
    assert client.get("/api/v1/settings").status_code in (401, 404)
    monkeypatch.setenv("RT_TELEGRAM_MINI_APP_USER_IDS", "6789")
    assert client.get(BASE + "/lessons").status_code == 401


# Init data is built inside the test: ids computed from time.time() at collection differ
# between xdist workers and abort the whole run.
@pytest.mark.parametrize("make_raw,status", [
    pytest.param(lambda: init_data(age=600), 401, id="expired"),
    pytest.param(lambda: init_data(age=-600), 401, id="future"),
    pytest.param(lambda: init_data(uid=6789), 403, id="unknown-user"),
    pytest.param(lambda: init_data() + "&auth_date=0", 401, id="duplicate-field"),
    pytest.param(lambda: init_data().replace("Student", "Intruder"), 401, id="tampered"),
    pytest.param(lambda: "hash=bad", 401, id="bad-hash"),
])
def test_invalid_telegram_identity(client, make_raw, status):
    assert client.post(BASE + "/auth", json={"init_data": make_raw()}).status_code == status


def test_access_is_disabled_until_owner_configures_ids(client, monkeypatch):
    monkeypatch.delenv("RT_TELEGRAM_MINI_APP_USER_IDS")
    assert client.post(BASE + "/auth", json={"init_data": init_data()}).status_code == 503


@pytest.fixture
def lesson(client, monkeypatch, tmp_path, rt_db):
    # Reuse the workspace already isolated by client.
    root = str(tmp_path / "lessons")
    run_mock_pipeline(make_lesson(root))
    login(client)
    lid = client.get(BASE + "/lessons").json()[0]["id"]
    from rt.api import jobs
    def enqueue_mock(kind, lesson_dir, payload, actor):
        return jobs.enqueue_job(kind, lesson_dir, {**payload, "mock": True, "force_mock": True}, actor)
    monkeypatch.setattr("rt.api.routers.recall.enqueue_job", enqueue_mock)
    accepted = client.post(f"{BASE}/lessons/{lid}/generate").json()
    worker = Worker(DbJobQueue(rt_db), worker_id="mini-test", mock=True)
    while worker.run_once() is not None:
        pass
    assert client.get(f"{BASE}/jobs/{accepted['job_id']}").json()["state"] == "succeeded"
    return lid, worker


def test_real_recall_and_consultation_share_the_existing_services(client, lesson, rt_db):
    lid, worker = lesson
    listing = client.get(BASE + "/lessons").json()[0]
    assert "path" not in listing and "cost_usd" not in listing
    detail = client.get(f"{BASE}/lessons/{lid}").json()
    assert detail["ready"] and detail["units"] and detail["units"][0]["html"]
    assert client.get(f"{BASE}/lessons/{lid}/units/missing/audio").status_code == 404
    question = client.post(f"{BASE}/lessons/{lid}/next").json()
    assert "correct_index" not in question and "explanation" not in question
    resume = client.get(f"{BASE}/lessons/{lid}/resume", params={"question_id": question["id"]})
    assert resume.status_code == 200 and resume.json()["answer"] is None
    result = client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": question["id"], "choice": 0})
    assert result.status_code == 200 and "correct_index" in result.json()["question"]
    assert client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": question["id"], "choice": 0}).status_code == 409
    assert client.post(f"{BASE}/lessons/{lid}/vote", json={"question_id": question["id"], "vote": "up"}).status_code == 200
    from rt.pipeline.recall import load_recall_bank
    from rt.services.lesson_service import resolve_lesson_dir
    bank = load_recall_bank(resolve_lesson_dir(lid))
    assert any(a.question_id == question["id"] for a in bank.answers)
    ended = client.post(f"{BASE}/lessons/{lid}/end").json()
    assert ended["summary"]["answered"] == 1
    assert client.get(f"{BASE}/lessons/{lid}/resume", params={"question_id": question["id"]}).status_code == 404


def test_dont_know_skip_and_open_answer_jobs(client, lesson):
    lid, worker = lesson
    q = client.post(f"{BASE}/lessons/{lid}/next").json()
    assert client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": q["id"], "dont_know": True}).json()["dont_know"]
    q = client.post(f"{BASE}/lessons/{lid}/next").json()
    assert client.post(f"{BASE}/lessons/{lid}/skip", json={"question_id": q["id"]}).status_code == 200
    client.post(f"{BASE}/lessons/{lid}/generate?qtype=mirata")
    while worker.run_once() is not None:
        pass
    q = client.post(f"{BASE}/lessons/{lid}/next?qtype=mirata").json()
    r = client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": q["id"], "answer": "La risposta dello studente"})
    assert r.status_code == 202, r.text
    assert client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": q["id"], "answer": "Doppio invio"}).status_code == 409
    while worker.run_once() is not None:
        pass
    result = client.get(f"{BASE}/jobs/{r.json()['job_id']}").json()
    assert result["state"] == "succeeded" and result["result"]["evaluation"]
    assert "payload" not in result and "lesson_path" not in result


def test_job_ownership(client, rt_db):
    login(client)
    job_id = DbJobQueue(rt_db).enqueue("recall_generate", payload={}, created_by="another-user")
    assert client.get(f"{BASE}/jobs/{job_id}").status_code == 404


def test_reconnect_does_not_consume_another_question(client, lesson):
    lid, _worker = lesson
    first = client.post(f"{BASE}/lessons/{lid}/next").json()
    assert client.post(f"{BASE}/lessons/{lid}/next").json()["id"] == first["id"]
    summary = client.post(f"{BASE}/lessons/{lid}/end").json()["summary"]
    assert summary["questions"] == 1


def test_generate_retry_reuses_the_queued_job(client, lesson):
    lid, _worker = lesson
    first = client.post(f"{BASE}/lessons/{lid}/generate?qtype=vasta").json()
    assert client.post(f"{BASE}/lessons/{lid}/generate?qtype=vasta").json()["job_id"] == first["job_id"]


def test_subject_round_robin_resume_and_end(client, lesson, tmp_path):
    lid, worker = lesson
    root = str(tmp_path / "lessons")
    run_mock_pipeline(make_lesson(root, name="2026-09-02_BIOCHIMICA_seconda"))
    ids = [row["id"] for row in client.get(BASE + "/lessons").json()]
    second_id = next(i for i in ids if i != lid)
    client.post(f"{BASE}/lessons/{second_id}/generate")
    while worker.run_once() is not None:
        pass
    params = {"materia": "BIOCHIMICA", "qtype": "quiz"}
    first = client.post(BASE + "/subject/next", params=params).json()
    again = client.post(BASE + "/subject/next", params=params).json()
    assert again == first
    qid = first["question"]["id"]
    assert client.get(f"{BASE}/lessons/{first['lesson_id']}/resume", params={"question_id": qid, "materia": "BIOCHIMICA"}).status_code == 200
    client.post(f"{BASE}/lessons/{first['lesson_id']}/answer", json={"question_id": qid, "choice": 0})
    after = client.post(BASE + "/subject/next", params=params).json()
    assert after["lesson_id"] != first["lesson_id"]
    ended = client.post(BASE + "/subject/end", params={"materia": "BIOCHIMICA"}).json()
    assert ended["summary"]["questions"] == 2 and ended["summary"]["answered"] == 1


def test_voice_job_is_recoverable_and_uses_existing_worker(client, lesson):
    from tests.api_support import AUDIO_FIXTURE
    lid, worker = lesson
    client.post(f"{BASE}/lessons/{lid}/generate?qtype=mirata")
    while worker.run_once() is not None:
        pass
    q = client.post(f"{BASE}/lessons/{lid}/next?qtype=mirata").json()
    with open(AUDIO_FIXTURE, "rb") as sound:
        response = client.post(f"{BASE}/lessons/{lid}/answer-voice", data={"question_id": q["id"]}, files={"audio": ("answer.wav", sound, "audio/wav")})
    assert response.status_code == 202, response.text
    resumed = client.get(f"{BASE}/lessons/{lid}/resume", params={"question_id": q["id"]}).json()
    assert resumed["pending_job"]["job_id"] == response.json()["job_id"]
    while worker.run_once() is not None:
        pass
    result = client.get(f"{BASE}/jobs/{response.json()['job_id']}").json()
    assert result["state"] == "succeeded", result
    assert result["result"]["answer"] and result["result"]["evaluation"] and result["result"]["is_voice"]


def test_study_markdown_keeps_images_authenticated_and_escapes_html():
    from rt.api.routers.mini_app import _unit_html
    html = _unit_html('<script>alert(1)</script>\n\n![Slide](assets/images/slide.png)\n\n![External](https://example.com/private.png)')
    assert '<script>' not in html and 'data-rt-image="slide.png"' in html
    assert 'src=' not in html


def test_session_expiry_and_signature_are_checked(client, monkeypatch):
    login(client)
    valid = client.headers["Authorization"]
    client.headers["Authorization"] = valid[:-1] + ('0' if valid[-1] != '0' else '1')
    assert client.get(BASE + "/lessons").status_code == 401
    client.headers["Authorization"] = valid
    now = time.time()
    monkeypatch.setattr("rt.api.mini_auth.time.time", lambda: now + 3601)
    assert client.get(BASE + "/lessons").status_code == 401


def test_dedicated_bot_auth_does_not_require_replacing_rt_bot(client, monkeypatch):
    monkeypatch.setenv("RT_TELEGRAM_MINI_APP_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:main-bot-kept")
    login(client)
    assert client.get(BASE + "/lessons").status_code == 200


def test_audio_download_and_send_use_the_existing_clip_and_topic_services(client, lesson, monkeypatch, tmp_path):
    from rt.services.lesson_service import resolve_lesson_dir
    lid, _worker = lesson
    unit = client.get(f"{BASE}/lessons/{lid}").json()["units"][0]
    clip = tmp_path / "clip.m4a"
    clip.write_bytes(b"test-audio")
    selected = []
    def existing_clip(directory, draft_unit, segments):
        selected.append((directory, draft_unit.unit_id))
        return str(clip)
    monkeypatch.setattr("rt.core.audio_clip.get_or_create_unit_clip", existing_clip)
    response = client.get(f"{BASE}/lessons/{lid}/units/{unit['id']}/audio")
    assert response.status_code == 200 and response.content == b"test-audio"
    assert response.headers["cache-control"] == "private, no-store"
    assert selected == [(resolve_lesson_dir(lid), unit["id"])]
    sent = []
    monkeypatch.setattr("rt.telegram.recall_channel.send_unit_audio", lambda directory, question, **kwargs: sent.append((directory, question.unit_ids, kwargs)))
    response = client.post(f"{BASE}/lessons/{lid}/units/{unit['id']}/send-audio")
    assert response.status_code == 200
    assert sent[0][0] == resolve_lesson_dir(lid) and sent[0][1] == [unit["id"]]
    assert "message_thread_id" in sent[0][2]


def test_resume_rejects_a_question_from_a_previously_ended_session(client, lesson):
    lid, _worker = lesson
    old = client.post(f"{BASE}/lessons/{lid}/next").json()
    client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": old["id"], "choice": 0})
    client.post(f"{BASE}/lessons/{lid}/end")
    current = client.post(f"{BASE}/lessons/{lid}/next").json()
    assert current["id"] != old["id"]
    assert client.get(f"{BASE}/lessons/{lid}/resume", params={"question_id": old["id"]}).status_code == 404
    assert client.get(f"{BASE}/lessons/{lid}/resume", params={"question_id": current["id"]}).status_code == 200


def test_mixed_type_unit_review_and_day_session(client, lesson, tmp_path):
    lid, worker = lesson
    client.post(f"{BASE}/lessons/{lid}/generate?qtype=mirata")
    while worker.run_once() is not None:
        pass
    detail = client.get(f"{BASE}/lessons/{lid}").json()
    unit = next(u for u in detail["units"] if u["pending"])
    assert set(unit["pending"]) <= {"quiz", "mirata", "caso", "esercizio"}
    # Leggi e ripeti: solo domande di quell'unità, tipi a turno.
    first = client.post(f"{BASE}/lessons/{lid}/next", params={"qtype": "mista", "unit_id": unit["id"]}).json()
    assert unit["id"] in first["unit_ids"]
    again = client.post(f"{BASE}/lessons/{lid}/next", params={"qtype": "mista", "unit_id": unit["id"]}).json()
    assert again["id"] == first["id"]  # riconnessione: la domanda posta resta quella
    client.post(f"{BASE}/lessons/{lid}/skip", json={"question_id": first["id"]})
    client.post(f"{BASE}/lessons/{lid}/end")
    # Ripasso del giorno: la sessione per materia con le lezioni della data.
    day = client.get(BASE + "/lessons").json()[0]["data"]
    params = {"materia": f"GIORNO:{day}", "qtype": "mista"}
    picked = client.post(BASE + "/subject/next", params=params).json()
    assert picked["lesson_id"] == lid and picked["question"]["type"] in {"quiz", "mirata"}
    client.post(f"{BASE}/lessons/{lid}/answer", json={"question_id": picked["question"]["id"], "dont_know": True})
    while worker.run_once() is not None:  # una mirata si valuta in un job
        pass
    nxt = client.post(BASE + "/subject/next", params=params).json()
    assert nxt["question"]["id"] != picked["question"]["id"]
    assert client.post(BASE + "/subject/end", params={"materia": f"GIORNO:{day}"}).json()["summary"]["questions"] == 2
