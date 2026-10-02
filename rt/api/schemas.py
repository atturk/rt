"""
rt.api.schemas
Schemi Pydantic delle risposte e delle richieste dell'API (compaiono nell'OpenAPI e da lì nel
client generato della SPA).
"""
from typing import Any, Dict, List, Literal, Optional

# Tipi di domanda; "mista" (solo per pescare la prossima domanda) li alterna tutti.
QuestionType = Literal["quiz", "mirata", "vasta", "caso", "esercizio"]
NextQuestionType = Literal["quiz", "mirata", "vasta", "caso", "esercizio", "mista"]

from pydantic import BaseModel, Field


class LessonSummary(BaseModel):
    id: int
    folder_name: str
    path: str
    data: str = ""
    materia: str = ""
    titolo: str = ""
    argomenti: str = ""
    docente: str = ""
    state: Optional[str] = Field(None, description="Stato effettivo del workflow (come 'rt status')")
    phases: Dict[str, str] = Field(description="fase -> VALID | PARTIAL | STALE | MISSING | INVALID")
    pending_issues: int = 0
    cost_usd: Optional[float] = None
    unit_count: Optional[int] = Field(None, description="Unità della scaletta (null se non c'è ancora)")
    duration_seconds: Optional[float] = Field(None, description="Durata dell'audio della lezione, se nota")
    recall_questions: int = Field(0, description="Domande di recall nel pool della lezione")
    recall_pending: int = Field(0, description="Domande del pool non ancora poste (da fare)")
    error: Optional[str] = None


class PhaseWarning(BaseModel):
    code: str = Field(description="review_missing | review_stale | review_partial | review_invalid | "
                                  "pending_issues | orphan_issues | check_failed")
    message: str = Field(description="Testo per l'utente (italiano)")
    count: Optional[int] = Field(None, description="Numero di issue, se l'avviso le conta")


class ManualValidation(BaseModel):
    at: str = Field(description="Quando è stata validata (ISO 8601, ora locale)")
    actor: Optional[str] = None
    channel: Optional[str] = Field(None, description="cli | api")
    previous_status: Optional[str] = Field(None, description="Stato della fase prima della validazione")
    previous_reason: Optional[str] = None


class PhaseState(BaseModel):
    phase: str
    status: str
    reason: str
    warnings: List[PhaseWarning] = Field(
        default_factory=list,
        description="Solo per build: avvisi di integrità della revisione (review non aggiornata o "
                    "incompleta, issue da valutare, issue orfane). Non bloccano il build: la web li "
                    "mostra nel dialogo di conferma.")
    manual_validation: Optional[ManualValidation] = Field(
        None, description="Presente se la fase è stata validata a mano (senza rieseguirla) e non "
                          "è stata più eseguita da allora")


class PhaseValidationResult(BaseModel):
    phase: str
    previous_status: str
    previous_reason: str
    status: str
    reason: str
    changed: bool = Field(description="False se la fase era già valida (nessuna modifica)")


class LessonAction(BaseModel):
    available: bool
    reason: Optional[str] = Field(None, description="Cosa manca, se non disponibile")
    preview: bool = Field(False, description="Per i download: l'export è l'anteprima dalla bozza, "
                                             "non il documento finale")


class LessonActions(BaseModel):
    recall: LessonAction
    images: LessonAction
    export_markdown: LessonAction
    export_zip: LessonAction


class LessonDetail(LessonSummary):
    phase_report: List[PhaseState]
    segment_count: int = 0
    outline_approved: bool = False
    has_audio: bool = False
    cost: Optional[Dict[str, Any]] = Field(None, description="Stesso report di 'rt cost --json'")
    actions: Optional[LessonActions] = Field(
        None, description="Recall, immagini e download: disponibili dopo il rewrite, senza build")


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
    relevance: Optional[Literal["organizational", "no_content"]] = None


class LessonDocument(BaseModel):
    final: bool = Field(description="True se è il documento di 'rt build' ed è aggiornato, False se "
                                    "anteprima dal draft (quello che il build produrrebbe ora)")
    markdown: str
    html: str = Field(description="HTML sanificato (l'HTML grezzo del Markdown è escapato)")
    sections: List[DocumentSection] = Field(description="Timecode per unità, da segments.json")


class UnitRelevanceItem(BaseModel):
    unit_id: str
    title: str
    content: str
    prediction: Optional[Literal["didactic", "organizational", "no_content"]] = None
    confidence: Optional[float] = None
    label: Optional[str] = Field(None, description="Etichetta RT assegnata dalla mappatura del classificatore")
    answer: Optional[Dict[str, Any]] = Field(None, description="Risposta completa del classificatore (scelta, confidenza, tutte le probabilità)")
    override: Optional[Literal["didactic", "organizational", "no_content"]] = None
    effective: Literal["didactic", "organizational", "no_content"]
    error: Optional[str] = None
    stale: bool = False
    corrected_at: Optional[str] = None
    corrected_by: Optional[str] = None
    prior_override: Optional[Literal["didactic", "organizational", "no_content"]] = None
    recall_assessment: Optional[Dict[str, Any]] = None


class UnitRelevanceSummary(BaseModel):
    total: int = Field(0, description="Unità della bozza")
    classified: int = Field(0, description="Unità con una classificazione valida per il testo e la configurazione attuali")
    errors: int = Field(0, description="Unità la cui classificazione non è riuscita (passano comunque)")
    stale: int = Field(0, description="Unità classificate con un testo o una configurazione diversi")
    missing: int = Field(0, description="Unità mai classificate")
    corrected: int = Field(0, description="Unità corrette dall'utente")
    excluded: int = Field(0, description="Unità la cui classe effettiva non è didattica")
    by_outcome: Dict[str, int] = Field(default_factory=dict, description="Unità classificate per classe RT")
    by_label: Dict[str, int] = Field(default_factory=dict, description="Unità classificate per etichetta del classificatore")
    last_run_at: Optional[str] = Field(None, description="Ultima classificazione valida (ISO, UTC)")
    model: Optional[str] = Field(None, description="Modello dell'ultima classificazione, se registrato")
    last_run_mode: Optional[str] = None


class UnitRelevanceOverview(BaseModel):
    view: Literal["draft", "resolved"] = "draft"
    mode: Literal["disabled", "shadow", "active"]
    units: List[UnitRelevanceItem]
    summary: UnitRelevanceSummary = Field(default_factory=UnitRelevanceSummary)


class UnitRelevanceRun(BaseModel):
    force: bool = Field(False, description="Riclassifica anche le unità già etichettate con il testo e la configurazione attuali")
    mock: bool = Field(False, description="Modalità prova: nessuna chiamata al classificatore")


class UnitRelevanceOverride(BaseModel):
    category: Optional[Literal["didactic", "organizational", "no_content"]] = None


class DocumentEditIn(BaseModel):
    markdown: str = Field(description="Markdown dell'anteprima modificato (senza frontmatter)")
    lease_token: Optional[str] = None


class DocumentEditLease(BaseModel):
    token: str
    expires: Optional[str] = Field(None, description="Scadenza (ISO, UTC) se l'editor non rinnova la sessione")
    lease_id: Optional[str] = Field(None, description="Identificativo breve della sessione di modifica")
    acquired_at: Optional[str] = Field(None, description="Inizio della sessione di modifica (ISO, UTC)")
    recovered: bool = Field(False, description="True se la richiesta ha sostituito la sessione di un'altra scheda")
    previous_lease_id: Optional[str] = None
    previous_acquired_at: Optional[str] = None


class DocumentEditProblem(BaseModel):
    line: Optional[int] = Field(None, description="Riga del Markdown (da 1), se l'errore ne ha una")
    message: str


class DocumentEditCheck(BaseModel):
    html: str = Field(description="HTML sanificato del Markdown in modifica")
    errors: List[DocumentEditProblem] = Field(description="Errori che impedirebbero il salvataggio")


class DocumentEditResult(BaseModel):
    changed: bool = Field(description="False se il Markdown era uguale all'anteprima")
    units_changed: List[str] = Field(description="Unità il cui testo è cambiato nella bozza")
    build_status: str = Field(description="Stato del documento finale dopo il salvataggio (STALE se va ricreato)")
    build_reason: str
    orphan_issues: List[str] = Field(description="Issue il cui testo non è più nella bozza")


class Waveform(BaseModel):
    ready: bool = Field(description="False mentre il calcolo è in corso: riprova tra poco")
    peaks: List[int] = Field(description="Livelli 3-72, circa 300 barre; vuoto se ffmpeg manca")


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


# ---------------------------------------------------------------- job

class Job(BaseModel):
    id: str
    type: str
    state: str = Field(description="queued | running | waiting_for_decision | succeeded | failed | cancelled")
    lesson_id: Optional[int] = None
    lesson_path: Optional[str] = None
    payload: Dict[str, Any] = {}
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = Field(None, description="Decisione attesa (DecisionRequired) se waiting_for_decision")
    attempts: int = 0
    cancel_requested: bool = False
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    retry_of: Optional[str] = Field(None, description="Job fallito di cui questo è il nuovo tentativo (Riprova)")
    retried_by: Optional[str] = Field(None, description="Job nuovo creato con Riprova da questo job fallito")


class JobAccepted(BaseModel):
    job_id: str
    type: str
    state: str
    lesson_id: Optional[int] = None
    worker_available: bool = Field(description="False se nessun 'rt worker' è attivo: il job resta in coda")
    retry_of: Optional[str] = None


class JobEvent(BaseModel):
    id: int
    job_id: str
    type: str
    payload: Dict[str, Any] = {}
    created_at: Optional[str] = None


class UploadInventoryItem(BaseModel):
    id: str
    state: Literal["active", "referenced", "orphan"]
    job_ids: List[str]
    files: int
    modified_at: str


class JobRequest(BaseModel):
    type: Literal["run_pipeline", "run_phase"] = "run_pipeline"
    phase: Optional[Literal["prepare", "outline", "rewrite", "review", "build"]] = Field(
        None, description="Obbligatoria per run_phase")
    unit: Optional[str] = Field(None, description="Rewrite o review: una sola unità")
    units: Optional[List[str]] = Field(None, description="Rewrite o review: unità selezionate (lista multipla)")
    extra_prompt: Optional[str] = Field(None, max_length=10000, description="Istruzioni aggiuntive per outline, rewrite o review")
    force: bool = False
    mock: bool = False
    with_review: bool = False
    auto_accept: bool = False
    rename: bool = True
    mock_fail_once: Optional[Literal["rewrite", "review"]] = Field(
        None, description="Solo con mock=true, per i test: la prima unità di questa fase fallisce una volta "
                          "con una risposta fuori schema (poi Riprova va a buon fine)")


class WorkerInfo(BaseModel):
    id: str
    hostname: Optional[str] = None
    pid: Optional[int] = None
    platform: Optional[str] = None
    job_types: List[str] = []
    current_job_id: Optional[str] = None


class CredentialTest(BaseModel):
    credential: str
    model: str
    provider: Optional[str] = None
    base_url: Optional[str] = None
    mock: bool = False


# ---------------------------------------------------------------- recall

class RecallQuestion(BaseModel):
    id: str
    type: str
    unit_ids: List[str]
    question_text: str
    options: Optional[List[str]] = None
    status: str
    correct_index: Optional[int] = None
    explanation: Optional[str] = None


class RecallQuestionDetail(RecallQuestion):
    created_at: Optional[str] = None
    classifier_level: Optional[int] = None
    vote: Optional[str] = Field(None, description="up | down | lightning")


class RecallQuestionList(BaseModel):
    questions: List[RecallQuestionDetail]
    unit_titles: Dict[str, str] = Field(default_factory=dict, description="unità -> titolo, per le unità delle domande")


class RecallQuestionDelete(BaseModel):
    question_ids: List[str] = Field(min_length=1, max_length=2000)


class RecallDeleted(BaseModel):
    deleted: int


class RecallOverview(BaseModel):
    legacy_pending: int = 0
    evaluated_empty: int = 0
    questions: Dict[str, Dict[str, int]] = Field(description="tipo -> stato -> numero")
    answers: int
    refill_thresholds: Dict[str, int] = Field(default_factory=dict,
                                              description="tipo -> domande da porre a cui il pool si rifornisce")


class RecallUnit(BaseModel):
    unit_id: str
    title: str
    category: Optional[str] = Field(None, description="didactic | organizational | no_content; null se non classificata")
    score: Optional[float] = Field(None, description="Score del classificatore (0-2)")
    level: Optional[int] = Field(None, description="Livello: 0 nessuna domanda, 1 una, 2 più domande")
    confidence: Optional[float] = None
    error: Optional[str] = None
    suggested: bool = Field(description="Rilevante secondo il classificatore: selezionata di predefinito")
    selected: bool


class RecallUnits(BaseModel):
    units: List[RecallUnit]
    custom: bool = Field(description="La selezione è stata cambiata dall'utente")
    classifier: str = Field(description="Modo del classificatore: disabled | shadow | active")
    selected: int


class RecallUnitSelection(BaseModel):
    unit_ids: Optional[List[str]] = Field(None, description="Unità selezionate; null torna alla selezione predefinita")


class RecallAnswerRecord(BaseModel):
    question_id: str
    answer_text: str
    is_voice: bool = False
    evaluation: Optional[str] = None
    vote: Optional[str] = Field(None, description="up | down | lightning")
    answered_at: str


class RecallHistory(BaseModel):
    questions: List[RecallQuestion]
    answers: List[RecallAnswerRecord]


class RecallGenerate(BaseModel):
    qtype: Optional[QuestionType] = Field(None, description="Vuoto: rigenera il pool di tutti i tipi dalle unità selezionate (aggiunge domande, non ne toglie)")
    count: Optional[int] = Field(None, ge=1, le=50)
    mock: bool = False


class RecallAnswer(BaseModel):
    question_id: str
    choice: Optional[int] = Field(None, description="Quiz: indice dell'opzione (0-3)")
    answer: Optional[str] = Field(None, description="Mirata/vasta: risposta scritta (valutata da un job)")
    mock: bool = False


class QuizResult(BaseModel):
    question: RecallQuestion
    correct: bool


class RecallVote(BaseModel):
    question_id: str
    vote: Literal["up", "down", "lightning"]


class RecallSkip(BaseModel):
    question_id: str


class RecallSummary(BaseModel):
    questions: int = Field(description="Domande poste nella sessione")
    answered: int = Field(description="Risposte date")
    quiz_answered: int = Field(description="Quiz a cui si è risposto")
    correct: int = Field(description="Quiz con la risposta giusta")


class RecallSessionInfo(BaseModel):
    id: int
    lesson_id: Optional[int] = None
    lesson_title: str = ""
    subject: Optional[str] = Field(None, description="Materia, per una sessione su tutte le sue lezioni")
    channel: Literal["web", "telegram"]
    state: Literal["active", "ended", "interrupted"]
    qtype: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    ended_by: Optional[str] = Field(None, description="web | telegram | app")
    questions: int = Field(0, description="Domande chieste finora dalla web app")
    summary: Optional[RecallSummary] = Field(None, description="Riepilogo salvato alla chiusura")


class TelegramCommandInfo(BaseModel):
    id: int
    kind: Literal["start_recall", "stop_recall"]
    state: Literal["pending", "running", "done", "failed"]
    error: Optional[str] = None
    created_at: Optional[str] = None
    processed_at: Optional[str] = None


class RecallSessionState(BaseModel):
    web: Optional[RecallSessionInfo] = Field(None, description="Sessione in corso nella web app")
    last: Optional[RecallSessionInfo] = Field(None, description="Ultima sessione web chiusa, con il riepilogo")
    telegram: Optional[RecallSessionInfo] = Field(None, description="Sessione in corso su Telegram per questa lezione")
    command: Optional[TelegramCommandInfo] = Field(None, description="Ultima richiesta al bot per questa lezione")


class ClassificationStatus(BaseModel):
    state: Literal["done", "partial", "stale", "never", "running", "disabled", "unavailable"] = Field(
        description="done: tutte le unità classificate; partial: solo alcune; stale: da rieseguire (testo o configurazione "
                    "cambiati); never: mai eseguito; running: classificazione in coda o in corso; disabled: classificatore "
                    "spento; unavailable: lezione senza bozza")
    classified: int = 0
    total: int = 0


class LessonRecallStats(BaseModel):
    lesson_id: int
    ready: bool = Field(description="Rielaborazione valida: la lezione può fare recall")
    questions: Dict[str, Dict[str, int]] = Field(description="tipo -> stato -> numero")
    answers: int
    telegram: bool = Field(False, description="Sessione in corso su Telegram per la lezione")
    classification: Optional[ClassificationStatus] = Field(None, description="Classificatore sulla lezione (null se non pronta)")


class SubjectRecall(BaseModel):
    materia: str = Field(description="Vuota per le lezioni senza materia; GIORNO:<data> per una sessione del giorno in corso")
    lessons: List[LessonRecallStats]
    session: Optional[RecallSessionInfo] = Field(None, description="Sessione per materia in corso nella web app")


class SubjectRecallState(SubjectRecall):
    last: Optional[RecallSessionInfo] = Field(None, description="Ultima sessione per materia chiusa, con il riepilogo")


class SubjectQuestion(BaseModel):
    lesson_id: int
    question: RecallQuestion


class SubjectGenerateAccepted(BaseModel):
    jobs: List[JobAccepted] = Field(description="Un job recall_generate per ogni lezione pronta senza domande")


class TelegramRecallStart(BaseModel):
    qtype: QuestionType = "quiz"
    mock: bool = False


class TelegramRecallStatus(BaseModel):
    configured: bool = Field(description="Token e chat del bot salvati")
    running: bool = Field(description="Bot in esecuzione")
    sessions: List[RecallSessionInfo] = Field(description="Sessioni di recall in corso su Telegram, per tutte le lezioni")


class SectionLabelRow(BaseModel):
    section_id: str
    title: str
    unit_ids: List[str]
    fresh: bool = Field(description="Classificata sul testo attuale")
    esercizio: Optional[str] = None
    caso: Optional[str] = None
    override_esercizio: Optional[str] = None
    override_caso: Optional[str] = None
    error: Optional[str] = None


class SectionLabels(BaseModel):
    mode: Literal["active", "mock", "disabled"]
    sections: List[SectionLabelRow]
    options: Dict[str, List[str]]


class SectionLabelOverride(BaseModel):
    kind: Literal["esercizio", "caso"]
    value: Optional[str] = Field(None, description="Nuovo valore; null torna a quello del classificatore")
