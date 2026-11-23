"""Test unitari Fase 3: run_collecting e fasi che raccolgono le chiamate batch differite."""
import json
from pathlib import Path

import pytest
import yaml

from rt.core.config import JobRoutingConfig, RTConfig, RouteConfig
from rt.core.idempotency import compute_file_sha256, record_phase_fingerprint
from rt.core.manifest import init_or_update_manifest, save_manifest
from rt.core.models import (
    Draft,
    DraftUnit,
    Outline,
    OutlineMacro,
    OutlineUnit,
    RecallQuestionType,
    Segment,
    SegmentsData,
)
from rt.core.state import WorkflowState
from rt.llm import deferred
from rt.llm.deferred import run_collecting, use_job_id
from rt.llm.errors import DeferredCall, DeferredPhase
from rt.llm.providers.base import NormalizedResponse
from rt.pipeline.outline import save_outline
from rt.pipeline.recall import generate_recall_batch, load_recall_bank
from rt.pipeline.review import run_review
from rt.pipeline.review_units import load_review_units
from rt.pipeline.rewrite import load_draft, run_rewrite, save_draft
from rt.services import enrichment_service
from rt.services.context import RunContext
from rt.services.events import ListReporter


def _batch_config():
    route = RouteConfig(provider="openrouter", credential="openrouter", model="openai/gpt-4o", batch=True)
    sync_route = RouteConfig(provider="openrouter", credential="openrouter", model="openai/gpt-4o", batch=False)
    return RTConfig(
        mock_llm=False,
        jobs={
            "outline": JobRoutingConfig(primary=route),
            "rewrite": JobRoutingConfig(primary=route),
            "review": JobRoutingConfig(primary=route),
            "recall": JobRoutingConfig(primary=route),
            "enrichment_writer": JobRoutingConfig(primary=route),
            "image_description": JobRoutingConfig(primary=sync_route),
        },
    )


def _seed_lesson(tmp_path: Path, state: str = WorkflowState.OUTLINE_VALIDATED.value) -> str:
    lesson_dir = tmp_path / "2026-10-10_FISIOLOGIA_Test"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "info.yaml").write_text(
        yaml.safe_dump({"data": "2026-10-10", "materia": "FISIOLOGIA", "titolo": "Test", "fase_corrente": state, "stato": state}),
        encoding="utf-8",
    )
    segs = SegmentsData(
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="Il rene filtra il sangue nei glomeruli.", confidence=0.95),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Il tubulo prossimale riassorbe acqua e glucosio.", confidence=0.95),
        ]
    )
    (lesson_dir / "segments.json").write_text(segs.model_dump_json(), encoding="utf-8")
    outline = Outline(
        schema_version="1.0",
        lesson_title="Fisiologia Renale",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Filtrazione",
                units=[OutlineUnit(id="1.1", title="Glomerulo", start_segment_id="seg_000001", end_segment_id="seg_000001", key_concepts=["filtrazione"])],
            ),
            OutlineMacro(
                id="2",
                title="Riassorbimento",
                units=[OutlineUnit(id="2.1", title="Tubulo prossimale", start_segment_id="seg_000002", end_segment_id="seg_000002", key_concepts=["riassorbimento"])],
            ),
        ],
    )
    save_outline(outline, str(lesson_dir))
    init_or_update_manifest(str(lesson_dir), lesson_dir.name, "2026-10-10", "FISIOLOGIA", "Test", state)
    record_phase_fingerprint(str(lesson_dir), "outline", "fp-o", {"outline.json": compute_file_sha256(str(lesson_dir / "outline.json"))})
    return str(lesson_dir)


def _seed_draft(lesson_dir: str) -> None:
    (Path(lesson_dir) / "info.yaml").write_text(
        yaml.safe_dump({"data": "2026-10-10", "materia": "FISIOLOGIA", "titolo": "Test", "fase_corrente": WorkflowState.DRAFT_VALIDATED.value, "stato": WorkflowState.DRAFT_VALIDATED.value}),
        encoding="utf-8",
    )
    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(unit_id="1.1", title="Glomerulo", start_segment_id="seg_000001", end_segment_id="seg_000001", source_segment_ids=["seg_000001"], content="Il rene filtra il sangue nei glomeruli renali."),
            DraftUnit(unit_id="2.1", title="Tubulo prossimale", start_segment_id="seg_000002", end_segment_id="seg_000002", source_segment_ids=["seg_000002"], content="Il tubulo prossimale riassorbe acqua e glucosio."),
        ],
    )
    save_draft(draft, lesson_dir)
    record_phase_fingerprint(lesson_dir, "rewrite", "fp-rw", {"draft.json": compute_file_sha256(str(Path(lesson_dir) / "draft.json"))})


def test_run_collecting_gathers_all_deferred_calls():
    visited = []

    def fn(x):
        visited.append(x)
        if x in (1, 3):
            raise DeferredCall(key=f"k-{x}", provider="openrouter", model="m:batch", job_id="j1")
        return x * 10

    with pytest.raises(DeferredPhase) as exc_info:
        run_collecting([1, 2, 3, 4], fn, job_id="j1", phase="test")

    assert visited == [1, 2, 3, 4]
    assert exc_info.value.keys == ["k-1", "k-3"]
    assert exc_info.value.job_id == "j1"

    # Se nessuna chiamata è differita restituisce tutti i risultati nell'ordine
    out = run_collecting([1, 2, 3], lambda x: x * 2, max_workers=2)
    assert out == [2, 4, 6]


def test_review_collects_all_units_and_completes_from_cache(rt_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _batch_config()
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.pipeline.review.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.llm.client.requests.post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No network")))

    lesson_dir = _seed_lesson(tmp_path)
    _seed_draft(lesson_dir)

    reporter = ListReporter()
    ctx = RunContext(lesson_dir=lesson_dir, reporter=reporter)
    with use_job_id("job-rev-1"):
        with pytest.raises(DeferredPhase) as exc_info:
            run_review(lesson_dir, force_mock=False, ctx=ctx)

    assert exc_info.value.phase == "review"
    pending = deferred.pending_for_job("job-rev-1")
    assert len(pending) == 2
    # Le unità differite non devono essere registrate come fallite
    assert load_review_units(lesson_dir) == {}
    assert not any(e.type == "phase_failed" for e in reporter.events)

    # Simula risposta batch completata
    deferred.mark_submitted([e.key for e in pending], "batch-rev")
    deferred.store_results("batch-rev", {
        e.key: NormalizedResponse(content='{"issues": []}', provider="openrouter", model=e.model, finish_reason="stop")
        for e in pending
    })

    with use_job_id("job-rev-1"):
        res = run_review(lesson_dir, force_mock=False, ctx=ctx)

    assert res["status"] == "review_completed"
    assert res["total_science_issues"] == 0
    assert set(load_review_units(lesson_dir)) == {"1.1", "2.1"}


def test_recall_collects_all_groups_and_completes_from_cache(rt_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _batch_config()
    cfg.recall.votes_enabled = False
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.pipeline.recall.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.llm.client.requests.post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No network")))

    lesson_dir = _seed_lesson(tmp_path)
    _seed_draft(lesson_dir)

    with use_job_id("job-rec-1"):
        with pytest.raises(DeferredPhase) as exc_info:
            generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, None, [], force_mock=False)

    assert exc_info.value.phase == "recall"
    pending = deferred.pending_for_job("job-rec-1")
    assert len(pending) == 2

    deferred.mark_submitted([e.key for e in pending], "batch-rec")
    rec_results = {}
    for e in pending:
        q_text = "Cosa filtra il glomerulo renale nel rene?" if "1.1" in json.dumps(e.request) else "Cosa riassorbe il tubulo prossimale nel rene?"
        rec_results[e.key] = NormalizedResponse(
            content=json.dumps({"questions": [{"type": "mirata", "question_text": q_text}]}),
            provider="openrouter", model=e.model, finish_reason="stop",
        )
    deferred.store_results("batch-rec", rec_results)

    with use_job_id("job-rec-1"):
        qs = generate_recall_batch(lesson_dir, RecallQuestionType.MIRATA, None, [], force_mock=False)

    assert len(qs) == 2
    assert len(load_recall_bank(lesson_dir).questions) == 2


def test_rewrite_macro_parallel_collects_both_macros(rt_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _batch_config()
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.llm.client.requests.post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No network")))

    lesson_dir = _seed_lesson(tmp_path)
    with use_job_id("job-rw-1"):
        with pytest.raises(DeferredPhase) as exc_info:
            run_rewrite(lesson_dir, force_mock=False)

    assert exc_info.value.phase == "rewrite"
    pending = deferred.pending_for_job("job-rw-1")
    assert len(pending) == 2

    deferred.mark_submitted([e.key for e in pending], "batch-rw")
    results = {}
    for e in pending:
        uid = "1.1" if "1.1" in json.dumps(e.request) else "2.1"
        seg = "seg_000001" if uid == "1.1" else "seg_000002"
        results[e.key] = NormalizedResponse(
            content=json.dumps({
                "unit_id": uid,
                "title": "Unità " + uid,
                "start_segment_id": seg,
                "end_segment_id": seg,
                "source_segment_ids": [seg],
                "content": f"Testo rielaborato per {uid}.",
            }),
            provider="openrouter", model=e.model, finish_reason="stop",
        )
    deferred.store_results("batch-rw", results)

    with use_job_id("job-rw-1"):
        res = run_rewrite(lesson_dir, force_mock=False)

    assert res["status"] == "draft_validated"
    assert len(load_draft(lesson_dir).units) == 2


def test_enrichment_analyze_collects_without_recording_errors(rt_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = _batch_config()
    monkeypatch.setattr("rt.llm.client.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.services.enrichment_service.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("rt.llm.client.requests.post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No network")))

    lesson_dir = _seed_lesson(tmp_path)
    _seed_draft(lesson_dir)

    from rt.llm.jev_client import JevNoulAnswer, JevResponse
    monkeypatch.setattr(
        "rt.services.enrichment_service.decision",
        lambda *a, **kw: JevResponse(
            model="jev",
            answers={"visualization": JevNoulAnswer(noul=0.9), "infographic": JevNoulAnswer(noul=0.1)},
        ),
    )

    with use_job_id("job-enr-1"):
        with pytest.raises(DeferredPhase) as exc_info:
            enrichment_service.analyze(lesson_dir, mock=False)

    assert exc_info.value.phase == "enrichment"
    pending = deferred.pending_for_job("job-enr-1")
    assert len(pending) == 2
    state = enrichment_service.load(lesson_dir)
    assert state.assessment_metadata == {}
