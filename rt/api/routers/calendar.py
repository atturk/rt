"""Router API per il calendario (4.2.5 CA1)."""
from datetime import date as dt_date
from typing import List, Optional

from fastapi import APIRouter, Query, Response, status

from rt.api import schemas
from rt.api.deps import Actor
from rt.services import calendar_service

router = APIRouter(tags=["calendar"])


@router.get(
    "/calendar/week",
    response_model=schemas.CalendarWeekView,
    summary="Vista settimanale del calendario (lun–ven) con stati, lezioni e riassunto",
)
def get_week_view(
    _actor: Actor,
    date: Optional[str] = Query(None, description="Data di riferimento (YYYY-MM-DD); default oggi"),
):
    target = date or dt_date.today().isoformat()
    return calendar_service.get_week_view(target)


@router.get(
    "/calendar/day",
    response_model=schemas.CalendarDayView,
    summary="Ore del giorno con stato ed eventuale lezione collegata (anche per import CA1e)",
)
def get_day_view(
    _actor: Actor,
    date: Optional[str] = Query(None, description="Data (YYYY-MM-DD); default oggi"),
):
    target = date or dt_date.today().isoformat()
    return calendar_service.get_day_view(target)


@router.get(
    "/calendar/template",
    response_model=List[schemas.CalendarTemplateEntryView],
    summary="Elenco degli slot della settimana tipo",
)
def list_template_entries(_actor: Actor):
    return calendar_service.list_template_entries()


@router.post(
    "/calendar/template",
    response_model=schemas.CalendarTemplateEntryView,
    status_code=status.HTTP_201_CREATED,
    summary="Aggiunge un'ora alla settimana tipo",
)
def create_template_entry(
    body: schemas.CalendarTemplateEntryCreate,
    _actor: Actor,
):
    return calendar_service.create_template_entry(body)


@router.delete(
    "/calendar/template/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Toglie un'ora dalla settimana tipo (da una data in poi, se indicata)",
)
def delete_template_entry(
    entry_id: int,
    _actor: Actor,
    from_date: Optional[str] = Query(
        None,
        alias="from",
        description="Da questa data (YYYY-MM-DD) l'ora non vale piu'; le settimane prima la conservano",
    ),
):
    calendar_service.delete_template_entry(entry_id, from_date=from_date)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/calendar/override",
    response_model=schemas.CalendarOverrideView,
    status_code=status.HTTP_201_CREATED,
    summary="Aggiunge o toglie un'ora solo per una settimana specifica",
)
def create_override(
    body: schemas.CalendarOverrideCreate,
    _actor: Actor,
):
    return calendar_service.create_override(body)


@router.delete(
    "/calendar/override/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimina una modifica puntuale della settimana",
)
def delete_override(
    override_id: int,
    _actor: Actor,
):
    calendar_service.delete_override(override_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/calendar/day-state",
    response_model=schemas.CalendarDayStateView,
    summary="Imposta lo stato del giorno intero (nonseguita, saltare, annullata o ripristina)",
)
def set_day_state(
    body: schemas.CalendarDayStateSet,
    _actor: Actor,
):
    return calendar_service.set_day_state(body)


@router.post(
    "/calendar/entry-state",
    response_model=schemas.CalendarEntryStateView,
    summary="Imposta lo stato di una singola ora (seguire, seguita, nonseguita, saltare, annullata) e/o note",
)
def set_entry_state(
    body: schemas.CalendarEntryStateSet,
    _actor: Actor,
):
    return calendar_service.set_entry_state(body)


@router.post(
    "/calendar/link-lesson",
    response_model=schemas.CalendarEntryStateView,
    summary="Collega (o scollega) a mano una lezione a un'ora del calendario",
)
def link_lesson(
    body: schemas.CalendarLinkLessonRequest,
    _actor: Actor,
):
    return calendar_service.link_lesson(body)
