"""
tests/test_job_cancel_fast.py
Annullamento immediato dei job (report del 1° ottobre) e avanzamento della generazione delle
domande:

- il token chiama subito chi ha registrato un'interruzione (anche se registrato dopo);
- una chiamata LLM in streaming si chiude appena la run viene annullata, senza aspettare la
  risposta: il client solleva RunCancelled e non prova altre route;
- il worker vede l'annullamento chiesto dall'app in pochi secondi anche con un lease lungo;
- la generazione delle domande racconta ogni unità e si ferma prima della successiva.
"""
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import BaseModel

from rt.core.config import JobRoutingConfig, RouteConfig
from rt.core.models import RecallMirataGenerationResult, RecallQuestionType
from rt.llm.cancel import RunCancelled, use_cancel_token
from rt.llm.client import LLMClient
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.pipeline import recall
from rt.services.context import CancelToken
from rt.services.jobs import DbJobQueue, JobState
from rt.services.worker import JobOutcome, Worker
from tests.test_jev_prefilter import setup_mock_lesson


class Summary(BaseModel):
    summary: str


def test_cancel_token_runs_callbacks_once_and_late_registrations_immediately():
    token = CancelToken()
    calls = []
    remove = token.on_cancel(lambda: calls.append("a"))
    token.on_cancel(lambda: calls.append("b"))
    remove()
    token.cancel()
    token.cancel()
    assert calls == ["b"]
    token.on_cancel(lambda: calls.append("late"))
    assert calls == ["b", "late"]
    with pytest.raises(RunCancelled):
        token.raise_if_cancelled()


class _BlockingStream:
    """Risposta in streaming che non arriva mai finché qualcuno non la chiude."""

    status_code = 200
    encoding = "utf-8"
    headers = {}

    def __init__(self):
        self.closed = threading.Event()

    def iter_lines(self, decode_unicode=False):
        yield b": OPENROUTER PROCESSING"
        if not self.closed.wait(30):
            raise AssertionError("lo stream non è stato chiuso")
        raise requests.exceptions.ConnectionError("connessione chiusa")

    def close(self):
        self.closed.set()


def test_streaming_call_stops_as_soon_as_the_run_is_cancelled(monkeypatch):
    monkeypatch.setattr("rt.core.config.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-12345")
    GLOBAL_CREDENTIALS.reload_from_env()
    client = LLMClient(force_mock=False)
    route = RouteConfig(route_id="r1", provider="openrouter", credential="openrouter", model="m/a",
                        thinking=False, timeout_seconds=300)
    client.config.jobs["recall"] = JobRoutingConfig(max_attempts=3, primary=route,
                                                    fallbacks=[route.model_copy(update={"route_id": "r2", "model": "m/b"})])
    streams = []

    def post(*args, **kwargs):
        streams.append(_BlockingStream())
        return streams[-1]

    token = CancelToken()
    outcome = {}

    def run():
        with use_cancel_token(token):
            try:
                client.call_structured(prompt="p", system_prompt="s", response_model=Summary, job_name="recall",
                                       show_monitor=False, stream=True)
            except BaseException as exc:  # noqa: BLE001
                outcome["error"] = exc

    with patch("requests.post", side_effect=post):
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 10
        while not streams and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        token.cancel()
        thread.join(10)
    assert not thread.is_alive()
    assert time.monotonic() - started < 5
    assert isinstance(outcome.get("error"), RunCancelled)
    assert len(streams) == 1 and streams[0].closed.is_set()  # nessuna route di riserva


def test_worker_sees_cancel_from_the_app_within_seconds(rt_db, tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)
    queue = DbJobQueue(rt_db)
    running = threading.Event()

    def slow(job, ctx):
        running.set()
        for _ in range(300):  # come una chiamata lunga che controlla solo il token
            if ctx.cancel_token.cancelled:
                ctx.check_cancelled()
            time.sleep(0.05)
        return JobOutcome(state=JobState.SUCCEEDED)

    job_id = queue.enqueue("slow_job", None, {})
    worker = Worker(queue, handlers={"slow_job": slow}, lease_seconds=600, poll_interval=0, on_message=lambda m: None)
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    assert running.wait(10)
    started = time.monotonic()
    queue.cancel(job_id)
    thread.join(15)
    assert not thread.is_alive()
    assert time.monotonic() - started < 6
    assert queue.get(job_id).state == JobState.CANCELLED.value


def test_generation_reports_each_unit_and_stops_before_the_next(tmp_path):
    path = setup_mock_lesson(tmp_path, num_units=3)
    token = CancelToken()
    events = []

    def progress(current, total, message, **unit):
        events.append((current, total, message, unit.get("unit_id")))

    def answer(**kwargs):
        token.cancel()  # annullato mentre il recaller risponde sulla prima unità
        return RecallMirataGenerationResult.model_validate({"questions": [{"type": "mirata", "question_text": "Primo?"}]})

    with patch("rt.llm.client.LLMClient.call_structured", side_effect=answer) as call, use_cancel_token(token):
        with pytest.raises(RunCancelled):
            recall.generate_recall_batch(path, RecallQuestionType.MIRATA, None, [], regenerate=True, progress=progress)
    assert call.call_count == 1
    messages = [e[2] for e in events]
    assert any("3 unità selezionate" in m for m in messages)
    assert any(m.startswith("Mirata · unità 1.1") and "chiedo le domande" in m for m in messages)
    assert any(m.startswith("Mirata · unità 1.1") and "1 domanda nuova" in m for m in messages)
    assert not any("1.2" in m for m in messages)
    # la domanda già ricevuta resta nel pool
    assert [q.question_text for q in recall.load_recall_bank(path).questions] == ["Primo?"]
    json.dumps(events)  # gli eventi finiscono nel DB: devono essere serializzabili
