"""Modelli di dominio e DTO per il calendario (4.2.5 CA1)."""
import datetime
import re
from typing import Annotated, List, Literal, Optional
from pydantic import AfterValidator, BaseModel, Field


def _check_date(value: str) -> str:
    datetime.date.fromisoformat(value)
    return value


def _check_time(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError("orario non valido, atteso HH:MM")
    return f"{int(match[1]):02d}:{match[2]}"


IsoDate = Annotated[str, Field(min_length=10, max_length=10, description="Data YYYY-MM-DD"), AfterValidator(_check_date)]
ClockTime = Annotated[str, Field(min_length=3, max_length=5, description="Orario HH:MM"), AfterValidator(_check_time)]
EntryStatus = Literal["seguire", "seguita", "nonseguita", "saltare", "annullata"]
DayStatus = Literal["", "nonseguita", "saltare", "annullata"]


class CalendarTemplateEntryCreate(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Lun, 1=Mar, ..., 6=Dom")
    start_time: ClockTime
    end_time: ClockTime
    materia: str = Field(min_length=1, max_length=256)
    docente: Optional[str] = Field(None, max_length=256)
    valid_from: Optional[IsoDate] = "2000-01-01"
    valid_to: Optional[IsoDate] = None


class CalendarTemplateEntryView(BaseModel):
    id: int
    valid_from: str
    valid_to: Optional[str] = None
    day_of_week: int
    start_time: str
    end_time: str
    materia: str
    docente: Optional[str] = None
    created_at: Optional[str] = None


class CalendarOverrideCreate(BaseModel):
    date: IsoDate
    action: Literal["added", "removed", "modified"]
    template_entry_id: Optional[int] = None
    start_time: Optional[ClockTime] = None
    end_time: Optional[ClockTime] = None
    materia: Optional[str] = Field(None, max_length=256)
    docente: Optional[str] = Field(None, max_length=256)


class CalendarOverrideView(BaseModel):
    id: int
    date: str
    action: str
    template_entry_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    materia: Optional[str] = None
    docente: Optional[str] = None
    created_at: Optional[str] = None


class CalendarDayStateSet(BaseModel):
    date: IsoDate
    status: DayStatus = Field("", description="nonseguita, saltare, annullata, o vuoto per normale")
    note: Optional[str] = Field(None, max_length=4000)


class CalendarDayStateView(BaseModel):
    date: str
    status: str
    note: Optional[str] = None


class CalendarEntryStateSet(BaseModel):
    date: IsoDate
    entry_key: str = Field(min_length=1, max_length=128)
    template_entry_id: Optional[int] = None
    override_id: Optional[int] = None
    status: Optional[EntryStatus] = None
    note: Optional[str] = Field(None, max_length=4000)


class CalendarEntryStateView(BaseModel):
    id: int
    date: str
    entry_key: str
    template_entry_id: Optional[int] = None
    override_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None
    lesson_id: Optional[int] = None
    manual_link: bool = False


class CalendarLinkLessonRequest(BaseModel):
    date: IsoDate
    entry_key: str = Field(min_length=1, max_length=128)
    lesson_id: Optional[int] = None
    template_entry_id: Optional[int] = None
    override_id: Optional[int] = None


class CalendarLessonSummary(BaseModel):
    id: int
    path: str
    titolo: str
    materia: str
    data: str
    ora: str
    workflow_state: Optional[str] = None
    units_learned: int = 0
    units_total: int = 0
    is_processing: bool = False


class CalendarEventView(BaseModel):
    key: str
    date: str
    day_of_week: int
    start_time: str
    end_time: str
    start_hour: float
    end_hour: float
    materia: str
    docente: Optional[str] = None
    status: str
    note: Optional[str] = None
    is_modified: bool = False
    is_recorded: bool = False
    template_entry_id: Optional[int] = None
    override_id: Optional[int] = None
    lesson: Optional[CalendarLessonSummary] = None


class CalendarDayView(BaseModel):
    date: str
    day_of_week: int
    day_name: str
    day_number: int
    month_name: str
    status: str = ""
    note: Optional[str] = None
    is_today: bool = False
    events: List[CalendarEventView] = Field(default_factory=list)
    hours: List[CalendarEventView] = Field(default_factory=list, description="Ore del giorno per popup di import (CA1e)")


class CalendarToRecoverItem(BaseModel):
    key: str
    date: str
    day_of_week: int
    day_name: str
    day_number: int
    month_number: int
    materia: str
    start_time: str
    end_time: str


class CalendarWeekSummary(BaseModel):
    hours_total: float
    recorded_count: int
    skip_count: int
    modified_hours_count: int
    to_recover: List[CalendarToRecoverItem] = Field(default_factory=list)


class CalendarWeekView(BaseModel):
    week_number: str
    start_date: str
    end_date: str
    label: str
    days: List[CalendarDayView]
    summary: CalendarWeekSummary


class CalendarDayImportHour(BaseModel):
    """Ora del giorno per il popup di importazione (CA1e)."""
    start_time: str
    end_time: str
    materia: str
    docente: Optional[str] = None
    status: str
    is_recorded: bool = False
    lesson_id: Optional[int] = None
    lesson_title: Optional[str] = None


class CalendarDayImportView(BaseModel):
    date: str
    hours: List[CalendarDayImportHour] = Field(default_factory=list)
