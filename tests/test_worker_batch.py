"""Test unitari Fase 4: coda job waiting_for_provider, submit/poll/resume/fallback/cancel nel worker."""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml
from pydantic import BaseModel

from rt.core.config import JobRoutingConfig, RTConfig, RouteConfig
from rt.core.idempotency import compute_file_sha256, record_phase_fingerprint
from rt.core.manifest import init_or_update_manifest
from rt.core.models import Draft, DraftUnit, Outline, OutlineMacro, OutlineUnit, Segment, SegmentsData
from rt.core.state import WorkflowState
from rt.llm import deferred
from rt.llm.client import LLMClient
from rt.llm.errors import RateLimitFailure
from rt.llm.providers.base import BaseLLMProvider, BatchResultItem, NormalizedResponse, StreamChunk
from rt.pipeline.outline import save_outline
from rt.pipeline.review import run_review
from rt.pipeline.rewrite import save_draft
from rt.services.context import RunContext
from rt.services.jobs import DbJobQueue, JobInfo, JobState
from rt.services.worker import JobOutcome, Worker


class _FakeBatchProvider(BaseLLMProvider):
    """Provider finto in memoria per testare submit/poll/cleanup/cancel senza rete."""

    def __init__(self):
        self.submitted: List[Dict[str, Any]] = []
        self.polls: int = 0
        self.cleaned: List[str] = []
        self.cancelled: List[str] = []
        self.next_poll: Tuple[str, Optional[Dict[str, BatchResultItem]]] = ("in_progress", None)
        self.poll_exception: Optional[Exception] = None
        self.supports_cancel: bool = False

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def supports_batch(self) -> bool:
        return True

    def batch_model(self, model: str) -> str:
        return model if model.endswith(":batch") else f"{model}:batch"

    def get_endpoint(self, base_url=None) -> str:
        return "https://fake.openrouter/api/v1/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def build_payload(self, model, messages, max_tokens=None, thinking=None, reasoning_effort=None,
                      temperature=None, response_format=None, stream=True, max_thinking_tokens=None,
                      provider_routing=None, response_json_schema=None) -> Dict[str, Any]:
        return {"model": model, "messages": messages, "stream": stream}

    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        return None

    def normalize_response(self, raw_json: Dict[str, Any], model_name: str, request_id: Optional[str] = None) -> NormalizedResponse:
        msg = raw_json["choices"][0]["message"]["content"]
        return NormalizedResponse(content=msg, provider=self.name, model=model_name, finish_reason="stop", usage=raw_json.get("usage"))

    def submit_batch(self, requests_list, *, model, api_key, base_url=None, timeout=60.0) -> str:
        bid = f"batch_{len(self.submitted) + 1}"
        self.submitted.append({"batch_id": bid, "model": model, "requests": list(requests_list)})
        return bid

    def poll_batch(self, batch_id, *, api_key, base_url=None, timeout=30.0):
        self.polls += 1
        if self.poll_exception is not None:
            exc = self.poll_exception
            self.poll_exception = None
            raise exc
        return self.next_poll

    def cleanup_batch(self, batch_id, *, api_key, base_url=None, timeout=15.0) -> None:
        self.cleaned.append(batch_id)

    def cancel_batch(self, batch_id, *, api_key, base_url=None, timeout=15.0) -> bool:
        if self.supports_cancel:
            self.cancelled.append(batch_id)
            return True
        return False


def _seed_review_lesson(tmp_path: Path) -> str:
    lesson_dir = tmp_path / "2026-10-10_BIO_Batch"
    lesson_dir.mkdir(parents=True)
    state = WorkflowState.DRAFT_VALIDATED.value
    (lesson_dir / "info.yaml").write_text(
        yaml.safe_dump({"data": "2026-10-10", "materia": "BIO", "titolo": "Batch", "fase_corrente": state, "stato": state}),
        encoding="utf-8",
    )
    segs = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="La cellula ha un nucleo.", confidence=0.95),
        Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="I mitocondri producono ATP.", confidence=0.95),
    ])
    (lesson_dir / "segments.json").write_text(segs.model_dump_json(), encoding="utf-8")
    outline = Outline(
        schema_version="1.0",
        lesson_title="La Cellula",
        macro_sections=[
            OutlineMacro(id="1", title="Nucleo", units=[OutlineUnit(id="1.1", title="Nucleo", start_segment_id="seg_000001", end_segment_id="seg_000001")]),
            OutlineMacro(id="2", title="Mitocondri", units=[OutlineUnit(id="2.1", title="Mitocondri", start_segment_id="seg_000002", end_segment_id="seg_000002")]),
        ],
    )
    save_outline(outline, str(lesson_dir))
    init_or_update_manifest(str(lesson_dir), lesson_dir.name, "2026-10-10", "BIO", "Batch", state)
    record_phase_fingerprint(str(lesson_dir), "outline", "fp-o", {"outline.json": compute_file_sha256(str(lesson_dir / "outline.json"))})
    draft = Draft(schema_version="1.0", units=[
        DraftUnit(unit_id="1.1", title="Nucleo", start_segment_id="seg_000001", end_segment_id="seg_000001", source_segment_ids=["seg_000001"], content="La cellula eucariotica contiene il nucleo."),
        DraftUnit(unit_id="2.1", title="Mitocondri", start_segment_id="seg_000002", end_segment_id="seg_000002", source_segment_ids=["seg_000002"], content="I mitocondri sintetizzano ATP."),
    ])
    save_draft(draft, str(lesson_dir))
    record_phase_fingerprint(str(lesson_dir), "rewrite", "fp-rw", {"draft.json": compute_file_sha256(str(lesson_dir / "draft.json"))})
    return str(lesson_dir)


def _setup_batch_env(monkeypatch, fake_provider: _FakeBatchProvider):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    route = RouteConfig(provider="openrouter", credential="openrouter", model="openai/gpt-4o", batch=True)
    cfg = RTConfig(mock_llm=False, jobs={"review": JobRoutingConfig(primary=route), "outline": JobRoutingConfig(primary=route)})
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.pipeline.review.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.llm.client.get_provider", lambda name: fake_provider)
    monkeypatch.setattr("rt.services.worker.Worker._submit_deferred_job", Worker._submit_deferred_job)
    import rt.llm.providers
    monkeypatch.setattr(rt.llm.providers, "get_provider", lambda name: fake_provider)


def test_worker_batch_full_roundtrip_matches_sync(rt_db, tmp_path, monkeypatch):
    fake_provider = _FakeBatchProvider()
    _setup_batch_env(monkeypatch, fake_provider)
    lesson_dir = _seed_review_lesson(tmp_path)

    queue = DbJobQueue(rt_db)

    def review_handler(job: JobInfo, ctx: RunContext) -> JobOutcome:
        with ctx.activate():
            res = run_review(job.lesson_path, force_mock=False, ctx=ctx)
        return JobOutcome(state=JobState.SUCCEEDED, result=res, lesson_path=job.lesson_path)

    worker = Worker(queue, handlers={"review_test": review_handler}, stt="none")
    job_id = queue.enqueue("review_test", lesson_dir, {})

    # 1. Prima esecuzione: raccoglie le 2 unità, invia il lotto e mette il job in waiting_for_provider
    job = worker.run_once()
    assert job is not None
    assert job.state == JobState.WAITING_FOR_PROVIDER.value
    assert job.progress["message"] == "In attesa del provider (batch)"
    assert len(fake_provider.submitted) == 1
    assert len(fake_provider.submitted[0]["requests"]) == 2
    batch_id = fake_provider.submitted[0]["batch_id"]
    assert any(e.type == "job_waiting_provider" and e.payload.get("requests") == 2 for e in queue.events(job_id))

    # active_lesson deve essere liberato mentre il job attende il provider
    from rt.db.models import Job as JobModel
    from rt.db.session import read_scope
    with read_scope(rt_db) as s:
        assert s.get(JobModel, job_id).active_lesson is None

    # 2. Poll ancora in corso → nessuna ripresa
    assert worker.poll_provider_batches(now=100.0) == 0
    assert queue.get(job_id).state == JobState.WAITING_FOR_PROVIDER.value

    # 3. Poll con 429 → backoff senza errori e salta il poll successivo dentro la finestra
    fake_provider.poll_exception = RateLimitFailure("Too many requests", retry_after=30.0)
    assert worker.poll_provider_batches(now=101.0) == 0
    polls_before = fake_provider.polls
    assert worker.poll_provider_batches(now=110.0) == 0
    assert fake_provider.polls == polls_before

    # 4. Poll completato dopo il backoff → salva in cache, pulisce remoto, rimette in coda
    req_keys = [r["custom_id"] for r in fake_provider.submitted[0]["requests"]]
    fake_provider.next_poll = (
        "completed",
        {
            k: BatchResultItem(
                custom_id=k,
                response=NormalizedResponse(content='{"issues": []}', provider="openrouter", model="openai/gpt-4o:batch", finish_reason="stop"),
            )
            for k in req_keys
        },
    )
    assert worker.poll_provider_batches(now=135.0) == 1
    assert batch_id in fake_provider.cleaned
    assert queue.get(job_id).state == JobState.QUEUED.value

    # 5. Seconda esecuzione: rilegge dalla cache senza rete e completa!
    monkeypatch.setattr("rt.llm.client.requests.post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No sync HTTP")))
    finished = worker.run_once()
    assert finished is not None
    assert finished.state == JobState.SUCCEEDED.value
    assert finished.result["total_science_issues"] == 0


def test_worker_batch_expired_falls_back_to_sync(rt_db, tmp_path, monkeypatch):
    fake_provider = _FakeBatchProvider()
    _setup_batch_env(monkeypatch, fake_provider)
    queue = DbJobQueue(rt_db)

    class _Out(BaseModel):
        val: str

    def handler(job: JobInfo, ctx: RunContext) -> JobOutcome:
        with ctx.activate():
            res = LLMClient(force_mock=False).call_structured(
                prompt="Ciao", system_prompt="Sys", response_model=_Out, job_name="review", stream=False,
            )
        return JobOutcome(state=JobState.SUCCEEDED, result={"val": res.val})

    worker = Worker(queue, handlers={"batch_test": handler}, stt="none")
    job_id = queue.enqueue("batch_test", None, {})

    job = worker.run_once()
    assert job.state == JobState.WAITING_FOR_PROVIDER.value
    batch_id = fake_provider.submitted[0]["batch_id"]

    # Lotto scaduto -> resume con batch_fallback: true + evento esplicativo
    fake_provider.next_poll = ("expired", None)
    assert worker.poll_provider_batches(now=100.0) == 1
    resumed = queue.get(job_id)
    assert resumed.state == JobState.QUEUED.value
    assert resumed.payload.get("batch_fallback") is True
    assert any(
        e.type == "job_resumed" and e.payload.get("batch_fallback") is True and "expired" in (e.payload.get("reason") or "")
        for e in queue.events(job_id)
    )

    # Ora la riesecuzione usa la chiamata sincrona e non differisce
    import json as _json
    from unittest.mock import MagicMock
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    body = {"id": "sync-fb", "choices": [{"message": {"content": '{"val": "ok_sync"}'}, "finish_reason": "stop"}]}
    fake_resp.json.return_value = body
    fake_resp.content = _json.dumps(body).encode("utf-8")
    monkeypatch.setattr("rt.llm.client.requests.post", MagicMock(return_value=fake_resp))

    final_job = worker.run_once()
    assert final_job.state == JobState.SUCCEEDED.value
    assert final_job.result == {"val": "ok_sync"}
    assert deferred.open_batches(db=rt_db) == []
    assert batch_id in fake_provider.cleaned


def test_cancel_waiting_for_provider_cleans_deferred_and_calls_provider_cancel(rt_db, monkeypatch):
    fake_provider = _FakeBatchProvider()
    fake_provider.supports_cancel = True
    _setup_batch_env(monkeypatch, fake_provider)
    queue = DbJobQueue(rt_db)

    class _Out(BaseModel):
        val: str

    def handler(job: JobInfo, ctx: RunContext) -> JobOutcome:
        with ctx.activate():
            LLMClient(force_mock=False).call_structured(prompt="X", system_prompt="S", response_model=_Out, job_name="review")
        return JobOutcome(state=JobState.SUCCEEDED)

    worker = Worker(queue, handlers={"cancel_test": handler}, stt="none")
    job_id = queue.enqueue("cancel_test", None, {})
    job = worker.run_once()
    assert job.state == JobState.WAITING_FOR_PROVIDER.value
    batch_id = fake_provider.submitted[0]["batch_id"]

    cancelled = queue.cancel(job_id)
    assert cancelled.state == JobState.CANCELLED.value
    assert deferred.open_batches(db=rt_db) == []
    assert deferred.job_has_waiting_items(job_id, db=rt_db) is False
    assert batch_id in fake_provider.cancelled
