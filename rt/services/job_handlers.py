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
RUN_PHASE = "run_phase"
INGEST_AUDIO = "ingest_audio"
ADD_IMAGES = "add_images"
RECALL_GENERATE = "recall_generate"
TRANSCRIBE_VOICE = "transcribe_voice"


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


def _lesson_dir(job: JobInfo) -> str:
    lesson_dir = job.lesson_path or job.payload.get("lesson_dir")
    if not lesson_dir:
        raise ValueError(f"Il job {job.type} richiede una lezione")
    return lesson_dir


def run_pipeline_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.services.pipeline_service import (
        TranscriptionUnavailable, is_audio_input, run_pipeline, transcription_unavailable_reason,
    )
    from rt.storage import fs
    inputs = job.payload.get("inputs") or ([job.lesson_path] if job.lesson_path else [])
    options = pipeline_options(job.payload.get("options") or {})
    if is_audio_input(inputs) and job.lesson_path and fs.isdir(job.lesson_path):
        # Ripresa dopo una decisione (es. scaletta approvata): la lezione è già stata creata
        # dall'audio, si riparte da lì invece di rifare il setup sulla stessa cartella.
        inputs = [job.lesson_path]
    if is_audio_input(inputs):
        reason = transcription_unavailable_reason(options.mock, options.skip_transcribe)
        if reason:
            raise TranscriptionUnavailable(reason)
    return outcome_from_pipeline(run_pipeline(inputs, options, ctx))


def ingest_audio_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.services.pipeline_service import ingest_audio
    options = pipeline_options(job.payload.get("options") or {})
    return outcome_from_pipeline(ingest_audio(job.payload.get("inputs") or [], options, ctx))


def run_phase_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.services.pipeline_service import run_phase
    options = pipeline_options(job.payload.get("options") or {})
    return outcome_from_pipeline(run_phase(_lesson_dir(job), job.payload["phase"], options, ctx))


def add_images_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.pipeline.add_images import run_add_images
    p = job.payload
    with ctx.activate():
        res = run_add_images(_lesson_dir(job), input_path=p.get("input_path"),
                             web_search_count=p.get("web_search_count"), unit_ids=p.get("unit_ids"),
                             force_mock=bool(p.get("mock")))
    return JobOutcome(state=JobState.SUCCEEDED, result=json_safe(res))


def recall_generate_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.pipeline.recall import load_recall_bank
    from rt.services.recall_service import ensure_initial_batch
    lesson_dir = _lesson_dir(job)
    with ctx.activate():
        ensure_initial_batch(lesson_dir, force_mock=bool(job.payload.get("force_mock")))
    return JobOutcome(state=JobState.SUCCEEDED, result={"questions": len(load_recall_bank(lesson_dir).questions)})


def transcribe_voice_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Trascrizione di una risposta vocale (Telegram). Il file è locale: il daemon accoda
    questo job solo se c'è un worker vivo sulla stessa macchina."""
    from rt.core.recall_stt import transcribe_voice_answer
    text = transcribe_voice_answer(job.payload["path"], job.payload.get("engine") or "macparakeet")
    return JobOutcome(state=JobState.SUCCEEDED, result={"text": text})


register_handler(RUN_PIPELINE, run_pipeline_job)
register_handler(INGEST_AUDIO, ingest_audio_job)
register_handler(RUN_PHASE, run_phase_job)
register_handler(ADD_IMAGES, add_images_job)
register_handler(RECALL_GENERATE, recall_generate_job)
register_handler(TRANSCRIBE_VOICE, transcribe_voice_job)
