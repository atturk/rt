"""
rt.pipeline.unit_failures
Fasi a unità (rewrite, review, immagini, recall): il fallimento definitivo di UNA unità (il
modello risponde fuori schema anche dopo i nuovi tentativi e il failover, un timeout che non
passa...) non abbatte la fase. L'unità resta fuori dal checkpoint, le altre proseguono e la
fase finisce PARTIAL: rilanciarla rifà solo le unità mancanti.

Gli errori che riguardano tutte le unità (credenziale mancante o rifiutata) o le interruzioni
(annullamento, Ctrl+C) fermano invece subito la fase, come prima. Dopo alcune unità fallite di
fila la fase si ferma lo stesso: il problema non è della singola unità.
"""
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from rt.llm.errors import AuthenticationFailure, LLMFailure, describe_llm_failure

MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class UnitFailure:
    unit_id: str
    label: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def is_unit_failure(exc: BaseException) -> bool:
    """Errore della singola unità (si prosegue con le altre)? Solo errori LLM che non
    dipendono dalla configurazione: una credenziale mancante fallirebbe ovunque."""
    return isinstance(exc, LLMFailure) and not isinstance(exc, AuthenticationFailure)


def unit_failure(unit_id: str, label: str, exc: BaseException) -> UnitFailure:
    return UnitFailure(unit_id=unit_id, label=label, message=describe_llm_failure(exc))


class UnitFailureTracker:
    """Raccoglie le unità fallite di una fase; too_many() dopo MAX_CONSECUTIVE_FAILURES di fila."""

    def __init__(self) -> None:
        self.failures: List[UnitFailure] = []
        self._streak = 0

    def failed(self, unit_id: str, label: str, exc: BaseException) -> UnitFailure:
        failure = unit_failure(unit_id, label, exc)
        self.failures.append(failure)
        self._streak += 1
        return failure

    def succeeded(self) -> None:
        self._streak = 0

    def too_many(self) -> bool:
        return self._streak >= MAX_CONSECUTIVE_FAILURES

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self.failures]


PHASE_NAMES_IT = {
    "rewrite": "Rielaborazione",
    "review": "Revisione",
    "add_images": "Immagini",
    "recall": "Domande di recall",
}


class PhaseIncomplete(RuntimeError):
    """Fase finita PARTIAL per unità non riuscite: il job fallisce con un messaggio leggibile
    e 'Riprova' rifà solo le unità mancanti."""

    def __init__(self, phase: str, failed_units: List[Dict[str, Any]], done: Optional[int] = None,
                 total: Optional[int] = None, stopped_early: bool = False):
        self.phase = phase
        self.failed_units = list(failed_units)
        self.done, self.total = done, total
        self.stopped_early = stopped_early
        super().__init__(describe_incomplete(phase, self.failed_units, done, total, stopped_early))


def describe_incomplete(phase: str, failed_units: List[Dict[str, Any]], done: Optional[int] = None,
                        total: Optional[int] = None, stopped_early: bool = False, max_listed: int = 3) -> str:
    name = PHASE_NAMES_IT.get(phase, phase)
    count = f" ({done}/{total} unità completate)" if done is not None and total else ""
    head = f"{name} incompleta{count}."
    if stopped_early:
        head += f" Fermata dopo {MAX_CONSECUTIVE_FAILURES} unità fallite di fila."
    parts = [head]
    for failure in failed_units[:max_listed]:
        parts.append(f"Unità {failure.get('label') or failure.get('unit_id')}: {failure.get('message')}.")
    if len(failed_units) > max_listed:
        parts.append(f"Altre {len(failed_units) - max_listed} unità non riuscite.")
    parts.append("Le unità completate sono salvate: Riprova rifà solo quelle mancanti.")
    return " ".join(parts)


def raise_if_incomplete(phase: str, result: Dict[str, Any]) -> None:
    """Chiamata dall'orchestratore dopo una fase: se ci sono unità fallite la pipeline si
    ferma qui (le fasi successive lavorerebbero su dati incompleti)."""
    failed = result.get("failed_units") or []
    if failed:
        raise PhaseIncomplete(phase, failed, result.get("completed_units"), result.get("expected_units"),
                              bool(result.get("stopped_early")))
