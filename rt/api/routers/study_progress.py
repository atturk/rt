"""Stato di studio e letture delle unità."""
from typing import Annotated

from fastapi import APIRouter, Path, Response

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.services import study_progress_service

router = APIRouter(tags=["studio"])
UnitId = Annotated[str, Path(min_length=1, max_length=64)]


@router.put("/lessons/{lesson_id}/study/units/{unit_id}", response_model=schemas.StudyProgress,
            summary="Cambia lo stato di studio di un'unità")
def set_status(lesson_id: int, unit_id: UnitId, body: schemas.StudyStatusUpdate, _dir: LessonDir, _actor: Actor):
    return study_progress_service.set_status(lesson_id, _dir, unit_id, body.status)


@router.post("/lessons/{lesson_id}/study/units/{unit_id}/read", status_code=204,
             summary="Segna l'ultima lettura di un'unità")
def mark_read(lesson_id: int, unit_id: UnitId, _dir: LessonDir, _actor: Actor):
    study_progress_service.mark_read(lesson_id, _dir, unit_id)
    return Response(status_code=204)


@router.get("/study/statuses/{status_id}/usage", response_model=schemas.StatusUsage,
            summary="Numero di unità con questo stato")
def status_usage(status_id: str, _actor: Actor):
    return {"count": study_progress_service.count_units_with_status(status_id)}


@router.delete("/study/statuses/{status_id}", response_model=schemas.DeleteStatusResult,
               summary="Elimina uno stato personalizzato e riporta le unità a in-apprendimento")
def delete_status(status_id: str, _actor: Actor):
    count = study_progress_service.delete_status_and_reassign(status_id)
    try:
        from pathlib import Path
        from rt.core import paths
        from rt.services.settings_service import general_config_path, _read_yaml, _atomic_yaml
        path = general_config_path(Path(paths.project_root()))
        data = _read_yaml(path)
        ui_data = data.setdefault("ui", {})
        statuses = ui_data.get("study_statuses", [])
        ui_data["study_statuses"] = [s for s in statuses if isinstance(s, dict) and s.get("id") != status_id]
        order = ui_data.get("study_status_order", [])
        ui_data["study_status_order"] = [x for x in order if x != status_id]
        _atomic_yaml(path, data)
    except Exception:
        pass
    return {"reassigned": count}
