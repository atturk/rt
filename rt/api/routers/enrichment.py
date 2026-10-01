"""Recommendations, explicitly queued generation, and protected isolated assets."""
import os
import re
from typing import Literal, Optional

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.api.jobs import enqueue_job, job_accepted, queue
from rt.api.schemas import JobAccepted
from rt.core.config import EnrichmentConfig
from rt.services import enrichment_service as service
from rt.services.review_service import lesson_lock
from rt.storage import fs

router = APIRouter(tags=["arricchimento"])


class Unit(BaseModel):
    id: str
    title: str


class EnrichmentView(BaseModel):
    cap: service.Cap
    effective_limit: Optional[int]
    units: list[Unit]
    elements: list[service.Element]


class ElementEdit(service.IdeaText):
    kind: service.Kind


class GenerateIn(BaseModel):
    element_id: Optional[str] = None
    unit_id: Optional[str] = None
    kind: service.Kind = "visualization"
    title: str = Field(default="Elemento grafico", min_length=1, max_length=120)
    description: str = Field(default="Generazione manuale", min_length=1, max_length=500)
    prompt: str = Field(default="", max_length=12000)
    mode: service.Mode = "interactive"
    mock: bool = False


class AnalyzeIn(BaseModel):
    mock: bool = False


class BatchIn(AnalyzeIn):
    lesson_ids: list[int] = Field(min_length=1, max_length=1000)


class BatchOut(BaseModel):
    jobs: list[JobAccepted]
    queued: int
    existing: int
    skipped: list[int]
    skipped_reasons: dict[int, str] = Field(default_factory=dict)


def _ready(lesson_dir):
    from rt.core.idempotency import PhaseStatus, check_phase_status
    if check_phase_status(lesson_dir, "rewrite")[0] != PhaseStatus.VALID:
        raise ApiError(409, "enrichment_not_ready", "Completa prima la rielaborazione della lezione.")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise ApiError(422, "invalid_enrichment", str(exc)) from exc


@router.get("/lessons/{lesson_id}/enrichment", response_model=EnrichmentView)
def enrichment(lesson_id: int, lesson_dir: LessonDir, actor: Actor):
    _ready(lesson_dir)
    # Repair queue-only states after cancellation/failure, including worker restart.
    with lesson_lock(lesson_dir):
        state = service.load(lesson_dir)
        changed = False
        for e in state.elements:
            if e.job_id and e.status in ("queued", "generating"):
                info = queue().get(e.job_id)
                if not info or info.finished:
                    e.status, e.error = "error", (info.error if info else None) or "Generazione interrotta: puoi riprovare."
                    changed = True
        if changed:
            service.save(lesson_dir, state)
    return service.view(lesson_dir)


@router.put("/lessons/{lesson_id}/enrichment/cap", response_model=EnrichmentView)
def cap(lesson_id: int, body: service.Cap, lesson_dir: LessonDir, actor: Actor):
    service.set_cap(lesson_dir, body)
    return service.view(lesson_dir)


def enqueue_analysis(lesson_dir, mock, actor):
    with lesson_lock(lesson_dir):
        existing = queue().list(state=["queued", "running"], lesson_id=lesson_dir,
                                job_type="enrichment_analyze", limit=1)
        if existing:
            return job_accepted(existing[0].id), False
        return enqueue_job("enrichment_analyze", lesson_dir, {"mock": mock}, actor=actor), True


@router.post("/lessons/{lesson_id}/enrichment/analyze", status_code=202, response_model=JobAccepted)
def analyze(lesson_id: int, body: AnalyzeIn, lesson_dir: LessonDir, actor: Actor):
    _ready(lesson_dir)
    return enqueue_analysis(lesson_dir, body.mock, actor)[0]


@router.post("/enrichment/analyze", status_code=202, response_model=BatchOut)
def batch(body: BatchIn, actor: Actor):
    from rt.services.lesson_service import resolve_lesson_dir, LessonNotFound
    jobs, skipped, reasons, count = [], [], {}, 0
    for lesson_id in dict.fromkeys(body.lesson_ids):
        try:
            path = resolve_lesson_dir(lesson_id)
            _ready(path)
            accepted, created = enqueue_analysis(path, body.mock, actor)
            jobs.append(accepted)
            count += created
        except (ApiError, LessonNotFound) as exc:
            skipped.append(lesson_id)
            reasons[lesson_id] = exc.message if isinstance(exc, ApiError) else str(exc)
    return BatchOut(jobs=jobs, queued=count, existing=len(jobs) - count, skipped=skipped, skipped_reasons=reasons)


@router.put("/lessons/{lesson_id}/enrichment/{element_id}", response_model=EnrichmentView)
def edit(lesson_id: int, element_id: str, body: ElementEdit, lesson_dir: LessonDir, actor: Actor):
    _call(service.mutate, lesson_dir, element_id, "edit", body)
    return service.view(lesson_dir)


class Action(BaseModel):
    action: Literal["dismiss", "restore", "delete"]


@router.post("/lessons/{lesson_id}/enrichment/{element_id}/action", response_model=EnrichmentView)
def action(lesson_id: int, element_id: str, body: Action, lesson_dir: LessonDir, actor: Actor):
    if body.action == "delete":
        from rt.api.jobs import ensure_no_running_job
        ensure_no_running_job(lesson_dir)
    _call(service.mutate, lesson_dir, element_id, body.action)
    return service.view(lesson_dir)


@router.post("/lessons/{lesson_id}/enrichment/generate", status_code=202, response_model=JobAccepted)
def generate(lesson_id: int, body: GenerateIn, lesson_dir: LessonDir, actor: Actor):
    _ready(lesson_dir)
    if not body.element_id:
        if not body.unit_id or not body.prompt.strip():
            raise ApiError(422, "invalid_enrichment", "Scegli una subunità e scrivi un prompt.")
        text = service.IdeaText(title=body.title, description=body.description, prompt=body.prompt,
                               mode="static" if body.kind == "infographic" else body.mode)
        element = _call(service.create_manual, lesson_dir, body.unit_id, body.kind, text)
        body.element_id = element.id
    with lesson_lock(lesson_dir):
        state = service.load(lesson_dir)
        element = _call(service.get_element, state, body.element_id)
        if element.job_id:
            previous = queue().get(element.job_id)
            if previous and not previous.finished:
                return job_accepted(previous.id)
        accepted = enqueue_job("enrichment_generate", lesson_dir,
                               {"element_id": element.id, "mock": body.mock}, actor=actor)
        element.job_id, element.status, element.error = accepted["job_id"], "queued", None
        service.save(lesson_dir, state)
        return accepted


@router.get("/lessons/{lesson_id}/assets/enrichment/{name}", response_class=Response)
def asset(lesson_id: int, name: str, lesson_dir: LessonDir, actor: Actor):
    if not re.fullmatch(r"[a-f0-9]{32}-[a-f0-9]{32}\.(png|html)", name):
        raise ApiError(404, "enrichment_asset_missing", "File inesistente")
    path = os.path.join(lesson_dir, "assets/enrichment", name)
    if not fs.isfile(path):
        raise ApiError(404, "enrichment_asset_missing", "File inesistente")
    with fs.open(path, "rb") as f:
        content = f.read()
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable"}
    if name.endswith(".html"):
        from rt.llm.enrichment_media import _CSP
        headers["Content-Security-Policy"] = _CSP + "; sandbox allow-scripts"
    return Response(content, media_type="text/html" if name.endswith(".html") else "image/png", headers=headers)


@router.get("/settings/enrichment", response_model=EnrichmentConfig)
def settings(actor: Actor):
    return service.load_config().enrichment


@router.put("/settings/enrichment", response_model=EnrichmentConfig)
def save_settings(body: EnrichmentConfig, actor: Actor):
    from pathlib import Path
    from rt.core.config import _default_project_root
    from rt.services.settings_service import general_config_path, _read_yaml, _atomic_yaml
    path = general_config_path(Path(_default_project_root()))
    data = _read_yaml(path)
    data["enrichment"] = body.model_dump()
    _atomic_yaml(path, data)
    return body
