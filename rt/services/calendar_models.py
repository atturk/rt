"""Modelli di dominio e DTO per il calendario (4.2.5 CA1)."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class CalendarTemplateEntryCreate(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Lun, 1=Mar, ..., 6=Dom")
    start_time: str = Field(min_length=3, max_length=8, description="Orario di inizio, es. 09:30")
    end_time: str = Field(min_length=3, max_length=8, description="Orario di fine, es. 11:30")
    materia: str = Field(min_length=1, max_length=256)
    docente: Optional[str] = Field(None, max_length=256)
    valid_from: Optional[str] = Field("2000-01-01", max_length=10, description="Data di inizio validità YYYY-MM-DD")


class CalendarTemplateEntryView(BaseModel):
    id: int
    valid_from: str
    day_of_week: int
    start_time: str
    end_time: str
    materia: str
    docente: Optional[str] = None
    created_at: Optional[str] = None


class CalendarOverrideCreate(BaseModel):
    date: str = Field(min_length=10, max_length=10, description="Data YYYY-MM-DD")
    action: Literal["added", "removed", "modified"]
    template_entry_id: Optional[int] = None
    start_time: Optional[str] = Field(None, max_length=8)
    end_time: Optional[str] = Field(None, max_length=8)
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
    date: str = Field(min_length=10, max_length=10, description="Data YYYY-MM-DD")
    status: str = Field("", description="nonseguita, saltare, annullata, o vuoto per normale")
    note: Optional[str] = None


class CalendarDayStateView(BaseModel):
    date: str
    status: str
    note: Optional[str] = None


class CalendarEntryStateSet(BaseModel):
    date: str = Field(min_length=10, max_length=10, description="Data YYYY-MM-DD")
    entry_key: str = Field(min_length=1, max_length=128)
    template_entry_id: Optional[int] = None
    override_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


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
    date: str = Field(min_length=10, max_length=10)
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
