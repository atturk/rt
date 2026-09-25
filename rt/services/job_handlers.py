"""
rt.services.job_handlers
Tipi di job standard eseguiti da 'rt worker'. Ogni handler traduce il payload del job in una
chiamata ai servizi (pipeline_service, ...) e il risultato in un JobOutcome.
"""
import dataclasses
from typing import Any, Dict

from rt.services.context import RunContext
from rt.services.jobs import JobInfo, JobState, json_safe
from rt.services.worker import JobOutcome, register_handler

RUN_PIPELINE = "run_pipeline"


def pipeline_options(data: Dict[str, Any]):
    """PipelineOptions dal payload, ignorando chiavi sconosciute (payload di versioni diverse)."""
    from rt.services.pipeline_service import PipelineOptions
    names = {f.name for f in dataclasses.fields(PipelineOptions)}
    return PipelineOptions(**{k: v for k, v in (data or {}).items() if k in names})


def pipeline_payload(inputs, options) -> Dict[str, Any]:
    """Payload di un job run_pipeline da input e PipelineOptions."""
    raw = [inputs] if isinstance(inputs, str) else list(inputs)
    return {"inputs": raw, "options": dataclasses.asdict(options)}


def outcome_from_pipeline(result) -> JobOutcome:
    from rt.services.pipeline_service import PipelineStatus
    data = {"status": result.status.value, "lesson_dir": result.lesson_dir,
            "phase_results": json_safe(result.phase_results)}
    if result.status == PipelineStatus.FAILED:
        raise result.error or RuntimeError("Pipeline fallita")
    if result.status == PipelineStatus.WAITING_FOR_DECISION:
        return JobOutcome(state=JobState.WAITING_FOR_DECISION, result=data,
                          decision=result.decision.model_dump(mode="json") if result.decision else None,
                          lesson_path=result.lesson_dir)
    return JobOutcome(state=JobState.SUCCEEDED, result=data, lesson_path=result.lesson_dir)


def run_pipeline_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.services.pipeline_service import run_pipeline
    inputs = job.payload.get("inputs") or ([job.lesson_path] if job.lesson_path else [])
    result = run_pipeline(inputs, pipeline_options(job.payload.get("options") or {}), ctx)
    return outcome_from_pipeline(result)


register_handler(RUN_PIPELINE, run_pipeline_job)
