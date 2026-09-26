"""
tests/test_job_retry_and_notify.py
RT4-FA1:
- 'Riprova' (POST /jobs/{id}/retry): job nuovo con lo stesso tipo e payload, collegato al vecchio
  (retry_of / retried_by), che riparte dalla fase fallita senza rifare le unità già fatte; 409 se
  la lezione è occupata o il job è già stato ripreso;
- la notifica Telegram di fine pipeline e di build singolo arriva anche dai job del worker (la
  registra l'avvio del worker, rt/services non importa rt.telegram); un errore di invio non fa
  fallire il job.
"""
import os

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import fake_telegram_server, isolated_workspace, make_lesson


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


@pytest.fixture
def worker(rt_db):
    return Worker(DbJobQueue(rt_db), worker_id="test-worker")


def drain(worker, limit=10):
    done = 0
    while worker.run_once() is not None:
        done += 1
        assert done <= limit
    return done


def job(client, job_id):
    return client.get(f"/api/v1/jobs/{job_id}").json()


def _lesson_id(api_client, ws):
    lesson_dir = make_lesson(ws)
    return api_client.get("/api/v1/lessons").json()[0]["id"], lesson_dir


def test_retry_resumes_from_failed_phase(api_client, ws, worker):
    lesson_id, lesson_dir = _lesson_id(api_client, ws)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={
        "type": "run_pipeline", "mock": True, "auto_accept": True, "rename": False, "mock_fail_once": "review"})
    assert res.status_code == 202, res.text
    first = res.json()["job_id"]
    drain(worker)
    failed = job(api_client, first)
    assert failed["state"] == "failed"
    assert failed["error"].startswith("Revisione incompleta") and "«User Safety: safe / Response Safety: safe»" in failed["error"]
    assert failed["retried_by"] is None
    phases = {p["phase"]: p for p in api_client.get(f"/api/v1/lessons/{lesson_id}/phases").json()["phases"]}
    assert phases["rewrite"]["status"] == "VALID" and phases["review"]["status"] == "PARTIAL"

    # la fase fallita vuole un job nuovo; un job non fallito non si riprova
    other = api_client.post(f"/api/v1/jobs/{first}/retry")
    assert other.status_code == 202, other.text
    body = other.json()
    assert body["retry_of"] == first and body["type"] == "run_pipeline" and body["lesson_id"] == lesson_id
    retry_id = body["job_id"]
    again = api_client.post(f"/api/v1/jobs/{first}/retry")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_retried"
    assert again.json()["error"]["details"]["job_id"] == retry_id
    assert job(api_client, first)["retried_by"] == retry_id
    assert job(api_client, retry_id)["payload"] == {**failed["payload"], "options": {**failed["payload"]["options"], "force": False}}

    drain(worker)
    done = job(api_client, retry_id)
    assert done["state"] == "succeeded", done
    assert done["retry_of"] == first
    events = api_client.get(f"/api/v1/jobs/{retry_id}/events/list").json()
    completed = {e["payload"]["phase"]: e["payload"] for e in events if e["type"] == "phase_completed"}
    # rewrite già valido: saltato; la review rifà solo l'unità mancante
    assert completed["rewrite"]["skipped"] is True
    assert completed["review"]["skipped"] is False and completed["review"]["result"]["failed_units"] == []
    progress = [e["payload"] for e in events if e["type"] == "phase_progress" and e["payload"]["phase"] == "review"]
    assert len(progress) == 1  # una sola unità (la mock ha un'unità: quella fallita)
    assert "build" in completed
    assert api_client.post(f"/api/v1/jobs/{retry_id}/retry").json()["error"]["code"] == "job_not_retryable"


def test_retry_refused_while_lesson_busy(api_client, ws, worker, rt_db):
    lesson_id, lesson_dir = _lesson_id(api_client, ws)
    first = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={
        "type": "run_phase", "phase": "prepare", "mock": True}).json()["job_id"]
    queue = DbJobQueue(rt_db)
    claimed = queue.claim("w1")
    queue.finish(claimed.id, "w1", "failed", error="finto")
    busy = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "prepare", "mock": True})
    res = api_client.post(f"/api/v1/jobs/{first}/retry")
    assert res.status_code == 409 and res.json()["error"]["code"] == "lesson_busy"
    assert res.json()["error"]["details"]["job_id"] == busy.json()["job_id"]
    assert api_client.post("/api/v1/jobs/inesistente/retry").status_code == 404


def test_mock_fail_once_needs_mock(api_client, ws):
    lesson_id, _ = _lesson_id(api_client, ws)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "mock_fail_once": "review"})
    assert res.status_code == 422


def test_failed_upload_job_keeps_files_for_retry(api_client, ws, worker, rt_db, monkeypatch):
    """Un job con upload fallito conserva i file (servono a Riprova); li pulisce il job ripreso."""
    from tests.golden_support import AUDIO_FIXTURE
    import rt.services.pipeline_service as ps
    real_ingest, calls = ps.ingest_audio, []

    def flaky_ingest(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("trascrizione non riuscita")
        return real_ingest(*args, **kwargs)
    monkeypatch.setattr(ps, "ingest_audio", flaky_ingest)
    with open(AUDIO_FIXTURE, "rb") as f:
        res = api_client.post("/api/v1/lessons", files={"audio": ("lezione.wav", f, "audio/wav")},
                              data={"date": "2026-09-05", "materia": "BIOCHIMICA", "mock": "true"})
    first = res.json()["job_id"]
    drain(worker)
    assert job(api_client, first)["state"] == "failed"
    uploads = os.path.join(ws, ".rt", "uploads")
    assert len(os.listdir(uploads)) == 1
    retry = api_client.post(f"/api/v1/jobs/{first}/retry")
    assert retry.status_code == 202, retry.text
    drain(worker)
    assert job(api_client, retry.json()["job_id"])["state"] == "succeeded"
    assert not os.listdir(uploads)


def test_sweep_stale_uploads(tmp_path, rt_db):
    import time
    from rt.services.api_jobs import sweep_stale_uploads
    queue = DbJobQueue(rt_db)
    root = tmp_path / "uploads"
    old, used, fresh = root / "old", root / "used", root / "fresh"
    for d in (old, used, fresh):
        d.mkdir(parents=True)
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    os.utime(used, (past, past))
    queue.enqueue("ingest_audio", None, {"upload_dir": str(used)})
    assert sweep_stale_uploads(str(root), queue) == 1
    assert sorted(os.listdir(root)) == ["fresh", "used"]


# ---------------------------------------------------------------- notifica Telegram dal worker


@pytest.fixture
def telegram(monkeypatch):
    from rt.services.pipeline_service import unregister_build_notifiers
    from rt.cli_jobs import prepare_worker_process
    server, base = fake_telegram_server()
    monkeypatch.setenv("RT_TELEGRAM_API_URL", base)
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:bot")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "-100123")
    yield server, prepare_worker_process
    unregister_build_notifiers()
    server.shutdown()


def _real_run_with_mock_llm(ws):
    """Run 'reale' (mock=False: niente scorciatoie di prova nella pipeline) con l'LLM mock
    da configurazione, come farebbe un utente senza chiamare i provider."""
    path = os.path.join(os.getcwd(), "config", "general.yaml")
    with open(path, "a", encoding="utf-8") as f:
        f.write("mock_llm: true\n")


def test_worker_pipeline_sends_telegram_notification(api_client, ws, worker, rt_db, telegram):
    server, prepare_worker_process = telegram
    prepare_worker_process(DbJobQueue(rt_db))
    _real_run_with_mock_llm(ws)
    lesson_id, _ = _lesson_id(api_client, ws)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "auto_accept": True, "rename": False})
    drain(worker)
    done = job(api_client, res.json()["job_id"])
    assert done["state"] == "succeeded", done
    messages = [body for method, body in server.sent if method == "sendMessage"]
    assert len(messages) == 1 and "Lezione pronta" in messages[0]["text"] and messages[0]["chat_id"] == "-100123"
    events = api_client.get(f"/api/v1/jobs/{res.json()['job_id']}/events/list").json()
    assert any(e["type"] == "notice" and "Telegram" in e["payload"]["message"] for e in events)

    # build singolo
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "build", "rename": False})
    drain(worker)
    assert job(api_client, res.json()["job_id"])["state"] == "succeeded"
    assert len([m for m, _ in server.sent if m == "sendMessage"]) == 2


def test_notification_error_does_not_fail_job(api_client, ws, worker, rt_db, telegram, monkeypatch):
    server, prepare_worker_process = telegram
    prepare_worker_process(DbJobQueue(rt_db))
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:rifiutato")
    _real_run_with_mock_llm(ws)
    lesson_id, _ = _lesson_id(api_client, ws)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "auto_accept": True, "rename": False})
    drain(worker)
    done = job(api_client, res.json()["job_id"])
    assert done["state"] == "succeeded", done
    events = api_client.get(f"/api/v1/jobs/{res.json()['job_id']}/events/list").json()
    warning = [e for e in events if e["type"] == "notice" and e["payload"].get("level") == "warning"]
    assert warning and "non inviata" in warning[-1]["payload"]["message"] and "rifiutato" not in str(warning)


def test_telegram_network_error_hides_token(monkeypatch):
    from rt.telegram.notify import TelegramBuildNotifier
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "123:segreto")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "-1")
    monkeypatch.setenv("RT_TELEGRAM_API_URL", "http://127.0.0.1:9")
    with pytest.raises(RuntimeError) as info:
        TelegramBuildNotifier().build_completed("/nessuna", {}, "Titolo")
    assert "segreto" not in str(info.value) and "[token]" in str(info.value)


def test_no_notification_without_telegram_or_in_mock(api_client, ws, worker, rt_db, telegram, monkeypatch):
    server, prepare_worker_process = telegram
    prepare_worker_process(DbJobQueue(rt_db))
    lesson_id, _ = _lesson_id(api_client, ws)
    # mock: nessuna notifica (come 'rt run --mock')
    api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "mock": True, "auto_accept": True, "rename": False})
    drain(worker)
    assert server.sent == []
    # Telegram non configurato: nessun invio, job riuscito
    monkeypatch.delenv("RT_TELEGRAM_CHAT_ID")
    _real_run_with_mock_llm(ws)
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "build", "rename": False})
    drain(worker)
    assert job(api_client, res.json()["job_id"])["state"] == "succeeded"
    assert server.sent == []


def test_retry_payload_drops_force_but_keeps_single_unit_rewrite():
    from rt.services.jobs import retry_payload
    forced = {"phase": "rewrite", "options": {"force": True, "mock": True}}
    assert retry_payload("run_phase", forced) == {"phase": "rewrite", "options": {"force": False, "mock": True}}
    assert forced["options"]["force"] is True  # il payload del job fallito non cambia
    unit = {"unit": "1.2", "options": {"force": True}}
    assert retry_payload("rewrite_unit", unit) == unit
