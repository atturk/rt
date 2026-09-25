"""
tests/test_api_persistence.py
RT4-E5: ogni endpoint di scrittura salva nel backend. Per ogni scrittura: scrivi con un client,
poi rileggi da un processo nuovo (app, client e connessione al DB nuovi, variabili dei segreti
tolte dall'ambiente) e verifica il valore. È la regola nata dal modello "salvato" della web
Gradio che spariva al ricaricamento (piano, sezione 9-bis).

Gli avvii e gli arresti del bot Telegram non salvano nulla oltre al PID file del demone: sono
coperti in tests/test_api_parity.py e tests/test_api_settings.py.
"""
import json
import os
import subprocess
import sys

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import make_lesson, run_mock_pipeline, workspace_with_example_config
from tests.golden_support import AUDIO_FIXTURE, PROJECT_ROOT

KEY = "sk-or-v1-persistenza-0123456789abcdef"
BOT = "123456789:AAH-persistenza-bot-token-abcdef"
STT = "stt-persistenza-chiave-0123456789"

_READER = r"""
import json, sys
from fastapi.testclient import TestClient
from rt.api.app import create_app
token, paths = sys.argv[1], json.loads(sys.argv[2])
client = TestClient(create_app())
client.headers["Authorization"] = "Bearer " + token
out = {}
for path in paths:
    res = client.get("/api/v1" + path)
    out[path] = {"status": res.status_code, "body": res.json()}
print(json.dumps(out))
"""


def reread(token, *paths, drop_env=()):
    """GET dei percorsi da un processo Python nuovo, nella stessa cartella di lavoro e con lo
    stesso database; senza le variabili d'ambiente dei segreti (devono arrivare da .env o
    dall'archivio cifrato)."""
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT, PYTHONIOENCODING="utf-8")
    for name in drop_env:
        env.pop(name, None)
    proc = subprocess.run([sys.executable, "-c", _READER, token, json.dumps(list(paths))], cwd=os.getcwd(),
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    for path, res in data.items():
        assert res["status"] == 200, (path, res)
    return {path: res["body"] for path, res in data.items()}


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    monkeypatch.delenv("RT_STT_API_KEY", raising=False)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "test-disabled-token")
    return workspace_with_example_config(tmp_path, monkeypatch)


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="persist-worker")


def drain(worker):
    while worker.run_once() is not None:
        pass


def ok(res, codes=(200, 201, 202)):
    assert res.status_code in codes, res.text
    return res.json()


def lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


# ---------------------------------------------------------------- impostazioni e segreti

def test_settings_writes_persist(api_client, api_token, ws, tmp_path):
    c = api_client
    settings = ok(c.post("/api/v1/settings/connections", json={"name": "Casa", "provider": "openrouter",
                                                                 "api_keys": [KEY]}))
    jobs = [p["job"] for p in settings["phases"]]
    assert len(jobs) == 6
    ok(c.post("/api/v1/settings/connections/Casa/models", json={"model": "vendor/extra"}))
    for n, job in enumerate(jobs):  # tutte e sei le fasi
        ok(c.put(f"/api/v1/settings/phases/{job}", json={"connection": "Casa", "model": f"vendor/fase-{n}"}))
    cred = ok(c.get("/api/v1/settings"))["connections"][-1]["credentials"][0]["name"]
    ok(c.put("/api/v1/settings/routes/rewrite/secondary", json={"provider": "openrouter", "credential": cred,
                                                                 "model": "vendor/secondaria"}))
    new_root = tmp_path / "radice nuova"
    ok(c.put("/api/v1/settings/lessons-root", json={"path": str(new_root)}))
    ok(c.put("/api/v1/settings/transcription", json={"engine": "custom", "base_url": "http://127.0.0.1:9000/v1",
                                                     "model": "whisper", "api_key": STT}))
    ok(c.put("/api/v1/settings/telegram", json={"bot_token": BOT, "chat_id": "-100123", "topics": {"fisica": 4},
                                                "misc_topic_id": 9}))
    pricing = {"openrouter": {"vendor/fase-0": {"input_per_million": 0.5, "output_per_million": 1.5}}}
    ok(c.put("/api/v1/settings/pricing", json=pricing))
    secret_var = ok(c.get("/api/v1/settings"))["credentials"][-1]["env_var"]
    ok(c.put(f"/api/v1/secrets/{secret_var}", json={"value": KEY + "-ruotata"}))

    data = reread(api_token, "/settings", "/settings/routes/rewrite/secondary",
                  drop_env=(secret_var, "RT_STT_API_KEY", "RT_TELEGRAM_BOT_TOKEN"))
    snap = data["/settings"]
    assert {p["job"]: (p["connection"], p["model"]) for p in snap["phases"]} == {
        job: ("Casa", f"vendor/fase-{n}") for n, job in enumerate(jobs)}
    conn = next(x for x in snap["connections"] if x["name"] == "Casa")
    assert "vendor/extra" in conn["models"] and all(x["set"] for x in conn["credentials"])
    assert data["/settings/routes/rewrite/secondary"]["model"] == "vendor/secondaria"
    assert snap["lessons_root"] == str(new_root.resolve())
    assert snap["transcription"] == {"engine": "custom", "base_url": "http://127.0.0.1:9000/v1",
                                     "model": "whisper", "api_key_set": True}
    assert snap["telegram"]["bot_token_set"] is True
    assert (snap["telegram"]["chat_id"], snap["telegram"]["topics"], snap["telegram"]["misc_topic_id"]) == (
        "-100123", {"FISICA": 4}, 9)
    assert snap["pricing"] == pricing
    assert next(x for x in snap["credentials"] if x["env_var"] == secret_var)["set"] is True
    assert KEY not in json.dumps(data) and BOT not in json.dumps(data) and STT not in json.dumps(data)


# ---------------------------------------------------------------- sessione del browser

def test_browser_session_persists_and_logout_revokes(api_client, api_token, ws):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    from rt.db.engine import reset_database_cache
    login = TestClient(create_app())
    ok(login.post("/api/v1/auth/session", json={"token": api_token}))
    cookies = dict(login.cookies)
    reset_database_cache()
    again = TestClient(create_app(), cookies=cookies)  # app e connessione nuove
    assert again.get("/api/v1/auth/me").status_code == 200
    headers = {"X-CSRF-Token": cookies["rt_csrf"]}
    assert again.delete("/api/v1/auth/session", headers=headers).status_code in (200, 204)
    reset_database_cache()
    after = TestClient(create_app(), cookies=cookies)
    assert after.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------- lezioni, job, decisioni

def test_job_writes_persist(api_client, api_token, ws, worker, tmp_path):
    c = api_client
    with open(AUDIO_FIXTURE, "rb") as f:
        ingest = ok(c.post("/api/v1/lessons", files={"audio": ("lezione.wav", f, "audio/wav")},
                           data={"date": "2026-09-05", "materia": "BIOCHIMICA", "argomenti": "Lipidi", "mock": "true"}))
    drain(worker)
    lid = lesson_id(c)
    run = ok(c.post(f"/api/v1/lessons/{lid}/jobs", json={"type": "run_pipeline", "mock": True, "rename": False}))
    phase = ok(c.post(f"/api/v1/lessons/{lid}/jobs", json={"type": "run_phase", "phase": "prepare", "mock": True}))
    cancelled = ok(c.post(f"/api/v1/lessons/{lid}/jobs", json={"type": "run_phase", "phase": "outline", "mock": True}))
    ok(c.post(f"/api/v1/jobs/{cancelled['job_id']}/cancel"))
    cred = ok(c.post("/api/v1/settings/test-credential", json={"credential": "x", "model": "m", "mock": True}))

    data = reread(api_token, "/lessons", f"/lessons/{lid}", *(f"/jobs/{j['job_id']}" for j in
                                                              (ingest, run, phase, cancelled, cred)))
    assert data["/lessons"][0]["folder_name"] == "[2026-09-05] BIOCHIMICA - Lipidi"
    assert data[f"/jobs/{ingest['job_id']}"]["state"] == "succeeded"
    assert data[f"/jobs/{run['job_id']}"]["type"] == "run_pipeline"
    assert data[f"/jobs/{phase['job_id']}"]["payload"]["phase"] == "prepare"
    assert data[f"/jobs/{cancelled['job_id']}"]["state"] == "cancelled"
    assert data[f"/jobs/{cred['job_id']}"]["type"] == "credential_test"


def test_images_job_persists(api_client, api_token, ws, worker, tmp_path):
    from PIL import Image
    lesson_dir = make_lesson(ws)
    run_mock_pipeline(lesson_dir)
    lid = lesson_id(api_client)
    path = tmp_path / "slide.png"
    Image.new("RGB", (32, 32), (0, 90, 200)).save(path, format="PNG")
    with open(path, "rb") as f:
        job = ok(api_client.post(f"/api/v1/lessons/{lid}/images", files={"files": ("slide.png", f, "image/png")},
                                 data={"mock": "true"}))
    drain(worker)
    result = api_client.get(f"/api/v1/jobs/{job['job_id']}").json()["result"]
    data = reread(api_token, f"/jobs/{job['job_id']}")
    assert data[f"/jobs/{job['job_id']}"]["state"] == "succeeded"
    assert data[f"/jobs/{job['job_id']}"]["result"] == result
    assert os.listdir(os.path.join(lesson_dir, "assets", "images"))


def test_outline_and_review_decisions_persist(api_client, api_token, ws, worker):
    c = api_client
    lesson_dir = make_lesson(ws)
    lid = lesson_id(c)
    run = ok(c.post(f"/api/v1/lessons/{lid}/jobs", json={"type": "run_pipeline", "mock": True, "rename": False}))
    drain(worker)
    revise = ok(c.post(f"/api/v1/lessons/{lid}/outline/revise", json={"feedback": "Dividi in due unità", "mock": True}))
    drain(worker)
    ok(c.post(f"/api/v1/lessons/{lid}/outline/approve"))
    drain(worker)
    assert c.get(f"/api/v1/jobs/{run['job_id']}").json()["decision"]["kind"] == "science_issue"
    items = c.get(f"/api/v1/lessons/{lid}/issues").json()["items"]
    assert len(items) >= 2
    first, rest = items[0]["issue"], [i["issue"] for i in items[1:]]
    ok(c.post(f"/api/v1/lessons/{lid}/issues/{first['id']}/decision", json={"decision": "rejected"}))
    ok(c.post(f"/api/v1/lessons/{lid}/decisions/undo", json={"issue_id": first["id"]}))
    ok(c.post(f"/api/v1/lessons/{lid}/issues/{first['id']}/decision", json={"decision": "accepted"}))
    ok(c.post(f"/api/v1/lessons/{lid}/issues/{rest[0]['id']}/decision", json={"decision": "rejected"}))

    data = reread(api_token, f"/lessons/{lid}/outline", f"/lessons/{lid}/decisions",
                  f"/lessons/{lid}/issues?status=all", f"/jobs/{revise['job_id']}")
    assert data[f"/lessons/{lid}/outline"]["approved"] is True
    assert data[f"/jobs/{revise['job_id']}"]["state"] == "succeeded"
    decided = {d["issue_id"]: (d["decision"], d["channel"]) for d in data[f"/lessons/{lid}/decisions"]}
    assert decided[first["id"]] == ("accepted", "api") and decided[rest[0]["id"]] == ("rejected", "api")
    assert os.path.isdir(lesson_dir)


# ---------------------------------------------------------------- recall

def test_recall_writes_persist(api_client, api_token, ws, worker):
    c = api_client
    run_mock_pipeline(make_lesson(ws))
    lid = lesson_id(c)
    ok(c.post(f"/api/v1/lessons/{lid}/recall/generate", json={"mock": True}))
    ok(c.post(f"/api/v1/lessons/{lid}/recall/generate", json={"qtype": "vasta", "count": 2, "mock": True}))
    drain(worker)
    quiz = ok(c.post(f"/api/v1/lessons/{lid}/recall/next?qtype=quiz"))
    ok(c.post(f"/api/v1/lessons/{lid}/recall/answer", json={"question_id": quiz["id"], "choice": 1}))
    ok(c.post(f"/api/v1/lessons/{lid}/recall/vote", json={"question_id": quiz["id"], "vote": "up"}))
    skipped = ok(c.post(f"/api/v1/lessons/{lid}/recall/next?qtype=quiz"))
    ok(c.post(f"/api/v1/lessons/{lid}/recall/skip", json={"question_id": skipped["id"]}))
    open_q = ok(c.post(f"/api/v1/lessons/{lid}/recall/next?qtype=mirata"))
    ok(c.post(f"/api/v1/lessons/{lid}/recall/answer", json={"question_id": open_q["id"], "answer": "Risposta.",
                                                             "mock": True}))
    voice_q = ok(c.post(f"/api/v1/lessons/{lid}/recall/next?qtype=vasta"))
    with open(AUDIO_FIXTURE, "rb") as f:
        voice = ok(c.post(f"/api/v1/lessons/{lid}/recall/answer-voice", files={"audio": ("r.wav", f, "audio/wav")},
                          data={"question_id": voice_q["id"], "mock": "true"}))
    drain(worker)

    data = reread(api_token, f"/lessons/{lid}/recall", f"/lessons/{lid}/recall/history", f"/jobs/{voice['job_id']}")
    history = data[f"/lessons/{lid}/recall/history"]
    by_id = {q["id"]: q for q in history["questions"]}
    answers = {a["question_id"]: a for a in history["answers"]}
    assert by_id[quiz["id"]]["status"] == "answered" and by_id[quiz["id"]]["correct_index"] is not None
    assert answers[quiz["id"]]["answer_text"] == quiz["options"][1] and answers[quiz["id"]]["vote"] == "up"
    assert by_id[skipped["id"]]["status"] == "pending"
    assert answers[open_q["id"]]["answer_text"] == "Risposta." and answers[open_q["id"]]["evaluation"]
    assert data[f"/lessons/{lid}/recall"]["questions"]["vasta"]
    assert data[f"/jobs/{voice['job_id']}"]["type"] == "recall_evaluate"
