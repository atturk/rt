"""
rt.core.models
Schemi dati Pydantic per il workflow accademico RT.
Tutti i contratti tra codice deterministico, LLM e ledger umano sono definiti qui.
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from rt.core.timestamp import format_timestamp


class Segment(BaseModel):
    id: str = Field(..., description="ID univoco e stabile (es. seg_000001)")
    index: int = Field(..., ge=1, description="Indice progressivo a partire da 1")
    start_seconds: float = Field(..., ge=0.0, description="Timestamp iniziale in secondi")
    end_seconds: float = Field(..., gt=0.0, description="Timestamp finale in secondi")
    start_formatted: str = Field(..., description="Formato MM:SS o H:MM:SS")
    end_formatted: str = Field(..., description="Formato MM:SS o H:MM:SS")
    text_raw: str = Field(..., description="Trascrizione ASR grezza immutata")
    source_file: Optional[str] = None
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    flags: List[str] = Field(default_factory=list)

    @field_validator("end_seconds")
    @classmethod
    def validate_end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_seconds")
        if start is not None and v <= start:
            raise ValueError(f"end_seconds ({v}) deve essere strettamente maggiore di start_seconds ({start})")
        return v

    @model_validator(mode="after")
    def validate_cross_field_consistency(self) -> "Segment":
        expected_id = f"seg_{self.index:06d}"
        if self.id != expected_id:
            raise ValueError(
                f"Segment incoerente: id='{self.id}' non corrisponde all'index={self.index} "
                f"(atteso '{expected_id}')"
            )
        expected_start_fmt = format_timestamp(self.start_seconds)
        if self.start_formatted != expected_start_fmt:
            raise ValueError(
                f"Segment incoerente: start_formatted='{self.start_formatted}' non corrisponde a "
                f"start_seconds={self.start_seconds} (atteso '{expected_start_fmt}')"
            )
        expected_end_fmt = format_timestamp(self.end_seconds)
        if self.end_formatted != expected_end_fmt:
            raise ValueError(
                f"Segment incoerente: end_formatted='{self.end_formatted}' non corrisponde a "
                f"end_seconds={self.end_seconds} (atteso '{expected_end_fmt}')"
            )
        return self


class SegmentsData(BaseModel):
    schema_version: str = "1.0"
    lesson_id: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    segments: List[Segment] = Field(default_factory=list)


# ---------------------------------------------------------
# OUTLINE
# ---------------------------------------------------------

class OutlineUnit(BaseModel):
    id: str = Field(..., description="Identificativo gerarchico (es. '1.1', '5.2')")
    title: str = Field(..., min_length=1, description="Titolo concettuale dell'unità didattica")
    start_segment_id: str = Field(..., description="ID del primo segmento ASR dell'unità")
    end_segment_id: str = Field(..., description="ID dell'ultimo segmento ASR dell'unità")
    key_concepts: List[str] = Field(default_factory=list, description="Concetti chiave didattici")


class OutlineMacro(BaseModel):
    id: str = Field(..., description="Identificativo macro capitolo (es. '1', '5')")
    title: str = Field(..., min_length=1, description="Titolo della macro sezione")
    units: List[OutlineUnit] = Field(..., min_length=1, description="Unità didattiche costituenti")


class Outline(BaseModel):
    schema_version: str = "1.0"
    lesson_title: str = Field(..., min_length=1, description="Titolo formale accademico della lezione")
    macro_sections: List[OutlineMacro] = Field(..., min_length=1, description="Elenco macro capitoli")


# ---------------------------------------------------------
# DRAFT & REWRITE PROVENANCE
# ---------------------------------------------------------

class DraftUnit(BaseModel):
    unit_id: str = Field(..., description="ID corrispondente all'OutlineUnit (es. '5.1')")
    title: str = Field(..., min_length=1)
    start_segment_id: str = Field(..., description="ID segmento iniziale")
    end_segment_id: str = Field(..., description="ID segmento finale")
    source_segment_ids: List[str] = Field(..., min_length=1, description="Lista completa dei segmenti ASR sorgente da cui deriva il testo")
    content: str = Field(..., min_length=1, description="Prosa accademica rielaborata")
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class Draft(BaseModel):
    schema_version: str = "1.0"
    lesson_id: Optional[str] = None
    units: List[DraftUnit] = Field(default_factory=list)


# ---------------------------------------------------------
# ASR AMBIGUITIES & CONFIDENCE GATING
# ---------------------------------------------------------

class ASRLevel(str, Enum):
    GREEN = "GREEN"    # Correzione certa / fonetica ovvia -> auto apply con tracciamento
    YELLOW = "YELLOW"  # Plausibile ma ambigua -> coda di revisione
    RED = "RED"        # Incertezza critica o rischio scientifico -> richiesta conferma esplicita


class ASRIssue(BaseModel):
    id: str = Field(..., description="ID univoco (es. asr_000001)")
    segment_id: str = Field(..., description="ID del segmento ASR correlato")
    source_text: str = Field(..., description="Frammento ASR originale")
    candidate: str = Field(..., description="Ipotesi o correzione proposta")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Stima di plausibilità della correzione da parte del modello linguistico (non una probabilità fonetica calibrata sull'audio originale)")
    level: ASRLevel = Field(..., description="Livello di gating: GREEN, YELLOW, RED")
    reason: str = Field(..., description="Motivazione fonetica o semantica")
    status: str = Field(default="pending", description="pending | accepted | rejected | edited")


# ---------------------------------------------------------
# SCIENCE CRITIC ISSUES
# ---------------------------------------------------------

class ScienceType(str, Enum):
    ERR_DOCENTE = "ERR_DOCENTE"              # Lapsus o errore esplicito pronunciato dal docente
    ERR_RECONSTRUCTION = "ERR_RECONSTRUCTION"# Errore o allucinazione introdotta dall'LLM durante la rielaborazione
    SCIENCE_CHECK = "SCIENCE_CHECK"          # Affermazione plausibile che merita verifica scientifica o controllo fonti


class ScienceSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScienceIssue(BaseModel):
    id: str = Field(..., description="ID univoco (es. sci_000001)")
    type: ScienceType = Field(..., description="Tipo di problematica scientifica")
    severity: ScienceSeverity = Field(..., description="Gravità dell'incongruenza")
    unit_id: Optional[str] = None
    segment_id: Optional[str] = None
    claim: str = Field(..., description="Affermazione presente nel rielaborato")
    source_quote: Optional[str] = Field(None, description="Passo corrispondente dell'ASR sorgente")
    reason: str = Field(..., description="Spiegazione dell'incongruenza scientifica")
    suggested_fix: Optional[str] = Field(None, description="Proposta di correzione o chiarimento")
    diplomatic_question: Optional[str] = Field(None, description="Domanda diplomatica consigliata per chiedere chiarimenti al docente")
    status: str = Field(default="pending", description="pending | accepted | rejected | edited")


# ---------------------------------------------------------
# HUMAN DECISION LEDGER
# ---------------------------------------------------------

class ReviewDecision(BaseModel):
    issue_id: str = Field(..., description="ID dell'ASRIssue o ScienceIssue")
    decision: str = Field(..., description="accepted | rejected | edited")
    resolved_text: Optional[str] = Field(None, description="Testo finale convalidato")
    resolved_by: str = Field(default="user", description="user | auto_green")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    notes: Optional[str] = None
    original_context: Optional[str] = None


class DecisionLedger(BaseModel):
    schema_version: str = "1.0"
    decisions: List[ReviewDecision] = Field(default_factory=list)


# ---------------------------------------------------------
# TELEGRAM PENDING CONFIRMATION (outline confirm/revise loop)
# ---------------------------------------------------------

class TelegramPendingStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"


class TelegramPendingState(BaseModel):
    schema_version: str = "1.0"
    kind: str = "outline_confirmation"
    round: int = Field(..., description="Incrementa ad ogni rigenerazione dell'outline")
    short_id: str = Field(..., description="Chiave nel registry globale short_id -> lesson_dir")
    created_at: str
    status: TelegramPendingStatus = TelegramPendingStatus.PENDING
    outline_summary_text: str = Field(..., description="Testo mandato all'utente, per audit/debug")
    feedback_text: Optional[str] = None
    responded_at: Optional[str] = None
    responded_via: Optional[str] = Field(None, description="'telegram' | 'terminal'")


class IssueReviewQueueState(BaseModel):
    schema_version: str = "1.0"
    issue_ids: List[str]
    issue_types: Dict[str, str]  # issue_id -> "asr" | "science"
    current_index: int = 0


# ---------------------------------------------------------

# MANIFEST
# ---------------------------------------------------------

class Manifest(BaseModel):
    schema_version: str = "1.0"
    workflow_version: str = "2.0.0"
    lesson_id: str
    lesson_dir: str
    date: str
    subject: str
    topics: Optional[str] = None
    audio_file: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    segment_count: int = 0
    current_state: str
    created_at: str
    updated_at: str
    model_info: Dict[str, Any] = Field(default_factory=dict)
    coverage_stats: Dict[str, Any] = Field(default_factory=dict)
    phase_records: Dict[str, Any] = Field(default_factory=dict)

# ----------------------------------------------------------------------
# Recall question/answer models (Phase D1)
# ----------------------------------------------------------------------

class RecallQuestionType(str, Enum):
    QUIZ = "quiz"
    MIRATA = "mirata"
    VASTA = "vasta"

class RecallQuestionStatus(str, Enum):
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"

class RecallQuestion(BaseModel):
    id: str  # e.g., recall_000001
    type: RecallQuestionType
    unit_ids: List[str] = Field(..., min_length=1)
    question_text: str
    options: Optional[List[str]] = None  # only quiz, exactly 4
    correct_index: Optional[int] = None  # only quiz
    pregenerated_material: Optional[str] = None
    status: RecallQuestionStatus = RecallQuestionStatus.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class RecallAnswer(BaseModel):
    question_id: str
    answer_text: str
    is_voice: bool = False
    evaluation: Optional[str] = None
    vote: Optional[str] = None  # up | down | lightning
    answered_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class RecallBank(BaseModel):
    schema_version: str = "1.0"
    questions: List[RecallQuestion] = Field(default_factory=list)
    answers: List[RecallAnswer] = Field(default_factory=list)
