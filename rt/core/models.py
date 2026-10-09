"""
rt.core.models
Schemi dati Pydantic per il workflow accademico RT.
Tutti i contratti tra codice deterministico, LLM e ledger umano sono definiti qui.
"""

from typing import List, Optional, Dict, Any, Literal
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
    generated_topics: Optional[List[str]] = Field(default=None, description="Argomenti generali di lezione generati automaticamente se omessi dall'utente")


class LessonTopics(BaseModel):
    argomenti: List[str] = Field(default_factory=list, description="Elenco sintetico di 3-6 argomenti principali a livello di lezione")



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
# SCIENCE CRITIC ISSUES
# ---------------------------------------------------------

class ScienceType(str, Enum):
    ERR_CONCETTUALE = "ERR_CONCETTUALE"      # Incongruenza o errore scientifico/concettuale nel rielaborato (lapsus o rewrite)
    ERR_ASR_ST = "ERR_ASR_ST"                # Segmento ASR con confidenza significativamente degradata (statistico)
    ERR_ASR_LLM = "ERR_ASR_LLM"              # Segmento ASR con confidenza degradata e sospetto confermato da LLM
    ERR_REWRITE_DRIFT = "ERR_REWRITE_DRIFT"  # Jev (System One) rileva contenuto rielaborato non supportato dai segmenti ASR grezzi, o deriva semantica significativa


class ScienceSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Anchor(BaseModel):
    """Citazione e contesto nel testo di una singola unità."""
    quote: str
    prefix: str = ""
    suffix: str = ""
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> "Anchor":
        if self.end < self.start or self.end - self.start != len(self.quote):
            raise ValueError("Posizioni incoerenti con la citazione")
        return self


class ScienceIssue(BaseModel):
    anchor: Optional[Anchor] = None
    origin: Literal["verifica", "parte", "studio"] = "verifica"
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
    anchor: Optional[Anchor] = None
    issue_id: str = Field(..., description="ID dell'ASRIssue o ScienceIssue")
    decision: str = Field(..., description="accepted | rejected | edited")
    resolved_text: Optional[str] = Field(None, description="Testo finale convalidato")
    resolved_by: str = Field(default="user", description="user | auto_green")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    notes: Optional[str] = None
    original_context: Optional[str] = None
    channel: Optional[str] = Field(None, description="cli | telegram | web | api (assente nelle decisioni storiche)")
    actor: Optional[str] = Field(None, description="Chi ha deciso (utente, auto_accept...)")


class DecisionLedger(BaseModel):
    schema_version: str = "1.0"
    decisions: List[ReviewDecision] = Field(default_factory=list)


# ---------------------------------------------------------
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
    # Domande speciali: nascono solo dove il classificatore delle unità (macro-sezioni)
    # riconosce un caso clinico o un esercizio, e hanno un "tipo" rigenerabile in varianti.
    CASO = "caso"
    ESERCIZIO = "esercizio"


SPECIAL_TYPES = (RecallQuestionType.CASO, RecallQuestionType.ESERCIZIO)

class RecallQuestionStatus(str, Enum):
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    DISCARDED = "discarded"

class RecallQuestion(BaseModel):
    id: str  # e.g., recall_000001
    type: RecallQuestionType
    unit_ids: List[str] = Field(..., min_length=1)
    question_text: str
    options: Optional[List[str]] = None  # only quiz, exactly 4
    correct_index: Optional[int] = None  # only quiz
    pregenerated_material: Optional[str] = None
    content_fingerprint: Optional[str] = None
    generation_version: Optional[str] = None
    generation_fingerprint: Optional[str] = None
    classifier_level: Optional[int] = None
    # Solo casi ed esercizi: il tipo da cui nasce la domanda e la variante (0 = dalla lezione).
    template_id: Optional[str] = None
    variant: Optional[int] = None
    status: RecallQuestionStatus = RecallQuestionStatus.PENDING
    discard_reasons: List[str] = Field(default_factory=list)
    comment: Optional[str] = None
    discarded_from: Optional[RecallQuestionStatus] = None
    regeneration_job_id: Optional[str] = None
    regenerated_from: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class GeneratedRecallQuestion(BaseModel):
    """Contratto rigoroso dell'LLM, distinto dalle banche storiche."""
    type: RecallQuestionType
    question_text: str = Field(min_length=1)
    options: Optional[List[str]] = None
    correct_index: Optional[int] = Field(default=None, strict=True)
    pregenerated_material: Optional[str] = None

    @model_validator(mode="after")
    def validate_style(self):
        if not self.question_text.strip():
            raise ValueError("Domanda vuota")
        if self.type == RecallQuestionType.QUIZ:
            options = self.options or []
            if len(options) != 4 or any(not x.strip() or len(x) > 100 for x in options):
                raise ValueError("Quiz: quattro opzioni non vuote, al massimo 100 caratteri")
            if len({x.strip().casefold() for x in options}) != 4:
                raise ValueError("Quiz: opzioni duplicate")
            if self.correct_index not in range(4) or len(self.question_text) >= 290:
                raise ValueError("Quiz: indice o lunghezza della domanda non valido")
            if not (self.pregenerated_material or "").strip():
                raise ValueError("Quiz: spiegazione obbligatoria")
        else:
            if self.options is not None or self.correct_index is not None:
                raise ValueError("Le domande aperte non hanno opzioni o indice")
            if self.type in (RecallQuestionType.MIRATA, RecallQuestionType.CASO) and self.pregenerated_material is not None:
                raise ValueError("Mirate e casi clinici non hanno materiale pregenerato")
            if self.type == RecallQuestionType.VASTA and not (self.pregenerated_material or "").strip():
                raise ValueError("Vasta: scaletta obbligatoria")
            if self.type == RecallQuestionType.ESERCIZIO and not (self.pregenerated_material or "").strip():
                raise ValueError("Esercizio: schema di risoluzione obbligatorio")
        return self


class GeneratedQuiz(GeneratedRecallQuestion):
    type: Literal[RecallQuestionType.QUIZ]


class GeneratedMirata(GeneratedRecallQuestion):
    type: Literal[RecallQuestionType.MIRATA]


class GeneratedVasta(GeneratedRecallQuestion):
    type: Literal[RecallQuestionType.VASTA]


class RecallGenerationResult(BaseModel):
    questions: List[GeneratedRecallQuestion] = Field(..., max_length=12)


class RecallQuizGenerationResult(RecallGenerationResult):
    questions: List[GeneratedQuiz] = Field(..., max_length=12)


class RecallMirataGenerationResult(RecallGenerationResult):
    questions: List[GeneratedMirata] = Field(..., max_length=12)


class RecallVastaGenerationResult(RecallGenerationResult):
    questions: List[GeneratedVasta] = Field(..., max_length=12)


class TemplateVariable(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    valore: str = Field(default="", max_length=200, description="Valore nella versione della lezione")
    intervallo: str = Field(default="", max_length=300, description="Valori plausibili per le varianti")


class SpecialTemplate(BaseModel):
    """Caso clinico o esercizio "tipo": la struttura astratta da cui si rigenerano varianti."""
    scenario: str = Field(min_length=1, max_length=4000)
    variabili: List[TemplateVariable] = Field(default_factory=list, max_length=20)
    obiettivo: str = Field(min_length=1, max_length=1500, description="Cosa verifica: comprensione, non nozioni")
    procedimento: str = Field(min_length=1, max_length=6000, description="Ragionamento o passaggi risolutivi")
    esplicito: bool = Field(default=False, description="Presentato a lezione (non solo adattabile)")


class GeneratedClinicalItem(BaseModel):
    question_text: str = Field(min_length=1, max_length=4000)
    unit_ids: List[str] = Field(default_factory=list, description="Subunità a cui si riferisce")
    tipo: SpecialTemplate


class GeneratedSpecialItem(GeneratedClinicalItem):
    pregenerated_material: str = Field(min_length=1, max_length=8000, description="Schema di risoluzione dell'esercizio")


class RecallClinicalGenerationResult(BaseModel):
    items: List[GeneratedClinicalItem] = Field(..., max_length=8)


class RecallSpecialGenerationResult(BaseModel):
    items: List[GeneratedSpecialItem] = Field(..., max_length=8)


class GeneratedClinicalVariant(BaseModel):
    question_text: str = Field(min_length=1, max_length=4000)


class GeneratedVariant(GeneratedClinicalVariant):
    pregenerated_material: str = Field(min_length=1, max_length=8000)


class VariantCheck(BaseModel):
    coerente: bool = Field(description="La soluzione proposta coincide con quella ricavata in modo indipendente")
    soluzione: str = Field(default="", max_length=8000, description="Soluzione ricavata in modo indipendente")
    problemi: str = Field(default="", max_length=2000)


class RecallTemplate(BaseModel):
    id: str  # template_000001
    kind: RecallQuestionType
    section_ids: List[str] = Field(..., min_length=1)
    unit_ids: List[str] = Field(..., min_length=1)
    tipo: SpecialTemplate
    fingerprint: Optional[str] = None
    variants: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


RecallOutcome = Literal["corretta", "parziale", "sbagliata"]


class RecallEvaluation(str):
    """Testo compatibile con CLI/bot, accompagnato dall'esito da salvare nella risposta."""
    outcome: Optional[RecallOutcome]

    def __new__(cls, text: str, outcome: Optional[RecallOutcome] = None):
        result = super().__new__(cls, text)
        result.outcome = outcome
        return result


class RecallAnswer(BaseModel):
    question_id: str
    answer_text: str
    is_voice: bool = False
    evaluation: Optional[str] = None
    outcome: Optional[RecallOutcome] = None
    vote: Optional[str] = None  # up | down | lightning
    vote_reasons: List[str] = Field(default_factory=list)
    vote_comment: Optional[str] = None
    dont_know: bool = False
    answered_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class RecallBank(BaseModel):
    schema_version: str = "1.0"
    questions: List[RecallQuestion] = Field(default_factory=list)
    answers: List[RecallAnswer] = Field(default_factory=list)
    generation_attempts: Dict[str, Any] = Field(default_factory=dict)
    # Unità scelte per il recaller: {"selected": [...], "known": [...]}; None = predefinite.
    unit_selection: Optional[Dict[str, List[str]]] = None
    # Numero dell'ultimo ID assegnato: le domande tolte dal pool non lasciano ID riusabili.
    last_question_number: int = 0
    # Casi clinici ed esercizi "tipo" della lezione (rt.pipeline.recall_special).
    templates: List[RecallTemplate] = Field(default_factory=list)
    last_template_number: int = 0
