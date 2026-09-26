"""
rt.services.events
Eventi tipizzati emessi durante l'esecuzione della pipeline e il protocollo Reporter che li
riceve. Le interfacce (CLI, web, API, worker) traducono gli eventi nella propria
presentazione; il motore non sa chi li ascolta.
"""
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol, Union

from pydantic import BaseModel, Field

PHASES = ("setup", "prepare", "outline", "rewrite", "review", "build")


class _Event(BaseModel):
    type: str


class PhaseStarted(_Event):
    type: Literal["phase_started"] = "phase_started"
    phase: str
    step: Optional[int] = None
    total_steps: Optional[int] = None


class PhaseProgress(_Event):
    type: Literal["phase_progress"] = "phase_progress"
    phase: str
    current: Optional[int] = None
    total: Optional[int] = None
    message: str = ""
    # Fasi a unità: unità in lavorazione e quante sono fallite finora (dati strutturati per
    # l'interfaccia, es. "Revisione · 8/31", senza leggere il messaggio)
    unit_id: Optional[str] = None
    unit_title: Optional[str] = None
    failed: Optional[int] = None


class PhaseCompleted(_Event):
    type: Literal["phase_completed"] = "phase_completed"
    phase: str
    result: Dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    partial: bool = Field(False, description="Fase finita PARTIAL: alcune unità non sono riuscite (result.failed_units)")
    step: Optional[int] = None
    total_steps: Optional[int] = None


class PhaseFailed(_Event):
    type: Literal["phase_failed"] = "phase_failed"
    phase: str
    error_class: str
    message: str = Field(description="Messaggio già sanificato: nessun segreto")


class CostUpdated(_Event):
    type: Literal["cost_updated"] = "cost_updated"
    total_requests: int = 0
    total_estimated_cost_usd: float = 0.0
    by_job: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


DecisionKind = Literal["outline_approval", "science_issue", "setup_metadata"]


class DecisionRequired(_Event):
    type: Literal["decision_required"] = "decision_required"
    kind: DecisionKind
    id: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class Notice(_Event):
    """Messaggio informativo libero (avvisi, riepiloghi) che non appartiene a una fase."""
    type: Literal["notice"] = "notice"
    message: str
    level: Literal["info", "warning", "error"] = "info"


Event = Union[PhaseStarted, PhaseProgress, PhaseCompleted, PhaseFailed, CostUpdated, DecisionRequired, Notice]


class Reporter(Protocol):
    def emit(self, event: Event) -> None: ...


class NullReporter:
    """Scarta tutti gli eventi (default quando nessuno ascolta)."""

    def emit(self, event: Event) -> None:
        return None


class ListReporter:
    """Accumula gli eventi in memoria: utile per test e per job che li salvano in blocco."""

    def __init__(self) -> None:
        self.events: List[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, event_type: type) -> List[Event]:
        return [e for e in self.events if isinstance(e, event_type)]


class CallbackReporter:
    """Inoltra ogni evento a una funzione."""

    def __init__(self, callback: Callable[[Event], None]) -> None:
        self._callback = callback

    def emit(self, event: Event) -> None:
        self._callback(event)


class FanOutReporter:
    """Inoltra ogni evento a più reporter, nell'ordine."""

    def __init__(self, *reporters: Reporter) -> None:
        self.reporters = [r for r in reporters if r is not None]

    def emit(self, event: Event) -> None:
        for r in self.reporters:
            r.emit(event)
