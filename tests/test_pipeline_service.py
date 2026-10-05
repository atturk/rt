"""
tests/test_pipeline_service.py
RT4-A2: orchestratore della pipeline senza terminale (rt.services.pipeline_service).
"""
import os

import pytest

from rt.services.context import RunContext
from rt.services.events import DecisionRequired, ListReporter, PhaseCompleted
from rt.services.pipeline_service import PipelineOptions, PipelineStatus, run_pipeline
from tests.test_integration import temp_lesson_dir  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _no_stdin(monkeypatch):
    def _fail(*_a, **_k):
        raise AssertionError("il servizio non deve leggere da stdin")
    monkeypatch.setattr("builtins.input", _fail)


def test_waits_for_outline_approval_without_provider(temp_lesson_dir):
    rep = ListReporter()
    res = run_pipeline(temp_lesson_dir, PipelineOptions(mock=True, channel="terminal"), RunContext(reporter=rep))
    assert res.status == PipelineStatus.WAITING_FOR_DECISION
    assert res.decision.kind == "outline_approval"
    assert rep.of_type(DecisionRequired)[0].kind == "outline_approval"
    assert [e.phase for e in rep.of_type(PhaseCompleted)] == ["prepare", "outline"]
    assert not os.path.exists(os.path.join(temp_lesson_dir, "_state", "draft.json"))


def test_completes_with_auto_accept(temp_lesson_dir):
    rep = ListReporter()
    ctx = RunContext(reporter=rep)
    opts = PipelineOptions(mock=True, with_review=True, auto_accept=True, rename=False, channel="terminal")
    res = run_pipeline(temp_lesson_dir, opts, ctx)
    assert res.status == PipelineStatus.COMPLETED, res.error
    assert [e.phase for e in rep.of_type(PhaseCompleted)] == ["prepare", "outline", "rewrite", "review", "build"]
    assert os.path.isfile(res.phase_results["build"]["rielaborato"])
    assert ctx.telemetry.get_summary()["total_requests"] == 3


def test_waits_for_science_review_without_auto_accept(temp_lesson_dir):
    class ApproveOnly:
        def approve_outline(self, lesson_dir, force, force_mock):
            self.called = True

        def review_science_issues(self, *a):
            raise AssertionError("non usato")

    provider = ApproveOnly()
    opts = PipelineOptions(mock=True, with_review=True, rename=False, channel="terminal")
    res = run_pipeline(temp_lesson_dir, opts, RunContext(), decisions=None)
    assert res.decision.kind == "outline_approval"

    res = run_pipeline(temp_lesson_dir, opts, RunContext(), decisions=provider)
    assert provider.called
    # Il provider esiste ma la review è chiesta tramite lui: qui simuliamo un worker senza
    # provider dopo l'approvazione, che si ferma sulle issue pendenti.
    assert res.status == PipelineStatus.FAILED and isinstance(res.error, AssertionError)
    res = run_pipeline(temp_lesson_dir, opts, RunContext())
    assert res.status == PipelineStatus.WAITING_FOR_DECISION
    assert res.decision.kind == "science_issue"
    assert res.decision.payload["pending"]


def test_failure_is_reported_not_exited(tmp_path):
    res = run_pipeline(str(tmp_path / "manca"), PipelineOptions(mock=True, channel="terminal"), RunContext())
    assert res.status == PipelineStatus.FAILED
    assert isinstance(res.error, FileNotFoundError)


def test_ingest_emits_lesson_created_before_setup_completes(tmp_path):
    from rt.services.events import PhaseProgress
    from rt.services.pipeline_service import ingest_audio

    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"audio")
    rep = ListReporter()
    opts = PipelineOptions(mock=True, date="2026-10-05", materia="BIOCHIMICA",
                           dest_dir=str(tmp_path / "lessons"), channel="terminal")
    result = ingest_audio(str(audio), opts, RunContext(reporter=rep))
    assert result.status == PipelineStatus.COMPLETED
    created = next(e for e in rep.events if isinstance(e, PhaseProgress) and e.lesson_dir)
    completed = next(e for e in rep.events if isinstance(e, PhaseCompleted) and e.phase == "setup")
    assert created.message == "Lezione creata"
    assert created.lesson_dir == completed.result["lesson_dir"]
    assert rep.events.index(created) < rep.events.index(completed)
