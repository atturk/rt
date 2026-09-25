"""
rt.api.schemas
Schemi Pydantic delle risposte e delle richieste dell'API (compaiono nell'OpenAPI e da lì nel
client generato della SPA).
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class LessonSummary(BaseModel):
    id: int
    folder_name: str
    path: str
    data: str = ""
    materia: str = ""
    titolo: str = ""
    argomenti: str = ""
    state: Optional[str] = Field(None, description="Stato effettivo del workflow (come 'rt status')")
    phases: Dict[str, str] = Field(description="fase -> VALID | PARTIAL | STALE | MISSING | INVALID")
    pending_issues: int = 0
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class PhaseState(BaseModel):
    phase: str
    status: str
    reason: str


class LessonDetail(LessonSummary):
    phase_report: List[PhaseState]
    segment_count: int = 0
    outline_approved: bool = False
    has_audio: bool = False
    cost: Optional[Dict[str, Any]] = Field(None, description="Stesso report di 'rt cost --json'")


class PhaseReport(BaseModel):
    phases: List[PhaseState]
    outline_validation: Optional[Dict[str, Any]] = Field(None, description="Come 'rt validate-outline'")
    draft_validation: Optional[Dict[str, Any]] = Field(None, description="Come 'rt validate-draft'")
    validation_error: Optional[str] = None


class DocumentSection(BaseModel):
    unit_id: str
    title: str
    start_segment_id: str
    end_segment_id: str
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    start_formatted: Optional[str] = None


class LessonDocument(BaseModel):
    final: bool = Field(description="True se è il documento di 'rt build', False se anteprima dal draft")
    markdown: str
    html: str = Field(description="HTML sanificato (l'HTML grezzo del Markdown è escapato)")
    sections: List[DocumentSection] = Field(description="Timecode per unità, da segments.json")


class OutlineUnit(BaseModel):
    id: str
    title: str
    key_concepts: List[str] = []
    start_segment_id: str
    end_segment_id: str


class OutlineMacro(BaseModel):
    id: str
    title: str
    units: List[OutlineUnit]


class Outline(BaseModel):
    lesson_title: str
    macro_sections: List[OutlineMacro]
    approval: Optional[Dict[str, Any]] = None
    approved: bool


class IssueContext(BaseModel):
    timecode: str
    unit_info: Optional[str] = None
    unit_content: Optional[str] = None
    start_segment_id: Optional[str] = None
    end_segment_id: Optional[str] = None
    start_s: Optional[float] = None
    end_s: Optional[float] = None


class Decision(BaseModel):
    issue_id: str
    decision: str
    resolved_text: Optional[str] = None
    resolved_by: str = "user"
    timestamp: str
    notes: Optional[str] = None
    channel: Optional[str] = None
    actor: Optional[str] = None


class IssueItem(BaseModel):
    issue: Dict[str, Any] = Field(description="ScienceIssue (science_issues.json)")
    context: Optional[IssueContext] = None
    decision: Optional[Decision] = None


class IssueList(BaseModel):
    pending: int
    total: int
    review_complete: bool
    items: List[IssueItem]


class JobCost(BaseModel):
    cost_usd: float
    calls: int


class LessonCost(BaseModel):
    id: int
    folder_name: str
    cost_usd: float
    calls: int
    has_unknown_cost: bool = False


class CostSummary(BaseModel):
    total_cost_usd: float
    total_calls: int
    by_job: Dict[str, JobCost]
    lessons: List[LessonCost]


# ---------------------------------------------------------------- scritture

class OutlineRevision(BaseModel):
    feedback: str = Field(min_length=1, description="Cosa cambiare nell'outline")
    mock: bool = False


class DecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected", "edited"]
    text: Optional[str] = Field(None, description="Testo corretto (obbligatorio per 'edited')")
    notes: Optional[str] = None


class UndoRequest(BaseModel):
    issue_id: str


class Message(BaseModel):
    message: str
