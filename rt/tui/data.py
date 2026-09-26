"""
rt.tui.data
Scansione della cartella lezioni (telegram.lessons_root) e calcolo dello stato di
ciascuna lezione per la dashboard principale. Riusa la stessa logica già impiegata
da 'rt status'/'rt cost', nessuna duplicazione di regole di stato.
"""
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.core.lesson_paths import lesson_path
from rt.core.state import WorkflowState, compute_effective_workflow_state, read_info_yaml
from rt.pipeline.cost import compute_lesson_cost
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review import load_science_issues
# Spostate nel service layer (RT4-E2): le usano anche web e API.
from rt.services.lesson_service import load_markdown_preview, strip_yaml_frontmatter  # noqa: F401
from rt.storage import fs

PHASES = ["prepare", "outline", "rewrite", "review", "build"]

# Ogni WorkflowState è legato a un'etichetta e a un token di colore SEMANTICO di
# Textual ($primary, $warning, ...), mai a un colore fisso, così la dashboard resta
# leggibile sia in tema scuro che chiaro senza codice dedicato per stato.
STATE_BADGE = {
    WorkflowState.METADATA_ONLY: ("METADATA", "secondary"),
    WorkflowState.SETUP_COMPLETED: ("SETUP", "secondary"),
    WorkflowState.PREPARED: ("PREPARATA", "primary"),
    WorkflowState.OUTLINE_VALIDATED: ("OUTLINE", "primary"),
    WorkflowState.DRAFT_VALIDATED: ("REWRITE", "primary"),
    WorkflowState.REVIEW_READY: ("REVISIONATA", "accent"),
    WorkflowState.HUMAN_REVIEW_REQUIRED: ("REVISIONE", "warning"),
    WorkflowState.READY_TO_BUILD: ("PRONTA BUILD", "accent"),
    WorkflowState.COMPLETED: ("COMPLETATA", "success"),
    WorkflowState.FAILED: ("FALLITA", "error"),
}


@dataclass
class LessonSummary:
    dir_path: str
    title: str
    subject: str
    recorded: str
    when: str
    state: Optional[WorkflowState]
    phase_status: List[Tuple[str, PhaseStatus]]
    pending_issues: int
    cost_total: Optional[float]
    mtime: float
    error: Optional[str] = None


def badge_for_state(state: Optional[WorkflowState]) -> Tuple[str, str]:
    if state is None:
        return ("SCONOSCIUTO", "secondary")
    return STATE_BADGE.get(state, (state.value.upper(), "secondary"))


def _relative_time(mtime: float) -> str:
    delta = max(0.0, time.time() - mtime)
    if delta < 60:
        return "adesso"
    if delta < 3600:
        return f"{int(delta // 60)}m fa"
    if delta < 86400:
        return f"{int(delta // 3600)}h fa"
    days = int(delta // 86400)
    return "ieri" if days <= 1 else f"{days}g fa"


def _lesson_dirs(root: str) -> List[str]:
    if not root or not fs.isdir(root):
        return []
    found = []
    for name in sorted(fs.listdir(root)):
        full = os.path.join(root, name)
        if fs.isdir(full) and fs.isfile(lesson_path(full, "info.yaml")):
            found.append(full)
    return found


def _lesson_mtime(lesson_dir: str) -> float:
    info_path = lesson_path(lesson_dir, "info.yaml")
    try:
        return fs.getmtime(info_path)
    except OSError:
        return fs.getmtime(lesson_dir)


def load_lesson_summary(lesson_dir: str) -> LessonSummary:
    mtime = _lesson_mtime(lesson_dir)
    title = os.path.basename(lesson_dir.rstrip(os.sep))
    try:
        info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
        ledger = load_ledger(lesson_dir)
        sci_issues = load_science_issues(lesson_dir)
        decided_ids = {d.issue_id for d in ledger.decisions}
        pending = sum(1 for x in sci_issues if x.id not in decided_ids)
        phase_status = [(ph, check_phase_status(lesson_dir, ph)[0]) for ph in PHASES]
        cost_data = compute_lesson_cost(lesson_dir)
        return LessonSummary(
            dir_path=lesson_dir,
            title=title,
            subject=info.get("materia") or "",
            recorded=info.get("data") or "",
            when=_relative_time(mtime),
            state=compute_effective_workflow_state(lesson_dir),
            phase_status=phase_status,
            pending_issues=pending,
            cost_total=(cost_data or {}).get("total_estimated_cost_usd"),
            mtime=mtime,
        )
    except Exception as exc:
        # Una lezione con stato illeggibile non deve impedire la lista delle altre:
        # viene mostrata comunque, marcata in errore, invece di far fallire l'intera scansione.
        return LessonSummary(
            dir_path=lesson_dir, title=title, subject="", recorded="", when=_relative_time(mtime),
            state=None, phase_status=[(ph, PhaseStatus.MISSING) for ph in PHASES],
            pending_issues=0, cost_total=None, mtime=mtime, error=str(exc),
        )


def discover_lessons(root: Optional[str]) -> List[LessonSummary]:
    if not root:
        return []
    summaries = [load_lesson_summary(d) for d in _lesson_dirs(root)]
    summaries.sort(key=lambda s: s.mtime, reverse=True)
    return summaries

