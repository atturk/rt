"""
rt.api.jobs
Ponte tra gli endpoint e la coda dei job della fase D (rt.services.jobs): accodamento con
risposta 202, conversione in schemi, rifiuto delle scritture con un job in esecuzione sulla
lezione. La ripresa dei job in attesa dopo una decisione la fanno i servizi
(outline_service, review_service).
"""
from typing import Any, Dict, Optional

from rt.api.errors import ApiError
from rt.storage import fs


def queue():
    from rt.db.engine import DatabaseUnavailable
    from rt.services.jobs import get_job_queue
    try:
        return get_job_queue()
    except (DatabaseUnavailable, RuntimeError) as exc:
        raise ApiError(503, "database_unavailable", str(exc))


def job_view(info) -> Dict[str, Any]:
    from rt.services.lesson_service import lesson_id_for_dir
    import os
    data = info.to_dict()
    lesson_path = data.get("lesson_path")
    data["lesson_id"] = lesson_id_for_dir(lesson_path) if lesson_path and fs.isdir(lesson_path) else None
    return data


def worker_available(job_type: str) -> bool:
    from rt.services.jobs import has_live_worker
    return has_live_worker(job_type)


def enqueue_job(job_type: str, lesson_dir: Optional[str], payload: Dict[str, Any],
                actor: str = "api") -> Dict[str, Any]:
    from rt.services.lesson_service import lesson_id_for_dir
    job_id = queue().enqueue(job_type, lesson_dir, payload, created_by=actor)
    info = queue().get(job_id)
    return {"job_id": job_id, "type": job_type, "state": info.state,
            "lesson_id": lesson_id_for_dir(lesson_dir) if lesson_dir else None,
            "worker_available": worker_available(job_type)}


def running_jobs(lesson_dir: str):
    from rt.services.jobs import JobState
    return queue().list(state=[JobState.RUNNING.value], lesson_id=lesson_dir)


def ensure_no_running_job(lesson_dir: str) -> None:
    """409 se un job sta modificando la lezione (la decisione arriverebbe a metà lavoro)."""
    busy = running_jobs(lesson_dir)
    if busy:
        raise ApiError(409, "lesson_busy", "Un job sta lavorando su questa lezione: riprova quando ha finito.",
                       {"job_id": busy[0].id, "type": busy[0].type})

