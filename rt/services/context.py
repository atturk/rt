"""
rt.services.context
Contesto di esecuzione di una run della pipeline: dove lavorare, come riportare gli eventi,
dove accumulare la telemetria LLM e come chiedere l'annullamento. Sostituisce, per chi lo
usa, i singleton globali di processo: due run nello stesso processo con due RunContext
diversi non si mescolano costi ed eventi.
"""
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional

from rt.llm.telemetry import TelemetryStore, use_telemetry
from rt.services.events import (
    CostUpdated,
    Event,
    NullReporter,
    PhaseCompleted,
    PhaseFailed,
    PhaseProgress,
    PhaseStarted,
    Reporter,
)


class RunCancelled(Exception):
    """La run è stata annullata tramite CancelToken; il lavoro già salvato resta valido."""


class CancelToken:
    """Flag di annullamento controllabile da un altro thread (API, worker, segnale)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise RunCancelled("Esecuzione annullata")


@dataclass
class RunContext:
    lesson_dir: Optional[str] = None
    force: bool = False
    force_mock: bool = False
    reporter: Reporter = field(default_factory=NullReporter)
    telemetry: TelemetryStore = field(default_factory=TelemetryStore)
    cancel_token: CancelToken = field(default_factory=CancelToken)

    def emit(self, event: Event) -> None:
        self.reporter.emit(event)

    def check_cancelled(self) -> None:
        self.cancel_token.raise_if_cancelled()

    def progress(self, phase: str, current: Optional[int] = None, total: Optional[int] = None, message: str = "",
                 **unit: Any) -> None:
        """unit: unit_id, unit_title, failed (fasi a unità)."""
        self.emit(PhaseProgress(phase=phase, current=current, total=total, message=message, **unit))

    def emit_cost(self) -> None:
        s = self.telemetry.get_summary()
        self.emit(CostUpdated(
            total_requests=s["total_requests"],
            total_estimated_cost_usd=s["total_estimated_cost_usd"],
            by_job=s["by_job"],
        ))

    @contextmanager
    def activate(self) -> Iterator["RunContext"]:
        """Rende la telemetria di questo contesto quella corrente per il client LLM."""
        with use_telemetry(self.telemetry):
            yield self


def _sanitize(message: str) -> str:
    try:
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        return GLOBAL_CREDENTIALS.sanitize_secrets(message)
    except Exception:
        return message


class _PhaseScope:
    def __init__(self, ctx: Optional[RunContext], phase: str, step: Optional[int], total_steps: Optional[int]):
        self.ctx = ctx
        self.phase = phase
        self.step = step
        self.total_steps = total_steps

    def complete(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if self.ctx is not None:
            skipped = bool(result.get("skipped")) or result.get("action") == "SKIP"
            self.ctx.emit(PhaseCompleted(
                phase=self.phase, result=result, skipped=skipped, partial=bool(result.get("failed_units")),
                step=self.step, total_steps=self.total_steps,
            ))
        return result


@contextmanager
def phase_scope(
    ctx: Optional[RunContext],
    phase: str,
    step: Optional[int] = None,
    total_steps: Optional[int] = None,
) -> Iterator[_PhaseScope]:
    """Incornicia l'esecuzione di una fase: PhaseStarted all'ingresso, PhaseFailed su
    eccezione (poi rilanciata), CostUpdated all'uscita se sono cambiati i costi. Il
    PhaseCompleted parte da scope.complete(result). Senza contesto non fa nulla."""
    scope = _PhaseScope(ctx, phase, step, total_steps)
    if ctx is None:
        yield scope
        return
    requests_before = ctx.telemetry.get_summary()["total_requests"]
    ctx.emit(PhaseStarted(phase=phase, step=step, total_steps=total_steps))
    try:
        with ctx.activate():
            yield scope
    except BaseException as exc:
        ctx.emit(PhaseFailed(
            phase=phase,
            error_class=getattr(exc, "failure_class", None) or type(exc).__name__,
            message=_sanitize(str(exc)),
        ))
        raise
    finally:
        if ctx.telemetry.get_summary()["total_requests"] != requests_before:
            ctx.emit_cost()
