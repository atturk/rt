"""
tests/test_off_schema_responses.py
RT4-FA1: un modello che risponde fuori schema (nel test reale 'openrouter/free' ha risposto
"User Safety: safe / Response Safety: safe" invece del JSON della review).

- call_structured: la risposta non JSON è un errore ritentabile sulla stessa route (repair turn e
  poi una richiesta nuova con il promemoria del formato), poi failover sulle altre route;
- fasi a unità: il fallimento definitivo di una unità non abbatte la fase, che finisce PARTIAL con
  il motivo leggibile; rilanciarla rifà solo le unità mancanti;
- il messaggio del job dice modello, unità e inizio della risposta.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from rt.core.config import JobRoutingConfig, RouteConfig
from rt.llm.client import JSON_REMINDER, LLMClient
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.errors import SchemaFailure, describe_llm_failure, response_excerpt
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline

_ORIGINAL_CALL = LLMClient.call_structured
GUARD_TEXT = "User Safety: safe\nResponse Safety: safe"


class Item(BaseModel):
    title: str
    summary: str


def _resp(content: str, model: str = "nvidia/llama-guard"):
    resp = MagicMock()
    resp.status_code = 200
    resp.encoding = "utf-8"
    body = {"id": "req", "model": model, "choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    resp.content = json.dumps(body).encode("utf-8")
    resp.text = resp.content.decode("utf-8")
    resp.json.return_value = body
    return resp


VALID = json.dumps({"title": "Ok", "summary": "JSON valido"})


@pytest.fixture
def openrouter_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-openrouter")
    GLOBAL_CREDENTIALS.reload_from_env()
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = LLMClient(force_mock=False)
    client.config.streaming = False
    client.config.show_monitor = False
    return client


def _route(route_id, model):
    return RouteConfig(route_id=route_id, provider="openrouter", credential="openrouter", model=model)


def test_off_schema_text_is_retried_on_same_route_with_json_reminder(openrouter_client):
    client = openrouter_client
    client.config.jobs["review"] = JobRoutingConfig(max_attempts=1, primary_routes=[_route("r_free", "openrouter/free")])
    sent = []

    def post(url, **kwargs):
        sent.append(kwargs["json"]["messages"])
        return _resp(GUARD_TEXT) if len(sent) < 3 else _resp(VALID)

    with patch("requests.post", side_effect=post):
        res = client.call_structured(prompt="Rivedi", system_prompt="Sistema", response_model=Item,
                                     job_name="review", max_retries=1, stream=False, show_monitor=False)
    assert res.title == "Ok"
    # 1: risposta fuori schema; 2: repair turn nella stessa conversazione; 3: richiesta nuova
    # (senza la conversazione di riparazione) con il promemoria del formato JSON
    assert len(sent) == 3
    assert any(GUARD_TEXT in str(m.get("content")) for m in sent[1])
    assert not any(GUARD_TEXT in str(m.get("content")) for m in sent[2])
    assert JSON_REMINDER in sent[2][-1]["content"]


def test_off_schema_everywhere_fails_over_then_explains(openrouter_client):
    client = openrouter_client
    client.config.jobs["review"] = JobRoutingConfig(
        max_attempts=2, primary_routes=[_route("r_free", "openrouter/free"), _route("r_paid", "deepseek/deepseek-chat")])
    models = []

    def post(url, **kwargs):
        models.append(kwargs["json"]["model"])
        return _resp(GUARD_TEXT) if kwargs["json"]["model"] == "openrouter/free" else _resp(VALID)

    with patch("requests.post", side_effect=post):
        res = client.call_structured(prompt="Rivedi", system_prompt="Sistema", response_model=Item,
                                     job_name="review", stream=False, show_monitor=False)
    assert res.summary == "JSON valido"
    assert models[-1] == "deepseek/deepseek-chat" and models.count("openrouter/free") >= 2

    client.config.jobs["review"] = JobRoutingConfig(max_attempts=1, primary_routes=[_route("r_free", "openrouter/free")])
    with patch("requests.post", side_effect=lambda url, **kw: _resp(GUARD_TEXT)):
        with pytest.raises(SchemaFailure) as info:
            client.call_structured(prompt="Rivedi", system_prompt="Sistema", response_model=Item, job_name="review",
                                   unit_id="unit 24/31 (4.1)", stream=False, show_monitor=False)
    failure = info.value
    assert failure.response_excerpt == "User Safety: safe / Response Safety: safe"
    assert failure.unit_id == "unit 24/31 (4.1)"
    text = describe_llm_failure(failure)
    assert "openrouter/free" in text and "nvidia/llama-guard" in text and "«User Safety: safe / Response Safety: safe»" in text


def test_response_excerpt_is_short_and_single_line():
    long = "riga uno\n\n  riga due  \nriga tre\nriga quattro"
    assert response_excerpt(long) == "riga uno / riga due / riga tre"
    assert len(response_excerpt("x" * 1000)) <= 240


# ---------------------------------------------------------------- fasi a unità


def _multi_unit_outline(monkeypatch, units=4):
    """L'outline mock ha una sola unità: qui i segmenti vengono divisi in 'units' unità."""
    import re
    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    original = LLMClient._generate_mock_response

    def generate(self, job_name, prompt, response_model):
        if response_model.__name__ != "Outline":
            return original(self, job_name, prompt, response_model)
        segs = list(dict.fromkeys(re.findall(r"seg_\d{6}", prompt)))
        size = max(1, len(segs) // units)
        chunks = [segs[i:i + size] for i in range(0, len(segs), size)][:units]
        chunks[-1] = segs[segs.index(chunks[-1][0]):]
        return Outline(schema_version="1.0", lesson_title="Lezione di prova", macro_sections=[OutlineMacro(
            id="1", title="Sezione", units=[OutlineUnit(id=f"1.{i}", title=f"Unità {i}", start_segment_id=c[0],
                                                        end_segment_id=c[-1], key_concepts=["k"])
                                            for i, c in enumerate(chunks, start=1)])])
    monkeypatch.setattr(LLMClient, "_generate_mock_response", generate)


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    with monkeypatch.context() as m:
        _multi_unit_outline(m)
        result = run_mock_pipeline(lesson_dir, with_review=False)
    assert result.status.value == "completed", result.error
    assert len(_unit_ids(lesson_dir)) == 4
    return lesson_dir


def _flaky(job_name, failing_units, calls):
    """call_structured in mock, tranne le unità indicate: rispondono fuori schema."""
    original = _ORIGINAL_CALL

    def call(self, *args, **kwargs):
        unit = kwargs.get("unit_id") or ""
        if kwargs.get("job_name") == job_name:
            calls.append(unit)
            if any(f"({u}" in unit for u in failing_units):
                failure = SchemaFailure("JSON non valido in 'content'", provider="openrouter", model="openrouter/free")
                failure.response_excerpt = response_excerpt(GUARD_TEXT)
                failure.unit_id = unit
                raise failure
        return original(self, *args, **kwargs)
    return call


def _unit_ids(lesson_dir):
    from rt.pipeline.rewrite import load_draft
    return [u.unit_id for u in load_draft(lesson_dir).units]


def test_review_unit_failure_does_not_stop_the_phase_and_rerun_redoes_only_it(lesson, monkeypatch):
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.pipeline.review import run_review
    from rt.services.context import RunContext
    from rt.services.events import ListReporter, Notice, PhaseCompleted
    units = _unit_ids(lesson)
    assert len(units) >= 2
    bad = units[1]
    calls = []
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("review", [bad], calls))
    reporter = ListReporter()
    res = run_review(lesson, force_mock=True, ctx=RunContext(reporter=reporter))

    assert res["status"] == "review_partial"
    assert [f["unit_id"] for f in res["failed_units"]] == [bad]
    assert res["completed_units"] == len(units) - 1 and res["expected_units"] == len(units)
    assert len(calls) == len(units)  # tutte le unità tentate: le successive non si fermano
    message = res["failed_units"][0]["message"]
    assert "openrouter/free" in message and "User Safety: safe" in message
    status, reason = check_phase_status(lesson, "review")
    assert status == PhaseStatus.PARTIAL
    assert f"({len(units) - 1}/{len(units)} unità verificate)" in reason and bad in reason
    completed = reporter.of_type(PhaseCompleted)[-1]
    assert completed.partial is True
    assert any(bad in n.message and n.level == "warning" for n in reporter.of_type(Notice))

    # Rilancio: solo l'unità mancante, poi la fase è VALID e le note sulle unità fallite spariscono
    calls.clear()
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("review", [], calls))
    res = run_review(lesson, force_mock=True)
    assert res["status"] == "review_completed" and res["failed_units"] == []
    assert len(calls) == 1 and f"({bad}" in calls[0]
    status, reason = check_phase_status(lesson, "review")
    assert status == PhaseStatus.VALID


def test_rewrite_unit_failure_is_partial_and_resume_is_idempotent(lesson, monkeypatch):
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.pipeline.rewrite import run_rewrite
    units = _unit_ids(lesson)
    bad = units[0]
    calls = []
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("rewrite", [bad], calls))
    res = run_rewrite(lesson, force=True, force_mock=True)
    assert res["status"] == "draft_partial"
    assert [f["unit_id"] for f in res["failed_units"]] == [bad]
    assert len(calls) == len(units)
    assert bad not in _unit_ids(lesson)
    status, reason = check_phase_status(lesson, "rewrite")
    assert status == PhaseStatus.PARTIAL and bad in reason

    calls.clear()
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("rewrite", [], calls))
    res = run_rewrite(lesson, force_mock=True)
    assert res["status"] == "draft_validated" and res["processed_units"] == 1
    assert len(calls) == 1 and f"({bad}" in calls[0]
    assert check_phase_status(lesson, "rewrite")[0] == PhaseStatus.VALID


def test_consecutive_failures_stop_the_phase_early(lesson, monkeypatch):
    from rt.pipeline.review import run_review
    from rt.pipeline.unit_failures import MAX_CONSECUTIVE_FAILURES
    units = _unit_ids(lesson)
    calls = []
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("review", units, calls))
    res = run_review(lesson, force_mock=True)
    assert res["stopped_early"] is (len(units) > MAX_CONSECUTIVE_FAILURES)
    assert len(calls) == min(len(units), MAX_CONSECUTIVE_FAILURES)


def test_job_error_names_model_unit_and_response(lesson, monkeypatch, rt_db):
    """Pipeline dal worker: la review parziale ferma la run prima del build con un errore
    leggibile (niente nome di classe Python)."""
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    units = _unit_ids(lesson)
    monkeypatch.setattr(LLMClient, "call_structured", _flaky("review", [units[1]], []))
    queue = DbJobQueue(rt_db)
    job_id = queue.enqueue("run_phase", lesson, {"phase": "review", "options": {"mock": True}})
    Worker(queue, worker_id="w").run_once()
    job = queue.get(job_id)
    assert job.state == "failed"
    assert job.error.startswith("Revisione incompleta")
    assert f"Unità 2/{len(units)} ({units[1]}" in job.error
    assert "openrouter/free" in job.error and "«User Safety: safe / Response Safety: safe»" in job.error
    assert "PhaseIncomplete" not in job.error and "Riprova" in job.error
