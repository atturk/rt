"""
tests/test_outline_service.py
RT4-A4: approvazione dell'outline come decisione (rt.services.outline_service).
"""
import json

from rt.pipeline.outline import run_outline
from rt.pipeline.prepare import run_prepare
from rt.services import outline_service
from rt.services.context import RunContext
from rt.services.pipeline_service import PipelineOptions, PipelineStatus, run_pipeline
from tests.test_integration import temp_lesson_dir  # noqa: F401  (fixture)


def _outline_ready(lesson_dir):
    run_prepare(lesson_dir)
    run_outline(lesson_dir, force_mock=True)


def test_review_tree_is_serializable(temp_lesson_dir):
    _outline_ready(temp_lesson_dir)
    tree = outline_service.get_outline_review(temp_lesson_dir)
    json.dumps(tree)
    assert tree["approved"] is False
    assert tree["macro_sections"][0]["units"][0]["id"] == "1.1"


def test_approve_is_persisted_with_actor_and_channel(temp_lesson_dir):
    _outline_ready(temp_lesson_dir)
    outline_service.approve_outline(temp_lesson_dir, actor="attilio", channel="web")
    assert outline_service.is_outline_approved(temp_lesson_dir)
    approval = outline_service.get_outline_review(temp_lesson_dir)["approval"]
    assert approval["actor"] == "attilio" and approval["channel"] == "web"


def test_revision_invalidates_approval(temp_lesson_dir, monkeypatch):
    _outline_ready(temp_lesson_dir)
    outline_service.approve_outline(temp_lesson_dir)
    # Il mock rigenera la stessa outline: simuliamo una revisione che cambia il titolo.
    from rt.pipeline import outline as outline_mod
    real = outline_mod.run_outline_revision

    def revised(lesson_dir, feedback, force_mock=False):
        res = real(lesson_dir, feedback=feedback, force_mock=force_mock)
        o = outline_mod.load_outline(lesson_dir)
        o.lesson_title = f"{o.lesson_title} ({feedback})"
        outline_mod.save_outline(o, lesson_dir)
        return res

    monkeypatch.setattr("rt.services.outline_service.run_outline_revision", revised)
    ctx = RunContext(force_mock=True)
    outline_service.request_outline_revision(temp_lesson_dir, "più dettagli", ctx=ctx)
    assert not outline_service.is_outline_approved(temp_lesson_dir)
    assert "più dettagli" in outline_service.get_outline_review(temp_lesson_dir)["lesson_title"]
    assert ctx.telemetry.get_summary()["total_requests"] == 1


def test_pipeline_resumes_after_approval(temp_lesson_dir):
    opts = PipelineOptions(mock=True, rename=False, channel="terminal")
    res = run_pipeline(temp_lesson_dir, opts, RunContext())
    assert res.status == PipelineStatus.WAITING_FOR_DECISION
    assert res.decision.payload["outline"]["lesson_title"]

    outline_service.approve_outline(temp_lesson_dir, actor="attilio", channel="api")
    res = run_pipeline(temp_lesson_dir, opts, RunContext())
    assert res.status == PipelineStatus.COMPLETED, res.error
