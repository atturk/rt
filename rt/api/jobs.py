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


def worker_available(job_type: str, payload: Optional[Dict[str, Any]] = None,
                     lesson_dir: Optional[str] = None) -> bool:
    """C'è un worker vivo che può prendere il job (se deve trascrivere, uno con la STT: RT4-G1)."""
    from rt.services.jobs import has_live_worker, job_needs_stt
    return has_live_worker(job_type, needs_stt=job_needs_stt(job_type, payload, lesson_dir))


def enqueue_job(job_type: str, lesson_dir: Optional[str], payload: Dict[str, Any],
                actor: str = "api") -> Dict[str, Any]:
    if lesson_dir:
        from rt.services.lesson_service import lesson_id_for_dir
        from rt.services.document_edit_lease import assert_editable
        lesson_id = lesson_id_for_dir(lesson_dir)
        if lesson_id is not None:
            assert_editable(lesson_id)
    return job_accepted(queue().enqueue(job_type, lesson_dir, payload, created_by=actor))


def job_accepted(job_id: str) -> Dict[str, Any]:
    """Risposta 202 per un job appena accodato."""
    from rt.services.lesson_service import lesson_id_for_dir
    info = queue().get(job_id)
    lesson_dir = info.lesson_path
    return {"job_id": job_id, "type": info.type, "state": info.state,
            "lesson_id": lesson_id_for_dir(lesson_dir) if lesson_dir and fs.isdir(lesson_dir) else None,
            "worker_available": worker_available(info.type, info.payload, lesson_dir), "retry_of": info.retry_of}


def running_jobs(lesson_dir: str):
    from rt.services.jobs import JobState
    return queue().list(state=[JobState.RUNNING.value], lesson_id=lesson_dir)


def ensure_no_running_job(lesson_dir: str) -> None:
    """409 se un job sta modificando la lezione (la decisione arriverebbe a metà lavoro)."""
    busy = running_jobs(lesson_dir)
    if busy:
        raise ApiError(409, "lesson_busy", "Un job sta lavorando su questa lezione: riprova quando ha finito.",
                       {"job_id": busy[0].id, "type": busy[0].type})
