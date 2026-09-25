"""
rt.cli_reporter
Traduce gli eventi del service layer (rt.services.events) nelle stesse righe che la CLI
stampa da sempre. È l'unico punto in cui la presentazione a terminale delle fasi vive.
"""
from typing import Any, Callable, Dict, Optional, Tuple

from rt.services.events import Event, Notice, PhaseCompleted

# Descrizioni mostrate da 'rt run' nell'intestazione "[n/N] FASE (descrizione)...".
RUN_PHASE_DESCRIPTIONS = {
    "prepare": "Parsing deterministico segmenti",
    "outline": "Scaletta gerarchica didattica",
    "rewrite": "Rielaborazione fluida a finestre con provenance",
    "review": "Critic indipendente su correttezza scientifica",
    "build": "Finalizzazione deterministica Markdown",
}


def run_phase_details(phase: str, res: Dict[str, Any]) -> Optional[str]:
    """Riga di dettaglio di 'rt run' per il risultato di una fase."""
    skipped = res.get("skipped")
    if phase == "prepare":
        if skipped:
            return f"Segmenti già validi ({res['segment_count']} segmenti, {res['duration_seconds']:.1f}s)"
        return f"Segmenti estratti: {res['segment_count']} ({res['duration_seconds']:.1f}s)"
    if phase == "outline":
        rep = res["validation_report"]
        if skipped:
            return f"Outline già valida ({rep['units_count']} unità didattiche, 0 chiamate LLM)"
        return f"Outline validata: {rep['units_count']} unità didattiche ({rep['coverage_percentage']}% copertura)"
    if phase == "rewrite":
        if skipped:
            return f"Draft già valido ({res['total_units']} unità verificate, 0 chiamate LLM)"
        return f"Rielaborate {res['processed_units']}/{res['total_units']} unità. Provenance verificata."
    if phase == "review":
        if skipped:
            return f"Review scientifica già completata ({res['total_science_issues']} issue note, 0 chiamate LLM)"
        return f"Issue scientifiche: {res['total_science_issues']} (Concettuali: {res.get('concettuale_issues', 0)})"
    if phase == "build":
        if skipped:
            return "Documenti finali già generati e aggiornati."
        return (
            "File finali generati con successo:\n"
            f"  - Rielaborato: {res['rielaborato']}\n"
            f"  - Pre-elaborato: {res['pre_elaborato']}\n"
            f"  - Errori concettuali: {res['errori_concettuali']}"
        )
    return None


def format_phase_action(
    phase_name: str,
    res: Dict[str, Any],
    step: Optional[int] = None,
    total_steps: Optional[int] = None,
    description: Optional[str] = None,
    details: Optional[str] = None,
) -> str:
    """Testo stampato al termine di una fase (stesse stringhe di sempre, newline inclusi)."""
    action = res.get("action", "RUN")
    reason = res.get("reason", "")
    skipped = res.get("skipped", False) or action == "SKIP"

    if step is not None and total_steps is not None:
        header_desc = f" ({description})" if description else ""
        lines = [f"\n[{step}/{total_steps}] {phase_name.upper()}{header_desc}..."]
        if skipped:
            msg = details if details else f"{phase_name} già valido ({reason})"
            lines.append(f"⏩ [SKIP] {msg}")
        elif action == "FORCE":
            msg = details if details else f"{phase_name} completato (rigenerazione forzata)."
            lines.append(f"✔ [FORCE] {msg}")
        else:
            msg = details if details else f"{phase_name} completato."
            lines.append(f"✔ {msg}")
        return "\n".join(lines)
    if action == "SKIP":
        return f"\n[SKIP] {phase_name}\nReason: {reason}\n"
    if action == "FORCE":
        return f"\n[FORCE] {phase_name}\nReason: {reason}\n✔ {phase_name} completato (rigenerazione forzata).\n"
    return f"\n[RUN] {phase_name}\nReason: {reason}\n✔ {phase_name} completato.\n"


def format_cost_summary(summary: Dict[str, Any]) -> Optional[str]:
    """Riepilogo costi di fine 'rt run'; None se non ci sono state richieste LLM."""
    if summary.get("total_requests", 0) <= 0:
        return None
    lines = ["\n" + "=" * 60, "💰 RIEPILOGO COSTI SESSIONE", "=" * 60]
    for job_name, job_stats in summary["by_job"].items():
        lines.append(f"  {job_name:<16} {job_stats['requests']:>3} richieste  ${job_stats['estimated_cost_usd']:.6f}")
    lines.append(f"  {'TOTALE':<16}     ${summary['total_estimated_cost_usd']:.6f}")
    lines.append("=" * 60)
    return "\n".join(lines)


class CliReporter:
    """Reporter per il terminale.

    steps: fase -> (numero di passo, descrizione) per la numerazione "[n/N]" di 'rt run';
    le fasi assenti (o senza steps) usano il formato dei comandi singoli ("[RUN] fase").
    """

    def __init__(
        self,
        steps: Optional[Dict[str, Tuple[int, str]]] = None,
        total_steps: Optional[int] = None,
        out: Callable[[str], None] = print,
    ) -> None:
        self.steps = steps or {}
        self.total_steps = total_steps
        self.out = out

    def emit(self, event: Event) -> None:
        if isinstance(event, PhaseCompleted):
            self.out(self.render_phase(event.phase, event.result))
        elif isinstance(event, Notice):
            self.out(event.message)

    def render_phase(self, phase: str, res: Dict[str, Any]) -> str:
        if phase in self.steps and self.total_steps is not None:
            step, description = self.steps[phase]
            return format_phase_action(
                phase, res, step=step, total_steps=self.total_steps,
                description=description, details=run_phase_details(phase, res),
            )
        return format_phase_action(phase, res)
